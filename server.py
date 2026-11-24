#!/usr/bin/env python3
"""DIE v2.0 — Range-capable local development server.

The v2.0 architecture (docs/v2/03 §1, docs/v2/05 §3) serves Parquet, PMTiles and
JSON over static files and relies on **HTTP Range requests** so DuckDB-WASM reads
only the byte ranges it needs. Python's stock http.server does not implement
Range; this server adds it.

Usage:
    python server.py [--port 8000] [--directory .]

Endpoints behave like a static host (GitHub Pages / Cloudflare R2 target):
  * GET/HEAD with `Range: bytes=start-end` -> 206 + Content-Range
  * unsatisfiable range                    -> 416 + Content-Range: bytes */size
  * `Accept-Ranges: bytes` advertised on every file response
  * MIME types for .parquet, .pmtiles, .json, .csv, .wasm registered
  * CORS `*` so the front end can be served from a different origin in dev

This server is for development and the M1.5 catalog checks (HTTP 200 + Range)
only. Production hosting is GitHub Pages → Cloudflare R2 (decision OD6).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from http import HTTPStatus
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

# Static-host MIME map (parquet/pmtiles are served as octet-stream by
# GitHub Pages and R2 alike; .wasm must be application/wasm for streaming).
MIME_OVERRIDES = {
    ".parquet": "application/octet-stream",
    ".pmtiles": "application/octet-stream",
    ".wasm": "application/wasm",
    ".json": "application/json",
    ".csv": "text/csv",
    ".html": "text/html",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".pbf": "application/x-protobuf",
}

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


class RangeHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def guess_type(self, path):  # noqa: D102 - see MIME_OVERRIDES
        ext = os.path.splitext(str(path))[1].lower()
        if ext in MIME_OVERRIDES:
            return MIME_OVERRIDES[ext]
        return super().guess_type(path)

    def end_headers(self):
        # CORS for development; harmless on a static host.
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    # -- helpers ---------------------------------------------------------

    def _send_head(self, head_only: bool):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().do_GET()  # directory listing: dev convenience only
        if not os.path.isfile(path):
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return None

        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not readable")
            return None

        size = os.fstat(f.fileno()).st_size
        ctype = self.guess_type(path)
        ext = os.path.splitext(str(path))[1].lower()

        rng = self.headers.get("Range")
        start, end = 0, size - 1
        status = HTTPStatus.OK
        extra = {}

        if rng:
            m = _RANGE_RE.match(rng.strip())
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:  # bytes=-N -> final N bytes
                    start = max(0, size - int(m.group(2)))
                    end = size - 1
                if start >= size or end < start:
                    f.close()
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None
                end = min(end, size - 1)
                status = HTTPStatus.PARTIAL_CONTENT
                extra["Content-Range"] = f"bytes {start}-{end}/{size}"
            else:
                # Malformed Range: serve the full body, ignore the header.
                pass

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        # Pitfall P2 (docs/v2/04 §3.3): browsers heuristically cache HTML/JS/JSON,
        # which serves stale code after edits; data files (.parquet) are
        # content-addressed by the catalog and may cache. Images are included so
        # a replaced logo/favicon shows up on the next reload in development
        # (browsers cache favicons especially aggressively).
        if ext in (".html", ".js", ".mjs", ".json", ".css",
                   ".svg", ".png", ".webp", ".jpg", ".jpeg", ".ico"):
            self.send_header("Cache-Control", "no-cache")
        self.send_header("Last-Modified", self.date_time_string(os.path.getmtime(path)))
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()

        if head_only:
            f.close()
            return None
        return f, start, end

    # -- methods ---------------------------------------------------------

    def do_GET(self):
        head = self._send_head(head_only=False)
        if head is None:
            return
        f, start, end = head
        f.seek(start)
        remaining = end - start + 1
        try:
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client aborted a ranged read; DuckDB does this routinely
        finally:
            f.close()

    def do_HEAD(self):
        self._send_head(head_only=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Range-capable static dev server")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--directory", default=".", help="serve root (default: cwd)")
    args = ap.parse_args()

    handler = RangeHandler
    handler.directory = args.directory
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"DIE dev server: http://127.0.0.1:{args.port}/  (root: {args.directory})")
    print("Range requests: supported (206). Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
