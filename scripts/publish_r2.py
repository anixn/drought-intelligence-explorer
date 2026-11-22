"""Publish an immutable data snapshot to Cloudflare R2 (M7.1).

The dashboard reads bulk data over HTTP Range requests, so the store does not
have to live in git. This script uploads one *versioned* snapshot and writes the
committed pointer (`data/data-source.json`). A monthly refresh is then a
kilobyte-scale commit instead of ~13 MB of git history.

What is uploaded (keys are relative to the snapshot prefix):

    parquet/…            the whole Parquet store (observed, atlas, projections,
                         cross_validation, catalog.json, _national_monthly)
    drought/*.csv        the ten era-B wide CSVs (first-paint path)
    SHA256SUMS.txt       generated here, per object + sizes

What is NOT uploaded: metadata.json, status.json, reality_checks.json and the
boundary GeoJSON — they stay in the repository with the code.

Usage (never prints or stores secrets):

    set R2_ACCOUNT_ID=…            # Cloudflare dashboard → R2 → API
    set R2_ACCESS_KEY_ID=…
    set R2_SECRET_ACCESS_KEY=…
    python scripts/publish_r2.py --version v2026.09 --dry-run
    python scripts/publish_r2.py --version v2026.09 --write-pointer \
        --public-base https://pub-xxxxxxxx.r2.dev/

Options:
    --bucket          bucket name (default die-data)
    --endpoint        S3 endpoint (default https://<account>.r2.cloudflarestorage.com)
    --max-total-gb    refuse if bucket usage + this snapshot would exceed it (default 8)
    --concurrency     parallel uploads (default 8)
    --no-csv          skip the wide CSVs (Parquet only)
    --force           allow re-uploading an existing version
    --dry-run         print the plan, hash nothing to R2, touch nothing

Requires boto3 (`pip install boto3`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^v\d{4}\.\d{2}(?:\.\d+)?$")
CACHE_CONTROL = "public, max-age=31536000, immutable"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def plan(version: str, include_csv: bool, only: set[str] | None = None) -> list[tuple[Path, str]]:
    """(local path, object key relative to the snapshot prefix)."""
    items: list[tuple[Path, str]] = []
    parquet = REPO / "data" / "parquet"
    wanted = only or None

    def keep(group: str) -> bool:
        if wanted is None:
            return True
        if group == "csv":
            return include_csv and "csv" in wanted
        return group in wanted

    for path in sorted(parquet.rglob("*.parquet")):
        rel = "parquet/" + str(path.relative_to(parquet)).replace("\\", "/")
        group = ("national" if rel.startswith("parquet/_national_monthly")
                 else rel.split("/")[1])
        if keep(group):
            items.append((path, rel))
    catalog = parquet / "catalog.json"
    if catalog.exists() and keep("catalog"):
        items.append((catalog, "parquet/catalog.json"))
    if keep("csv"):
        for path in sorted((REPO / "data" / "drought").glob("*.csv")):
            items.append((path, "drought/" + path.name))
    return items


GROUPS = {"observed", "atlas", "projections", "cross_validation",
          "national", "catalog", "csv"}


def client(endpoint: str | None, bucket: str):
    try:
        import boto3  # noqa: F401
        from botocore.config import Config
    except ImportError:
        raise SystemExit(
            "boto3 is required: pip install boto3\n"
            "(The rest of the repository does not need it.)")
    account = os.environ.get("R2_ACCOUNT_ID", "").strip()
    key = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
    secret = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
    if not endpoint:
        if not account:
            raise SystemExit("set R2_ACCOUNT_ID or pass --endpoint")
        endpoint = f"https://{account}.r2.cloudflarestorage.com"
    if not (key and secret):
        raise SystemExit("set R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY")
    import boto3
    return boto3.client(
        "s3", endpoint_url=endpoint, aws_access_key_id=key,
        aws_secret_access_key=secret, region_name="auto",
        config=Config(retries={"max_attempts": 5, "mode": "standard"}))


def bucket_bytes(s3, bucket: str) -> int:
    total = 0
    token = None
    while True:
        kw = {"Bucket": bucket, "MaxKeys": 1000}
        if token:
            kw["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kw)
        for obj in resp.get("Contents", []):
            total += int(obj.get("Size", 0))
        if not resp.get("IsTruncated"):
            return total
        token = resp.get("NextContinuationToken")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Publish a data snapshot to R2")
    ap.add_argument("--version", required=True,
                    help="snapshot prefix, e.g. v2026.09")
    ap.add_argument("--bucket", default=os.environ.get("R2_BUCKET", "die-data"))
    ap.add_argument("--endpoint", default=os.environ.get("R2_ENDPOINT"))
    ap.add_argument("--max-total-gb", type=float, default=8.0)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--no-csv", action="store_true")
    ap.add_argument("--only", default=None,
                    help="comma-separated subset for a smoke test: "
                         "observed,atlas,projections,cross_validation,national,catalog,csv")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--prune", action="store_true",
                    help="after a full upload, delete objects under this version "
                         "that are not in the local manifest (cleans stale keys)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--write-pointer", action="store_true")
    ap.add_argument("--public-base", default=None,
                    help="public URL of the snapshot prefix (r2.dev or custom domain)")
    args = ap.parse_args(argv)

    version = args.version if args.version.startswith("v") else "v" + args.version
    if not VERSION_RE.match(version):
        raise SystemExit("version must look like v2026.09 or v2.0.0")
    prefix = version + "/"

    only = None
    if args.only:
        only = {s.strip() for s in args.only.split(",") if s.strip()}
        bad = only - GROUPS
        if bad:
            raise SystemExit("unknown group(s): " + ", ".join(sorted(bad)) +
                             " (choose from " + ", ".join(sorted(GROUPS)) + ")")
        print("PARTIAL upload (smoke test): " + ", ".join(sorted(only)))
    partial = only is not None

    items = plan(version, include_csv=not args.no_csv, only=only)
    if not items:
        raise SystemExit("nothing to upload: check --only / --no-csv")
    total = sum(p.stat().st_size for p, _ in items)
    by_group: dict[str, int] = {}
    for p, key in items:
        group = key.split("/")[0] if "/" in key else "root"
        by_group[group] = by_group.get(group, 0) + p.stat().st_size

    print(f"snapshot   : {version}")
    print(f"bucket     : {args.bucket}")
    print(f"objects    : {len(items):,}")
    print(f"bytes      : {total / 1e6:.1f} MB")
    for g, n in sorted(by_group.items(), key=lambda kv: -kv[1]):
        print(f"  {g:<22} {n / 1e6:8.1f} MB")
    if total / 1e9 > args.max_total_gb:
        print(f"REFUSED: this snapshot alone is {total / 1e9:.2f} GB "
              f"> --max-total-gb {args.max_total_gb}")
        return 2
    if args.dry_run:
        print("\ndry run: nothing uploaded")
        for p, key in items[:5]:
            print(f"  {prefix + key}  <-  {p.relative_to(REPO)}")
        if len(items) > 5:
            print(f"  … {len(items) - 5:,} more")
        return 0

    s3 = client(args.endpoint, args.bucket)
    used = bucket_bytes(s3, args.bucket)
    projected = (used + total) / 1e9
    print(f"bucket use : {used / 1e9:.2f} GB now -> {projected:.2f} GB after this upload")
    if projected > args.max_total_gb and not args.force:
        print(f"REFUSED: would exceed --max-total-gb {args.max_total_gb} "
              f"(old snapshots are never deleted automatically). "
              f"Delete an old prefix or pass --force.")
        return 2

    marker_key = prefix + "_READY"
    exists = False
    try:
        s3.head_object(Bucket=args.bucket, Key=marker_key)
        exists = True
    except Exception:
        exists = False
    if exists and not args.force:
        raise SystemExit(f"{version} already has a _READY marker; pass --force to "
                         f"overwrite (snapshots are meant to be immutable)")

    checksums: list[str] = []
    uploaded = skipped = 0

    def put(p: Path, key: str) -> tuple[str, bool]:
        full = prefix + key
        digest = sha256(p)
        size = p.stat().st_size
        try:
            head = s3.head_object(Bucket=args.bucket, Key=full)
            same = int(head.get("ContentLength", -1)) == size and \
                (head.get("Metadata") or {}).get("sha256") == digest
            if same:
                return f"{digest}  {key}", False
        except Exception:
            pass
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        s3.upload_file(str(p), args.bucket, full,
                       ExtraArgs={"ContentType": ctype,
                                  "CacheControl": CACHE_CONTROL,
                                  "Metadata": {"sha256": digest}})
        return f"{digest}  {key}", True

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(put, p, key) for p, key in items]
        done = 0
        for fut in as_completed(futures):
            line, did = fut.result()
            checksums.append(line)
            uploaded += 1 if did else 0
            skipped += 0 if did else 1
            done += 1
            if done % 500 == 0 or done == len(futures):
                print(f"  {done:,}/{len(items):,} objects "
                      f"(uploaded {uploaded:,}, unchanged {skipped:,})")

    if partial:
        s3.put_object(Bucket=args.bucket, Key=prefix + "_PARTIAL",
                      Body=json.dumps({
                          "version": version, "groups": sorted(only),
                          "objects": len(items), "bytes": total,
                          "created": date.today().isoformat(),
                          "note": "smoke test only; run the full upload to write _READY",
                      }, indent=1).encode(),
                      ContentType="application/json", CacheControl=CACHE_CONTROL)
        print(f"\nuploaded {uploaded:,} object(s), {skipped:,} already present")
        print(f"PARTIAL snapshot at {prefix} (no SHA256SUMS, no _READY). "
              f"Run again without --only to complete it.")
        if args.write_pointer:
            raise SystemExit("refusing to write the pointer for a partial snapshot")
        return 0

    checksums.sort(key=lambda s: s.split("  ", 1)[1])
    sums = "\n".join(checksums) + "\n"
    s3.put_object(Bucket=args.bucket, Key=prefix + "SHA256SUMS.txt",
                  Body=sums.encode(), ContentType="text/plain",
                  CacheControl=CACHE_CONTROL)
    s3.put_object(Bucket=args.bucket, Key=marker_key,
                  Body=json.dumps({"version": version, "objects": len(items),
                                   "bytes": total, "created": date.today().isoformat()},
                                  indent=1).encode(),
                  ContentType="application/json", CacheControl=CACHE_CONTROL)
    print(f"\nuploaded {uploaded:,} object(s), {skipped:,} already present")
    print(f"snapshot ready at {prefix}")

    if args.prune:
        keep = {prefix + key for _p, key in items}
        keep |= {prefix + "SHA256SUMS.txt", prefix + "_READY"}
        stale = []
        token = None
        while True:
            kw = {"Bucket": args.bucket, "Prefix": prefix, "MaxKeys": 1000}
            if token:
                kw["ContinuationToken"] = token
            resp = s3.list_objects_v2(**kw)
            for obj in resp.get("Contents", []):
                if obj["Key"] not in keep:
                    stale.append(obj["Key"])
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
        for i in range(0, len(stale), 1000):
            batch = [{"Key": k} for k in stale[i:i + 1000]]
            s3.delete_objects(Bucket=args.bucket, Delete={"Objects": batch,
                                                          "Quiet": True})
        print(f"pruned {len(stale):,} stale object(s) under {prefix}")

    if args.write_pointer:
        base = args.public_base or ""
        if not base:
            raise SystemExit("--write-pointer needs --public-base "
                             "(e.g. https://pub-xxxx.r2.dev/)")
        if not base.endswith("/"):
            base += "/"
        pointer = {
            "schema": "die-data-source/1.0",
            "note": ("Committed pointer to the immutable bulk-data snapshot. Only the "
                     "Parquet store and the era-B wide CSVs move; metadata.json, "
                     "status.json, reality_checks.json and the boundary GeoJSON stay "
                     "with the code. base=null means same-origin."),
            "base": base + prefix,
            "snapshot": version,
            "public_base": base,
            "updated": date.today().isoformat(),
            "uploaded_by": "scripts/publish_r2.py",
        }
        out = REPO / "data" / "data-source.json"
        out.write_text(json.dumps(pointer, indent=1) + "\n", encoding="utf-8")
        print("wrote", out, "->", pointer["base"])
        print("commit data/data-source.json (and the refreshed status/metadata) "
              "to switch the live site; do not commit the data itself.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
