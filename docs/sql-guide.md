# Querying the DIE data store with SQL

*Drought Intelligence Explorer v2.0 — data contract, field reference and recipe book for the
Parquet store. This guide matches the files the dashboard serves: if a query works here, it works
in the **Engine Lab** workspace (`#engine`), in a Python notebook, or in R.*

---

## 1. What runs where

| Where | Engine | Reads |
|---|---|---|
| Dashboard · Engine Lab (`#engine`) | DuckDB-WASM 1.32.0 in a Web Worker | HTTP **Range** requests over the static files |
| Python | `duckdb` (CLI/notebook) or `pyarrow` | the same files on disk |
| R | `duckdb` / `arrow` | the same files on disk |

There is no server, no API key and no database to install. The Parquet files **are** the database.
The browser fetches only the byte ranges a query needs, which is why a 20,000-file store still
answers in tens of milliseconds.

Two consequences worth knowing before you write SQL:

1. **No HTTP globbing.** In the browser you pass DuckDB an explicit list of file paths
   (`read_parquet(['a.parquet', 'b.parquet', …])`), normally built from `data/parquet/catalog.json`.
   `read_parquet('https://…/**/*.parquet')` will not work over HTTP. Locally (Python/R) globs are fine.
2. **Absolute URLs in the browser.** `httpfs` needs `https://host/path.parquet`; relative paths only
   work for local files. Engine Lab's presets already do this for you.

---

## 2. Store layout

```
data/parquet/
├── catalog.json                                  # exact-path manifest (the only index)
├── observed/variable=<id>/part-0.parquet          # era B — 10 files
├── atlas/variable=<id>/year=<yyyy>/part-0.parquet # era A — one file per year
├── projections/scenario=<ssp>/stat=<stat>/variable=<id>/year=<yyyy>/part-0.parquet
│   └── …/stat=members/variable=<id>/model=<GCM>/year=<yyyy>/part-0.parquet
├── cross_validation/
│   ├── overlap_1981_2014.parquet                 # district-month pairs, A vs B
│   ├── per_district_1981_2014.parquet            # one row per district × variable
│   └── monthly_1981_2014.parquet                 # area-weighted monthly agreement
├── _national_monthly.parquet                     # area-weighted national series (all eras-B vars)
└── _tehsil_national_monthly.parquet              # reserved for the tehsil layer (not yet served)
```

Partition keys are **directory names**, not columns: `variable`, `year`, `scenario`, `stat` and
`model` are not in the table schema unless the query selects them from the path (DuckDB can do this
with `filename = true` or `parse_filename`, see §7 R14).

### Which stores are present in this checkout

`data/parquet/projections/` and `data/parquet/atlas/` are **not committed** (large; era C is hosted
separately and era A is published at release — see Documentation N and register D5). The catalog
lists their exact paths regardless, so an `atlas` or `projections` query will 404 until those stores
are provisioned. Era B (`observed/`), the national aggregate and the cross-validation artifacts are
always in the repository.

---

## 3. Schema reference

### 3.1 `district_month` — observed, atlas, projections, and per-model members

The same four columns everywhere, so one query shape works across all three eras.

| Column | Type | Meaning |
|---|---|---|
| `district_id` | `dictionary<string>` | District slug: `state-district`, lower-case, hyphenated — e.g. `gujarat-ahmedabad`, `andaman-and-nicobar-islands-nicobars`. 724 values in era B, 718 in era A (six island districts have no Atlas grid cells), 720 in era C. |
| `year` | `int16` | Calendar year (1901–2025 era A · 1981–2025 era B · 2015–2100 era C). |
| `month` | `int8` | Calendar month, **1–12** (not zero-based). |
| `value` | `float32` | The indicator value in its own units: z-score for SPI/SPEI, **percent** for soil-moisture anomaly, 0–100 for VCI. |

Metadata is carried per file (`source_csv`, `source_sha256`, `variable_id`, `era`, and for era C
`scenario`, `stat`, `stat_definition`, `era_label`) — read it from Parquet metadata, never hard-code it.

**There are no NULLs.** Missing observations are **absent rows** (R10). `count(*)` is therefore the
number of valid district-months, and a gap has to be detected by comparing against the expected
calendar sequence (recipe R12).

### 3.2 `_national_monthly.parquet` — area-weighted national series

| Column | Type | Meaning |
|---|---|---|
| `variable` | `dictionary<string>` | Store id (`spi_01`, `spi_03`, `spi_06`, `spi_12`, `spei_01`, `spei_03`, `spei_06`, `spei_12`, `sma`, `vci`). |
| `year` | `int16` | |
| `month` | `int8` | 1–12 |
| `value` | `float32` | District-area-weighted national value. |
| `n_districts` | `int16` | Districts contributing that month (sample size — always report it). |

Aggregation: equal-area (LAEA `+lat_0=22.5 +lon_0=79.5`), weights = district area. Rebuilding it is a
build-time job (`scripts/build_national.py`), not something to recompute per query.

### 3.3 `overlap_1981_2014.parquet` — era A ↔ era B pairs

| Column | Type | Meaning |
|---|---|---|
| `variable` | `dictionary<string>` | `spei_01`, `spei_12` (the shared definitions). |
| `district_id` | `dictionary<string>` | |
| `date` | `string` | `YYYY-MM` (a string here, unlike the `year`/`month` columns elsewhere). |
| `era_a_value`, `era_b_value` | `float` | Matched pair; both must be finite to appear. |
| `diff` | `float` | `era_b_value − era_a_value`. |
| `flag_a`, `flag_b` | `bool` | Drought flag at the published threshold. |
| `class_a`, `class_b` | `int8` | McKee class index from the shipped metadata table. |
| `event_match`, `class_match`, `class_near` | `bool` | Agreement at event / exact class / within one class. |

### 3.4 `per_district_1981_2014.parquet` — one row per district × variable

`n`, `n_window`, `coverage`, `r`, `bias`, `rmsd`, `sd_diff` (the X7 seam spread), `state_agree`,
`both_drought`, `severe_agree`, `class_exact`, `class_near`, `a_drought_share`, `b_drought_share`,
`a_mean`, `b_mean`. All `double` except `n` (`int32`) and `n_window` (`int16`).

### 3.5 `monthly_1981_2014.parquet` — area-weighted monthly agreement

`variable`, `date` (string), `n_districts`, `mean_a`, `mean_b`, `diff`, `state_agree`,
`both_drought`, `class_exact`, `class_near`.

---

## 4. Identifier vocabularies

| Kind | Values |
|---|---|
| Era B variables (`observed/`) | `spi_01`, `spi_03`, `spi_06`, `spi_12`, `spei_01`, `spei_03`, `spei_06`, `spei_12`, `sma`, `vci` |
| Era A variables (`atlas/`) | `spei_01`, `spei_04`, `spei_12` — the Atlas has **no** SPI and no SPEI-3/6 |
| Era C variables | `spi_01/03/06/12`, `spei_01/03/06/12` |
| Scenarios | `ssp245`, `ssp585` |
| Era C stats | `median`, `p25`, `p75`, `agreement_moderate`, `agreement_severe`, `n_models`, `dir_agreement_drier`, `dir_agreement_n`, `members` |
| Districts | 724 slugs; the UI registry (`data/boundaries/*.geojson` + `metadata.json`) is authoritative |

Era C statistics are **fractions of models**, not z-scores:

- `agreement_moderate` — share of available models with value ≤ −1.0 in that month.
- `agreement_severe` — same at ≤ −1.5.
- `n_models` — how many models contributed (the denominator; always report it).
- `dir_agreement_drier` — share of models whose change is drier (published only when step 07 emitted it).
- `dir_agreement_n` — denominator for the direction statistic.
- `members` — one partition per model (`model=<GCM>`), values in indicator units.

---

## 5. Missing data, precision and era rules

1. **Absent rows = missing.** Never fill, interpolate or carry forward. `count(*)` ≠ expected months
   means gaps; report both.
2. **`float32` rounding.** Store values are single precision (`−1.3100000023841858`). Cast
   `value::DOUBLE` in the **select list** when you need tidy numbers; never cast inside `WHERE`
   (it disables filter pushdown and can be slow over HTTP).
3. **Never splice eras.** A query that unions era A, B and C produces a scientifically invalid series.
   Present them side by side with their labels (see `#crossval` for the sanctioned comparison).
4. **Era C is not a forecast.** It is an ensemble of simulations; quote the agreement share and the
   model count alongside any number.
5. **Area weighting.** District-area weighting lives in `_national_monthly.parquet`; a plain
   `avg(value)` over districts is unweighted and will not match the dashboard's national figures.

---

## 6. Connecting

### DuckDB CLI / Python (local checkout)

```python
import duckdb
con = duckdb.connect()
con.sql("""
  SELECT district_id, count(*) AS n
  FROM read_parquet('data/parquet/observed/variable=*/part-0.parquet')
  GROUP BY 1 ORDER BY n DESC LIMIT 3
""").show()
```

A `*` glob works locally. To select one variable, name the directory:
`read_parquet('data/parquet/observed/variable=spi_03/part-0.parquet')`.

### Browser (Engine Lab)

Use absolute URLs and an explicit list. The simplest way to get the list is the catalog:

```js
const catalog = await (await fetch('/data/parquet/catalog.json')).json();
const files = catalog.variables
  .find(v => v.id === 'spi_03').files.observed;      // ["data/parquet/observed/…"]
const urls = files.map(p => new URL(p, location.origin).href);
const list = urls.map(u => `'${u}'`).join(', ');
// SELECT … FROM read_parquet([<list>])
```

Engine Lab's presets do exactly this; the **Catalog** panel shows the counts per variable.

### R

```r
library(duckdb)
con <- dbConnect(duckdb())
dbGetQuery(con, "
  SELECT year, month, value
  FROM read_parquet('data/parquet/observed/variable=spi_03/part-0.parquet')
  WHERE district_id = 'gujarat-ahmedabad' ORDER BY year, month
")
```

---

## 7. Recipe book

Each recipe is complete: run it as-is in Engine Lab (after pasting the file list) or in Python.
`OBS_SPI3` below stands for `read_parquet(['…/observed/variable=spi_03/part-0.parquet'])`.

### R1 · One district, full monthly series

```sql
SELECT year, month, round(value::DOUBLE, 2) AS spi3
FROM OBS_SPI3
WHERE district_id = 'gujarat-ahmedabad'
ORDER BY year, month;
```

### R2 · One month, every district (ranked)

```sql
SELECT district_id, round(value::DOUBLE, 2) AS spi3
FROM OBS_SPI3
WHERE year = 2002 AND month = 7
ORDER BY value;
```

### R3 · Annual mean with an honest sample size

```sql
SELECT year, round(avg(value)::DOUBLE, 3) AS mean_spi3, count(*) AS months_present
FROM OBS_SPI3
WHERE district_id = 'gujarat-ahmedabad'
GROUP BY year
HAVING count(*) >= 9          -- same rule as the dashboard's annual series
ORDER BY year;
```

### R4 · Drought months and their share of valid months

```sql
SELECT district_id,
       count(*)                              AS valid_months,
       count(*) FILTER (WHERE value <= -1.0) AS drought_months,
       round(100.0 * count(*) FILTER (WHERE value <= -1.0) / count(*), 1) AS pct
FROM OBS_SPI3
WHERE year BETWEEN 1981 AND 2025
GROUP BY district_id
ORDER BY pct DESC
LIMIT 20;
```

### R5 · National series (use the pre-aggregate, don't re-weight)

```sql
SELECT year, month, round(value::DOUBLE, 3) AS national, n_districts
FROM read_parquet(['…/_national_monthly.parquet'])
WHERE variable = 'spi_03'
ORDER BY year, month;
```

### R6 · Trend input: complete annual series for one district

```sql
SELECT year, avg(value)::DOUBLE AS annual
FROM OBS_SPI3
WHERE district_id = 'gujarat-ahmedabad' AND year BETWEEN 1981 AND 2025
GROUP BY year HAVING count(*) >= 9
ORDER BY year;
```

Feed that to Mann–Kendall + Sen (the dashboard does this in JavaScript; `scipy`/`pymannkendall`
or the R `trend` package give the same statistic).

### R7 · Event runs (≥ 3 consecutive dry months, gaps break runs)

```sql
WITH m AS (
  SELECT year, month, year::INT * 12 + month AS t, value::DOUBLE AS v
  FROM OBS_SPI3
  WHERE district_id = 'gujarat-ahmedabad'
),
g AS (
  SELECT *, t - row_number() OVER (PARTITION BY (v < -1.0) ORDER BY t) AS grp
  FROM m
)
SELECT min(year::INT * 100 + month) AS onset_ym,
       count(*)                AS duration_months,
       round(-sum(v + 1.0), 3) AS severity,
       round(min(v), 3)        AS worst_month
FROM g
WHERE v < -1.0
GROUP BY grp
HAVING count(*) >= 3
ORDER BY onset_ym;
```

Because `t` is derived from the calendar, a missing month changes the group key and therefore
**breaks the run** — the same rule the dashboard applies (missing months never extend an event).
Severity is Σ(τ − x) with τ = −1.0, hence `-sum(v + 1.0)`.

### R8 · Projection: median vs the 25–75 % band, 2041–2060

```sql
-- three reads over the same district set; run each stat separately in Engine Lab
SELECT district_id, round(avg(value)::DOUBLE, 3) AS median_mean
FROM read_parquet([ /* all stat=median/variable=spei_12/year=2041…2060 paths */ ])
WHERE year BETWEEN 2041 AND 2060
GROUP BY district_id ORDER BY median_mean LIMIT 10;
```

Replace `stat=median` with `stat=p25` / `stat=p75` and join on `district_id` for the band.

### R9 · Agreement over a window (always with its denominator)

```sql
WITH a AS (
  SELECT district_id, avg(value)::DOUBLE AS agreement
  FROM read_parquet([ /* stat=agreement_moderate/variable=spei_12, 2081–2100 */ ])
  WHERE year BETWEEN 2081 AND 2100
  GROUP BY district_id
),
n AS (
  SELECT district_id, min(value)::DOUBLE AS models
  FROM read_parquet([ /* stat=n_models/variable=spei_12, same years */ ])
  GROUP BY district_id
)
SELECT a.district_id, round(a.agreement, 3) AS agreement, n.models
FROM a JOIN n USING (district_id)
ORDER BY agreement DESC LIMIT 20;
```

### R10 · Atlas: class shares for one month

```sql
SELECT
  count(*)                                                  AS districts_with_data,
  count(*) FILTER (WHERE value <= -2.0)                     AS extreme,
  count(*) FILTER (WHERE value > -2.0 AND value <= -1.5)    AS severe,
  count(*) FILTER (WHERE value > -1.5 AND value <= -1.0)    AS moderate,
  round(100.0 * count(*) FILTER (WHERE value <= -1.0) / count(*), 1) AS pct_moderate_or_worse
FROM read_parquet(['…/atlas/variable=spei_12/year=2002/part-0.parquet'])
WHERE month = 9;
```

### R11 · Worst agreement districts (cross-validation)

```sql
SELECT district_id, n, round(r, 3) AS r, round(bias, 3) AS bias, round(sd_diff, 3) AS seam_sd
FROM read_parquet(['…/cross_validation/per_district_1981_2014.parquet'])
WHERE variable = 'spei_12'
ORDER BY bias            -- most negative first
LIMIT 15;
```

### R12 · Completeness audit (gaps without imputation)

```sql
WITH per AS (
  SELECT district_id, count(*) AS n
  FROM OBS_SPI3 GROUP BY district_id
)
SELECT district_id, n, 540 AS expected_months, 540 - n AS missing
FROM per
WHERE n < 540
ORDER BY missing DESC;
```

540 = 45 years × 12 months for 1981–2025. VCI is shorter by design (MODIS starts in 2000).

### R13 · Per-model spread (members) for one district-month

```sql
SELECT split_part(filename, 'model=', 2) AS model_part, value::DOUBLE AS v
FROM read_parquet([ /* stat=members/variable=spei_12/model=*/year=2050 paths */ ], filename = true)
WHERE district_id = 'gujarat-ahmedabad' AND month = 7
ORDER BY v;
```

Model names come from the path, not from a column — use `filename = true` (or `parse_filename`)
and split on `model=`.

### R14 · Introspect the catalog (what exists, without guessing)

```sql
SELECT variable, count(*) AS rows, min(year) AS first_year, max(year) AS last_year
FROM read_parquet('data/parquet/observed/variable=*/part-0.parquet', filename = true)
GROUP BY variable        -- requires hive partitioning (local paths)
ORDER BY variable;
```

In the browser, read `catalog.json` instead: `catalog.variables[]` has `id`, `label`, `unit`,
`eras`, and `files` nested `era → [paths]` (projections nest `scenario → stat → [paths]`, and
`members` further nests `model`).

---

## 8. Engine Lab specifics

- **Settings:** the worker sets `memory_limit`, `threads` and a modest `max_memory` defensively; a
  long query can still be stopped by reloading the tab. Prefer `LIMIT` while exploring.
- **Byte counter:** the status strip reports exact bytes and the number of HTTP requests for the last
  query; a repeat of the same query costs **0 bytes** (in-memory file cache).
- **Results:** the table shows the first 200 rows; **CSV exports all rows** and carries the citation,
  licence and generation header.
- **Errors** are shown verbatim (e.g. `Catalog Error: Table with name …`), not swallowed — useful for
  checking whether a store has been provisioned.
- **No uploads.** Everything happens in your browser; the only network traffic is the file ranges.

---

## 9. Gotchas that cost time

| Symptom | Cause | Fix |
|---|---|---|
| `HTTP Error 404` on an `atlas/` or `projections/` path | store not provisioned in this checkout | era A/C are published at release; check Documentation N |
| `IO Error: No files found` | glob over HTTP | pass an explicit list (catalog-driven) |
| Query returns far fewer rows than expected | a filter on a **dictionary** column compared to a non-string literal | compare with a quoted string, e.g. `district_id = 'gujarat-ahmedabad'` |
| National mean does not match the dashboard | unweighted `avg(value)` over districts | use `_national_monthly.parquet` |
| Trend differs from the dashboard | annual series without the ≥ 9-months rule, or a different period | filter `HAVING count(*) >= 9` and the same 1981–2025 window |
| Values end in `…00023841858` | `float32` storage | cast `::DOUBLE` in the select list |
| `date` comparisons fail in the cross-validation tables | `date` is a **string** there (`YYYY-MM`) | compare as `substr(date,1,4)::INT` or `date >= '2002-07'` |
| Event count higher than the UI | runs merged across gaps, or truncation ≠ −1.00 | derive `t` from the calendar (R7) and use the published truncation |
| `Out of Range Error: Overflow in multiplication of INT16` | `year` is `int16`; `year * 100` overflows at 1982 | cast first: `year::INT * 100 + month` |

---

## 10. Reproducibility and citation

Every file carries provenance metadata (`source_csv`/`source_sha256` for era B, `source_file` and
`stat_definition` for era C). When you publish a number derived from these files, state: the era,
the indicator and timescale, the window, the baseline (1981–2020), the sample size `n`, and the
methodology version (`research-gee-1.0.2` / pipeline 1.1.0). The citation block and licence
statements are in Documentation G and L, and every CSV/PNG export from the dashboard already
prefixes them.

*This guide is versioned with the dashboard: `docs/sql-guide.md` at the released commit.*
