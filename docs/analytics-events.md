# Analytics event schema — Drought Intelligence Explorer

This document describes the deep application-event instrumentation shipped in
`assets/js/telemetry.js`. Every event is pushed onto `window.dataLayer`
(GTM container `GTM-MDF5QQ4D`) with a **value weight** that estimates how
strongly the action signals willingness to pay for a professional/research
tier (bulk exports, API access, custom regions, operational feeds).

No backend, no cookies, no PII: only interaction metadata (public region
names, indicator ids, filenames) leaves the browser.

---

## 1. How to read it in GTM / GA4

1. **Triggers** — create a *Custom Event* trigger with the event name
   `die_.*` (regex) to catch every application event, or match individual
   names (`die_export_data`, `die_user_tier`, …).
2. **Data layer variables** — register the keys you need as Data Layer
   Variables: `value`, `engagement_tier`, `session_value`, `session_id`,
   `die_tab`, `die_indicator`, `die_region`, plus the per-event params in
   the table below.
3. **GA4** — if the container forwards to GA4, `value` is a
   GA4-standard parameter and works with conversion values out of the box;
   mark `die_export_data` as a key event to value conversions.
4. **Debug** — open the console and inspect `DIE.Telemetry.log` (ring
   buffer of the last 120 events) or `DIE.Telemetry.state()` (live session
   value, exports, tiers).

## 2. Value model & paid-intent tiers

Weights accumulate per session (`session_value`). Crossing a threshold
emits **`die_user_tier`** once, so you can build GTM/GA4 audiences:

| Tier           | Threshold | Meaning                                                        |
| -------------- | --------: | -------------------------------------------------------------- |
| `browsing`     |       ≥ 1 | Casual map browsing                                            |
| `explorer`     |      ≥ 12 | Repeated analysis: date scrubbing, indicator swaps             |
| `high_intent`  |      ≥ 40 | Event deep-dives, propagation pairs, table searches            |
| `research_pro` |     ≥ 100 | Multiple data exports — the profile most likely to pay         |

Highest-weight signals: **data exports (25)**, chart exports (10), event
deep-dives (8), propagation/comparison experiments (6).

## 3. Event reference

Common fields on every event: `event` (name below, prefixed `die_`),
`value`, `engagement_tier`, `session_value`, `session_id`, `die_tab`,
`die_indicator`, `die_region`.

| Event name (`die_…`) | Params | Value | Fired when |
| --- | --- | ---: | --- |
| `die_session_start` | — | 0 | page load (Telemetry wire) |
| `die_tab_view` | `tab` | 1 overview · 3 historical/events · 4 propagation · 2 data | workspace switch (incl. hash routing) |
| `die_filter_change` | `keys`, `extent`, `state_id`, `district_id`, `period`, `season` | 1 | geography/period state change |
| `die_indicator_change` | `indicator` | 4 | drought indicator swap |
| `die_date_change` | `date` (YYYY-MM) | 1 | committed observation-date change (slider drag → one event) |
| `die_district_focus` | `district`, `state`, `source: map_click` | 4 | district clicked on the main map |
| `die_animation_play` | `action` (play/pause), `speed_ms` | 3 | evolution animation play/pause |
| `die_table_sort` | `table` (comparison/events), `key` | 1 | sortable table header |
| `die_table_search` | `table` | 2 | debounced search (one per typing burst) |
| `die_table_page` | `table`, `page` | 1 | pagination click |
| `die_table_level` | `level` (state/district) | 1 | comparison table level changed |
| `die_event_detail_open` | `district`, `state`, `duration_months`, `severity`, `censored` | 8 | event row opened in the detail view |
| `die_propagation_pair` | `a`, `b` | 6 | cross-correlation indicator pair changed |
| `die_comparison_change` | `a`, `b`, `view` | 6 | single-date comparison module changed |
| `die_export_data` | `file_name`, `file_type` (csv/json/png/markdown) | 25 | any download funnelled through `downloadBlob` (all CSV/JSON/MD exports, map PNG) |
| `die_chart_export` | `tool` | 10 | Plotly modebar export |
| `die_docs_open` | `section` | 2 | any "how to read this" / guide jump |
| `die_validate_all` | — | 2 | full data-quality audit |
| `die_outbound_link` | `destination` | 1 | external link (author site) |
| `die_drawer_toggle` | `open` | 0 | mobile drawer opened/closed |
| `die_panel_toggle` | `control: sidebar`, `collapsed` | 0 | desktop sidebar collapse/expand |
| `die_fullscreen` | `entering` | 0 | fullscreen toggle |
| `die_reset_filters` | — | 0 | "Reset filters" |
| `die_session_summary` | `seconds`, `tabs_visited`, `exports`, `event_count` | 0 | session ends (visibility hidden / pagehide, ≥ 60 s apart) |

## 4. Suggested GTM audience recipes

- **Paywall-eligible** — trigger `die_user_tier` where `tier` = `high_intent`
  or `research_pro`; the strongest single audience for a paid tier.
- **Export abandoners** — `die_explorer` tier reached but no
  `die_export_data`: these users analyse but have not discovered exports
  (target for onboarding, not a paywall).
- **Research workflows** — sequence: `die_indicator_change` →
  `die_propagation_pair` → `die_export_data` signals methodology-sensitive
  users who would pay for bulk/API access.

## 5. Implementation notes

- Transport is `window.dataLayer.push` only — works with the GTM
  container snippet in `<head>` and never blocks rendering.
- `telemetry.js` loads in the same non-blocking module batch as the other
  application modules and wires itself in `app.js` init (`DIE.Telemetry.wire()`).
- Transient slider drags are filtered (only committed changes emit
  `die_date_change`); table searches are debounced (1.5 s).
- Telemetry calls are wrapped in `try/catch` everywhere — a blocked
  dataLayer can never break the application.
