/* ---------------------------------------------------------------------------
 * DIE v2.0 — Drought to 2100 (#summary, task M9 / feature E19; Owner request
 * 2026-11-18: "how drought changes from now to 2100").
 *
 * The headline surface: per district, drought FREQUENCY / DURATION /
 * SEVERITY in the validated era-C ensemble over a future window (near /
 * mid / late) compared against the ERA-B GRIDDED MULTI-SOURCE PRODUCT
 * 1981–2014 baseline (register D6 — era B is NOT labelled "observed",
 * decision D8: CHIRPS/ERA5-Land/MODIS are observation-based gridded
 * sources, never merged) built by scripts/build_events_baseline.py from
 * the committed era-B store.
 *
 * Every number is computed from published, validated products only (R3):
 *   - era C: the committed Parquet store via the DuckDB engine
 *     (ensemble median series; scenario + window + indicator selectable);
 *   - baseline: data/events/baseline_1981_2014.json (frozen v1.0 runs
 *     analysis over era B, 34 years);
 *   - agreement: the published dir_agreement_drier / dir_agreement_n
 *     window-constant partitions (effective window 2081–2100, base
 *     1981–2014 — recorded verbatim in metadata.json → era_c.dir_agreement).
 *   - areas/state membership: the shared registry (LAEA km², v1.0 rule).
 *
 * Honesty rules honoured here:
 *  - Projections are simulations, never forecasts (R2); the two eras are
 *    never spliced — this surface is a DELTA map, computed per era
 *    separately, never one continuous series.
 *  - Event statistics are MEDIAN-based and labelled as such (X2/X3): the
 *    agreement map shows how many of the honest 8 subset models actually
 *    dry, so the median is never read alone.
 *  - Sample sizes reported everywhere (R10); missing districts rendered
 *    grey, never imputed (R10). The 6 island districts absent from the
 *    IMD-anchored era-C reference stay absent (documented ocean mask).
 *  - Per-district seam uncertainty (X7) arrives with M6.6/M6.8 and is
 *    explicitly marked pending in the caveat block — never fabricated.
 * ------------------------------------------------------------------------- */
(function () {
  "use strict";

  const DIE = (window.DIE = window.DIE || {});
  const $ = (id) => document.getElementById(id);

  const Sum = { ready: false };

  /* ---- module state ---------------------------------------------------- */
  const state = {
    scenario: "ssp245",
    variable: "spi_03",
    window: "late",          // the headline question is "to 2100"
    metric: "agreement",     // X2: agreement-first — the median never leads
  };

  const WINDOWS = {
    near: { from: 2026, to: 2040 },
    mid: { from: 2041, to: 2060 },
    late: { from: 2081, to: 2100 },
  };
  const WINDOW_LABEL = {
    near: "Near term (2026–2040)",
    mid: "Mid century (2041–2060)",
    late: "Late century (2081–2100)",
  };
  const SCENARIO_LABEL = { ssp245: "SSP2-4.5", ssp585: "SSP5-8.5" };
  // truncation thresholds — frozen v1.0 events machinery (era C publishes
  // the SPI/SPEI families only; the baseline JSON matches them)
  const THRESHOLD = -1.0;
  const MIN_DURATION = 3;
  const BASELINE_WINDOW = [1981, 2014];
  const BASELINE_YEARS = BASELINE_WINDOW[1] - BASELINE_WINDOW[0] + 1;

  let catalog = null;
  let baselineEvents = null;   // parsed baseline JSON (cached)
  let mapApi = null;           // primary choropleth (lazy)
  let rowsCache = null;        // current computed per-district rows
  let seq = 0;                 // stale-render guard

  /* ---- shared palette (mirrors projections.js so both era-C surfaces
   * read identically) ---------------------------------------------------- */
  const DIR_COLORS = ["#F7F3EC", "#E3D2BA", "#C9A97F", "#A57344", "#6E4523"];
  const DIR_BINS = [
    { test: (f) => f <= 0, label: "0 % of models drier", range: "0" },
    { test: (f) => f <= 0.25, label: "1–25 % of models drier", range: "(0, 0.25]" },
    { test: (f) => f <= 0.5, label: "26–50 % of models drier", range: "(0.25, 0.5]" },
    { test: (f) => f <= 0.75, label: "51–75 % of models drier", range: "(0.5, 0.75]" },
    { test: () => true, label: "76–100 % of models drier", range: "> 0.75" },
  ];
  const CHANGE_COLORS = ["#2F5F9E", "#9DB8D4", "#E9EDF2", "#C9955C", "#7A3E14"];
  // symmetric bins around "no meaningful change"; bounds per metric
  const CHANGE_BINS = {
    frequency: [ -5, -2, 2, 5 ],     // percentage points of drought months
    duration:  [ -1, -0.25, 0.25, 1 ], // months of mean event duration
    severity:  [ -0.5, -0.15, 0.15, 0.5 ], // z-units of mean severity/event
  };
  const CHANGE_LEGEND = {
    frequency: {
      head: "Change in drought-month share vs 1981–2014 (percentage points; ensemble median)",
      labels: ["≤ −5 pp (much fewer drought months)", "−5 to −2 pp", "−2 to +2 pp (little change)", "+2 to +5 pp", "> +5 pp (many more drought months)"],
    },
    duration: {
      head: "Change in mean event duration vs 1981–2014 (months; ensemble median)",
      labels: ["≤ −1 month", "−1 to −0.25", "−0.25 to +0.25 (little change)", "+0.25 to +1", "> +1 month"],
    },
    severity: {
      head: "Change in mean severity per event vs 1981–2014 (z-units; ensemble median)",
      labels: ["≤ −0.5 z", "−0.5 to −0.15 z", "−0.15 to +0.15 z (little change)", "+0.15 to +0.5 z", "> +0.5 z"],
    },
  };
  /* ---- helpers ---------------------------------------------------------- */
  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }
  function fmt(v, dp) {
    return Number.isFinite(v) ? v.toFixed(dp) : "—";
  }
  function track(control, value) {
    if (DIE.Telemetry) {
      try { DIE.Telemetry.track("sum_control", { control, value }); } catch (e) {}
    }
  }
  function getCatalog() {
    if (DIE.Engine && DIE.Engine.ensureCatalog) return DIE.Engine.ensureCatalog();
    return fetch("data/parquet/catalog.json", { cache: "no-store" })
      .then((r) => { if (!r.ok) throw new Error("catalog HTTP " + r.status); return r.json(); });
  }
  function fetchJSON(url) {
    return fetch(url, { cache: "no-store" }).then((r) => {
      if (!r.ok) throw new Error(url + " HTTP " + r.status);
      return r.json();
    });
  }
  function eraC() {
    return catalog && catalog.eras && catalog.eras.projections;
  }
  function dirMidYear() {
    // dir_agreement partitions exist only inside the EFFECTIVE window (they
    // are window-constant), so read them at the effective window's midpoint
    // and label the window verbatim — regardless of the selected future
    // window. Effective window comes from metadata.json (pipeline-recorded).
    const eff = dirEffectiveWindow();          // e.g. "2081-2100"
    const m = /^(\d{4})-(\d{4})$/.exec(eff);
    if (m) return Math.round((+m[1] + +m[2]) / 2);
    return 2090;                               // record 2015–2100: configured 2081–2100
  }
  function dirEffectiveWindow() {
    // recorded verbatim by the pipeline in metadata.json → era_c.dir_agreement
    const da = DIE.meta && DIE.meta.era_c && DIE.meta.era_c.dir_agreement;
    return (da && da.window_effective) || "2081-2100";
  }

  /* ---- controls ---------------------------------------------------------- */
  function renderVariableOptions() {
    const sel = $("sumVariable");
    const avail = (catalog.variables || []).filter(
      (v) => v.files && v.files.projections &&
        Object.keys(v.files.projections).length > 0);
    sel.innerHTML = avail.map((v) =>
      '<option value="' + esc(v.id) + '">' + esc(v.label || v.id) + "</option>"
    ).join("");
    if (!avail.some((v) => v.id === state.variable) && avail.length) {
      state.variable = avail[0].id;
    }
    sel.value = state.variable;
  }

  function wire() {
    for (const radio of document.querySelectorAll('input[name="sumScenario"]')) {
      radio.addEventListener("change", () => {
        state.scenario = radio.value;
        track("scenario", radio.value);
        renderAll();
      });
    }
    $("sumVariable").addEventListener("change", (e) => {
      state.variable = e.target.value;
      track("variable", state.variable);
      renderAll();
    });
    $("sumWindow").addEventListener("change", (e) => {
      state.window = e.target.value;
      track("window", state.window);
      renderAll();
    });
    $("sumMetric").addEventListener("change", (e) => {
      state.metric = e.target.value;
      track("metric", state.metric);
      renderAll();
    });
    $("sumCsvBtn").addEventListener("click", exportCsv);
  }

  function renderBanner() {
    const el = $("sumBanner");
    const ec = eraC();
    const da = DIE.meta && DIE.meta.era_c && DIE.meta.era_c.dir_agreement;
    el.innerHTML =
      "<b>Drought change, honestly framed.</b> Future values are " +
      "<b>simulations, not forecasts</b> (era C: QDM-bias-corrected CMIP6, " +
      "8-model committed subset" + (ec && ec.label ? " — " + esc(ec.label) : "") +
      "). The comparison baseline is the <b>era-B Gridded Multi-Source " +
      "Product 1981–2014 record</b> (34 years; register D6). The two eras are " +
      "<b>never spliced</b> — " +
      "each side is computed separately and only their difference is shown. " +
      "Every map pairs the median-based change with the " +
      "<b>share of models agreeing on drying</b> (never the median alone, X2" +
      (da && da.window_effective ? "; agreement window " + esc(da.window_effective) +
        ", base " + esc(da.base || "1981-2014") : "") + ").";
  }

  /* ---- core computation -------------------------------------------------- */
  /* Per district: frozen v1.0 runs analysis on the era-C ensemble-median
   * series (window), the same metrics recomputed from the baseline JSON
   * (1981–2014), and their difference. Missing months break runs (R10). */

  function eventMetrics(values, nYears) {
    const events = DIE.Analytics.findEvents(
      values, values.map((_, i) => String(i)), THRESHOLD, MIN_DURATION);
    const n = events.length;
    const droughtMonths = values.filter((v) => Number.isFinite(v) && v <= THRESHOLD).length;
    const validMonths = values.filter(Number.isFinite).length;
    const totalSeverity = events.reduce((s, e) => s + e.severity, 0);
    return {
      nEvents: n,
      droughtMonths,
      validMonths,
      share: validMonths ? droughtMonths / validMonths : null,
      meanDuration: n ? events.reduce((s, e) => s + e.duration, 0) / n : null,
      meanSeverity: n ? totalSeverity / n : null,
      eventsPerYear: nYears ? n / nYears : null,
      nCensored: events.filter((e) =>
        e.startIdx === 0 || e.endIdx === values.length - 1).length,
    };
  }

  function baselineMetrics(id) {
    const bv = baselineEvents && baselineEvents.variables &&
      baselineEvents.variables[state.variable];
    const b = bv && bv.districts && bv.districts[id];
    if (!b || !b.valid_months) return null;
    return {
      share: b.drought_months / b.valid_months,
      meanDuration: b.mean_duration,
      meanSeverity: b.n_events ? b.total_severity / b.n_events : null,
      eventsPerYear: b.events_per_year,
      validMonths: b.valid_months,
      nEvents: b.n_events,
    };
  }

  async function ensureBaseline() {
    if (baselineEvents) return baselineEvents;
    baselineEvents = await fetchJSON("data/events/baseline_1981_2014.json");
    return baselineEvents;
  }

  async function renderAll() {
    const mySeq = ++seq;
    const ec = eraC();
    if (!ec || !ec.available || !DIE.Engine || !DIE.registry) return;
    const w = WINDOWS[state.window];
    const nYears = w.to - w.from + 1;
    const note = $("sumNationalNote");
    $("sumMapMeta").textContent = "computing…";
    note.textContent = "querying the era-C store…";
    try {
      const [medianRows, dirRows, dirNRows, baseline] = await Promise.all([
        DIE.Engine.ensemble({
          scenario: state.scenario, variable: state.variable,
          stat: "median", yearRange: [w.from, w.to],
        }),
        DIE.Engine.ensemble({
          scenario: state.scenario, variable: state.variable,
          stat: "dir_agreement_drier", yearRange: [dirMidYear(), dirMidYear()],
        }),
        DIE.Engine.ensemble({
          scenario: state.scenario, variable: state.variable,
          stat: "dir_agreement_n", yearRange: [dirMidYear(), dirMidYear()],
        }),
        ensureBaseline(),
      ]);
      if (mySeq !== seq) return;   // a newer selection superseded this render

      // group the median rows per district (absent rows = missing months)
      const byDistrict = new Map();
      for (const r of medianRows) {
        let list = byDistrict.get(r.district_id);
        if (!list) byDistrict.set(r.district_id, (list = []));
        list.push(r);
      }
      const dirMap = new Map();
      for (const r of dirRows) {
        if (Number.isFinite(r.value)) dirMap.set(r.district_id, r.value);
      }
      const dirNMap = new Map();
      for (const r of dirNRows) {
        if (Number.isFinite(r.value) && r.value >= 0) {
          dirNMap.set(r.district_id, r.value);
        }
      }

      const rows = [];
      for (const [id, list] of byDistrict) {
        list.sort((a, b) => a.year - b.year || a.month - b.month);
        const values = list.map((r) => (Number.isFinite(r.value) ? r.value : NaN));
        const met = eventMetrics(values, nYears);
        if (!met.validMonths) continue;
        const base = baselineMetrics(id);
        if (!base) continue;      // baseline-missing districts can't produce a DELTA
        const reg = DIE.registry.districts.get(id) || {};
        rows.push({
          id,
          name: reg.name || id,
          stateName: reg.state || "—",
          stateId: reg.state_id || (reg.state || "").toLowerCase().replace(/[^a-z0-9]+/g, "-"),
          area: Number.isFinite(reg.area) ? reg.area : null,
          met, base,
          dir: Number.isFinite(dirMap.get(id)) ? dirMap.get(id) : null,
          dirN: Number.isFinite(dirNMap.get(id)) ? dirNMap.get(id) : null,
          dShare: (met.share - base.share) * 100,                    // pp
          dDur: met.meanDuration !== null && base.meanDuration !== null
            ? met.meanDuration - base.meanDuration : null,           // months
          dSev: met.meanSeverity !== null && base.meanSeverity !== null
            ? met.meanSeverity - base.meanSeverity : null,           // z
        });
      }
      rowsCache = rows;

      renderMap(rows, nYears, mySeq);
      renderNational(rows);
      renderStateTable(rows);
    } catch (err) {
      console.warn("[summary] render failed:", err);
      $("sumMapMeta").textContent = "unavailable";
      note.textContent = "Change layer unavailable: " +
        String(err && err.message || err);
    }
  }

  /* ---- primary map (M9.1 + M9.2 in one map, X2 agreement-first) -----------
   * DEFAULT statistic = share of subset models drier (dir_agreement_drier,
   * window-constant). The median-based change metrics are one click away and
   * always labelled "median-based"; they never lead because the ensemble
   * median concentrates (a documented property of a median-of-subset
   * standardised series) and would read as "drought disappears". */
  function changeColor(row) {
    if (state.metric === "agreement") {
      if (row.dir === null) return null;
      const f = Math.min(1, Math.max(0, row.dir));
      return DIR_COLORS[DIR_BINS.findIndex((b) => b.test(f))];
    }
    const v = state.metric === "frequency" ? row.dShare
      : state.metric === "duration" ? row.dDur : row.dSev;
    if (!Number.isFinite(v)) return null;
    const b = CHANGE_BINS[state.metric];
    if (v <= b[0]) return CHANGE_COLORS[0];
    if (v <= b[1]) return CHANGE_COLORS[1];
    if (v < b[2]) return CHANGE_COLORS[2];
    if (v <= b[3]) return CHANGE_COLORS[3];
    return CHANGE_COLORS[4];
  }
  function changeValue(row) {
    if (state.metric === "agreement") return row.dir;
    return state.metric === "frequency" ? row.dShare
      : state.metric === "duration" ? row.dDur : row.dSev;
  }

  function renderMap(rows, nYears, mySeq) {
    const meta = $("sumMapMeta"), noteEl = $("sumMapNote");
    try {
      if (!mapApi) {
        mapApi = DIE.MapView.createChoropleth($("sumMap"), { tooltip: false });
      }
      const byId = new Map(rows.map((r) => [r.id, r]));
      mapApi.applyData(null, 0, null, null,
        () => null,
        (id) => {
          const r = byId.get(id);
          return r ? (changeColor(r) || "#D7DEE7") : "#D7DEE7";
        });
      if (mySeq !== seq) return;
      const indLabel = DIE.indicatorById && DIE.indicatorById.get(state.variable)
        ? DIE.indicatorById.get(state.variable).label : state.variable;
      meta.textContent = SCENARIO_LABEL[state.scenario] + " · " + indLabel +
        " · " + WINDOW_LABEL[state.window];
      const n = rows.length;
      let noteText = "";
      if (state.metric === "agreement") {
        const withDir = rows.filter((r) => r.dir !== null);
        const strong = withDir.filter((r) => r.dir > 0.75).length;
        const some = withDir.filter((r) => r.dir > 0.5).length;
        const nMax = withDir.reduce((m, r) => Math.max(m, r.dirN || 0), 0) || 8;
        renderLegend($("sumLegend"), {
          head: "Share of the " + nMax + "-model committed subset whose " +
            dirEffectiveWindow() + " mean is drier than their own 1981–2014 base",
          labels: DIR_BINS.map((b) => b.label),
        }, DIR_COLORS);
        noteText =
          "Agreement on drying (direction of change), " + n + " districts: " +
          strong + " district(s) have MORE THAN 75 % of the subset drier and " +
          some + " have a majority drier in " + dirEffectiveWindow() +
          ". Denominator = exact per-district model count; a count of models, " +
          "never a probability (R9); base = the GCM-native 1981–2014 window " +
          "(register D6). Switch the map statistic to the median-based " +
          "change metrics to see the ensemble-median deltas behind this.";
      } else {
        const wetter = rows.filter((r) => {
          const v = changeValue(r);
          return Number.isFinite(v) && v <= CHANGE_BINS[state.metric][1];
        }).length;
        const drier = rows.filter((r) => {
          const v = changeValue(r);
          return Number.isFinite(v) && v > CHANGE_BINS[state.metric][3];
        }).length;
        renderLegend($("sumLegend"), CHANGE_LEGEND[state.metric], CHANGE_COLORS);
        noteText =
          "MEDIAN-BASED change (era-C ensemble median over " + nYears +
          " years vs the era-B 1981–2014 baseline, 34 years): " + n +
          " districts with comparable data · " + drier +
          " much drier, " + wetter + " much wetter (outer bins). " +
          "Read with care: the ensemble median CONCENTRATES (a documented " +
          "property of a median-of-subset standardised series), so its " +
          "drought-month share is lower than any single model's — the " +
          "agreement statistic (default view) is the models' own verdict. " +
          "Frozen v1.0 runs analysis, τ = −1.0, min 3 months, censoring " +
          "flagged; missing districts grey, never imputed (R10).";
      }
      noteEl.textContent = noteText;
    } catch (err) {
      console.warn("[summary] map failed:", err);
      noteEl.textContent = "Map unavailable: " + String(err && err.message || err);
    }
  }

  function renderLegend(el, legend, colors) {
    el.innerHTML =
      '<span class="legend-head">' + esc(legend.head) + "</span>" +
      legend.labels.map((lab, i) =>
        '<span class="legend-row"><span style="display:inline-block;' +
        "width:12px;height:12px;border-radius:2px;background:" + colors[i] +
        '"></span><span class="legend-range">' + esc(lab) + "</span></span>"
      ).join("");
  }

  /* ---- national figures (M9.3, area-weighted, LAEA areas) ----------------- */
  function renderNational(rows) {
    const note = $("sumNationalNote");
    let aC = 0, aB = 0, area = 0;
    for (const r of rows) {
      if (!Number.isFinite(r.area)) continue;
      area += r.area;
      aC += r.area * r.met.share;
      aB += r.area * r.base.share;
    }
    if (!area) {
      note.textContent = "No area-weighted figures available for this selection.";
      return;
    }
    const shareC = aC / area * 100, shareB = aB / area * 100;
    const dirArea = rows.filter((r) => r.dir !== null && Number.isFinite(r.area));
    const dirW = dirArea.reduce((s, r) => s + r.area * r.dir, 0) /
      dirArea.reduce((s, r) => s + r.area, 0);
    note.innerHTML =
      "<b>National (area-weighted, LAEA):</b> share of months in moderate-or-" +
      "worse drought — era-B 1981–2014 baseline <b>" + shareB.toFixed(1) +
      "%</b> → " + WINDOW_LABEL[state.window].toLowerCase() + " ensemble median <b>" +
      shareC.toFixed(1) + "%</b> (change " + (shareC - shareB >= 0 ? "+" : "") +
      (shareC - shareB).toFixed(1) + " pp). Area-weighted share of the " +
      "8-model subset drier than base: <b>" + (dirW * 100).toFixed(0) +
      "%</b>. n = " + rows.length + " districts, " +
      area.toFixed(0) + " km² of comparable area.";
  }

  /* ---- per-state table (M9.3) --------------------------------------------- */
  function renderStateTable(rows) {
    const meta = $("sumStateMeta"), noteEl = $("sumStateNote");
    const tbody = $("sumStateTable").querySelector("tbody");
    meta.textContent = SCENARIO_LABEL[state.scenario] + " · " +
      WINDOW_LABEL[state.window] + " · area-weighted";
    // group by state (registry name); area-weight where area is known
    const groups = new Map();
    for (const r of rows) {
      let g = groups.get(r.stateName);
      if (!g) groups.set(r.stateName, (g = []));
      g.push(r);
    }
    const srows = [];
    for (const [stateName, list] of groups) {
      const withArea = list.filter((r) => Number.isFinite(r.area));
      const w = (fn) => {
        const wa = withArea.reduce((s, r) => s + r.area, 0);
        return wa ? withArea.reduce((s, r) => s + r.area * fn(r), 0) / wa : null;
      };
      const dirW = w((r) => (r.dir !== null ? r.dir : 0));
      const dirKnown = list.filter((r) => r.dir !== null).length;
      srows.push({
        stateName,
        n: list.length,
        baseShare: w((r) => r.base.share) * 100,
        futShare: w((r) => r.met.share) * 100,
        change: w((r) => r.dShare / 100) * 100,
        dirW, dirKnown,
        withArea: withArea.length,
      });
    }
    srows.sort((a, b) => (b.change || -99) - (a.change || -99));
    tbody.innerHTML = srows.map((s) => {
      const chg = Number.isFinite(s.change) ? s.change : null;
      return "<tr>" +
        "<td>" + esc(s.stateName) + "</td>" +
        '<td class="num">' + s.n + "</td>" +
        '<td class="num">' + fmt(s.baseShare, 1) + "%</td>" +
        '<td class="num">' + fmt(s.futShare, 1) + "%</td>" +
        '<td class="num">' + (chg === null ? "—" :
          (chg >= 0 ? "+" : "") + chg.toFixed(1) + " pp") + "</td>" +
        '<td class="num">' + (s.dirW === null ? "—" :
          (s.dirW * 8).toFixed(1) + " / 8") + "</td>" +
        "</tr>";
    }).join("");
    const areaSum = rows.reduce((s, r) => s + (Number.isFinite(r.area) ? r.area : 0), 0);
    noteEl.textContent =
      "Area-weighted with the v1.0 LAEA district areas; drought-month share " +
      "is months ≤ −1.0 z over valid months (era C: " + WINDOW_LABEL[state.window] +
      "median series; baseline: era B 1981–2014). Rows with no area fall " +
      "back to unweighted means of the same districts. Agreement column = " +
      "area-weighted share × 8 (models drier than their 1981–2014 base, " +
      "window " + dirEffectiveWindow() + "). National comparable area " +
      areaSum.toFixed(0) + " km² across " + rows.length + " districts (of 724; " +
      "island districts absent from the era-C reference stay absent, R10).";
  }

  /* ---- CSV export (X6 reproducibility headers) ---------------------------- */
  function exportCsv() {
    if (!rowsCache || !rowsCache.length) {
      DIE.App && DIE.App.toast("Nothing to export",
        "Compute the change layer first (the map must have rendered).");
      return;
    }
    const w = WINDOWS[state.window];
    const ind = DIE.indicatorById && DIE.indicatorById.get(state.variable);
    const L = [];
    L.push("# DIE v2.0 #summary — drought change vs observed baseline");
    L.push("# generated: " + new Date().toISOString());
    L.push("# scenario: " + state.scenario + " (" + SCENARIO_LABEL[state.scenario] + ")");
    L.push("# indicator: " + state.variable + (ind ? " (" + ind.label + ")" : ""));
    L.push("# future window: " + w.from + "-" + w.to + " (era C ensemble median series)");
    L.push("# baseline: era B Gridded Multi-Source Product 1981-2014 (data/events/baseline_1981_2014.json, register D6)");
    L.push("# event machinery: frozen v1.0 runs analysis, threshold -1.0 z, min duration 3 months, censoring flagged");
    L.push("# dir_agreement: fraction of the 8-model subset drier than their own 1981-2014 base; effective window " + dirEffectiveWindow());
    L.push("# areas: LAEA km2 (v1.0 registry); missing values are empty cells, never imputed (R10)");
    L.push("district_id,district_name,state,area_km2," +
      "baseline_drought_share,future_drought_share,change_pp," +
      "baseline_mean_duration_mo,future_mean_duration_mo,duration_change_mo," +
      "baseline_mean_severity_z,future_mean_severity_z,severity_change_z," +
      "baseline_events_per_year,future_events_per_year," +
      "dir_agreement_drier,dir_agreement_n," +
      "future_valid_months,baseline_valid_months");
    for (const r of rowsCache) {
      const cell = (v, dp) => (Number.isFinite(v) ? v.toFixed(dp) : "");
      L.push([
        r.id, '"' + String(r.name).replace(/"/g, '""') + '"',
        '"' + String(r.stateName).replace(/"/g, '""') + '"',
        Number.isFinite(r.area) ? r.area.toFixed(2) : "",
        cell(r.base.share * 100, 3), cell(r.met.share * 100, 3), cell(r.dShare, 3),
        cell(r.base.meanDuration, 3), cell(r.met.meanDuration, 3), cell(r.dDur, 3),
        cell(r.base.meanSeverity, 4), cell(r.met.meanSeverity, 4), cell(r.dSev, 4),
        cell(r.base.eventsPerYear, 4), cell(r.met.eventsPerYear, 4),
        cell(r.dir, 3), r.dirN !== null && r.dirN !== undefined ? r.dirN : "",
        r.met.validMonths, r.base.validMonths,
      ].join(","));
    }
    const blob = new Blob([L.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "die-summary_" + state.scenario + "_" + state.variable +
      "_" + w.from + "-" + w.to + "_vs_1981-2014.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    if (DIE.Telemetry) {
      try { DIE.Telemetry.track("sum_export", { scenario: state.scenario }); } catch (e) {}
    }
  }

  /* ---- init / render ------------------------------------------------------ */
  async function init() {
    if (!Sum.ready) {
      wire();
      Sum.ready = true;
    }
    if (!catalog) {
      try {
        catalog = await getCatalog();
      } catch (err) {
        console.warn("[summary] catalog load failed:", err);
        $("sumBanner").textContent =
          "Data contract unavailable — this workspace shows committed " +
          "catalog facts only (no synthetic placeholders, R3). Error: " +
          String(err && err.message || err);
        return;
      }
    }
    if (!eraC() || !eraC().available) {
      $("sumBanner").textContent =
        "The projections era has no validated products yet; this workspace " +
        "renders nothing rather than a placeholder (R3).";
      return;
    }
    renderBanner();
    renderVariableOptions();
    await renderAll();
  }

  function invalidate() {
    // container re-layout (tab switch / resize): Leaflet re-query is near-free
    if (mapApi) mapApi.invalidateSize();
  }

  DIE.Summary = { init, invalidate };
})();
