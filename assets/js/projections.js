/* ---------------------------------------------------------------------------
 * DIE v2.0 - Future Projections (#projections, task M5.2; docs/v2/04 section 4.2)
 *
 * Era C surface. This M5.2 SKELETON wires the selection controls against the
 * COMMITTED catalog (data/parquet/catalog.json) and shows the projection
 * banner, store status and era seam notes. Charts, choropleths and the
 * agreement layer land in M5.3-M5.8; nothing here renders synthetic data
 * (R3) and nothing is presented as a forecast (R2).
 *
 * Honesty rules honoured here:
 *  - The statistic selector defaults to agreement (X2: agreement-first),
 *    with the exact thresholds (<= -1.0 moderate, <= -1.5 severe).
 *  - The ensemble n is shown verbatim from metadata (X3), never "24 models".
 *  - Unsupported combinations are DISABLED WITH AN EXPLANATION, never
 *    silently broken (section 7): the late-century window is enabled only
 *    when the committed catalog actually covers at least 10 years of
 *    2081-2100 (window bounds are derived from the catalog, never hard-coded
 *    to a particular download state).
 *  - The selection check reads only the committed catalog — it never
 *    guesses that files exist.
 * ------------------------------------------------------------------------- */
(function () {
  "use strict";

  const DIE = (window.DIE = window.DIE || {});
  const $ = (id) => document.getElementById(id);

  const Proj = { ready: false };

  /* ---- module state ---------------------------------------------------- */
  const state = {
    scenario: "ssp245",
    variable: "spi_03",
    statistic: "agreement_moderate",   // X2: agreement-first from day one
    window: "near",
    customFrom: 2026,
    customTo: 2040,
    geography: "national",
    district: "gujarat-ahmedabad",     // known-good store id (M1.6 gate)
    stateSid: "gujarat",
    mapYear: 2040,
    mapMonth: 7,
    divYear: 2040,
    divMonth: 7,
  };

  const WINDOWS = {
    near: { from: 2026, to: 2040 },
    mid: { from: 2041, to: 2060 },     // coverage depends on the published record
    late: { from: 2081, to: 2100 },    // enabled from the catalog once covered
  };

  // statistic -> era C partition groups in the published store
  // (scenario=<s>/stat=<st>/variable=<v>/year=<yyyy>/part-0.parquet)
  const STAT_PARTITIONS = {
    median: ["median"],
    band: ["median", "p25", "p75"],
    agreement_moderate: ["agreement_moderate"],
    agreement_severe: ["agreement_severe"],
    dir_agreement_drier: ["dir_agreement_drier"],
  };
  const STAT_LABEL = {
    median: "median",
    p25: "p25",
    p75: "p75",
    agreement_moderate: "agreement (moderate)",
    agreement_severe: "agreement (severe)",
    // published only when step 07 emitted it and step 09 exported it; the
    // option is enabled dynamically from the catalog (R3: no placeholders)
    dir_agreement_drier: "direction of change (share of models drier)",
  };
  const SCENARIO_LABEL = { ssp245: "SSP2-4.5", ssp585: "SSP5-8.5" };
  const YEAR_RE = /year=(\d{4})\//;

  let catalog = null;       // shared catalog.json object (see getCatalog)
  let mapApi = null;        // DIE.MapView.createChoropleth() instance (lazy)
  let lastMapValues = null; // Map district_id -> value for the current map frame
  let lastMapStat = null;   // stat key behind lastMapValues
  let lastMapVar = null;    // variable id behind lastMapValues
  let lastDirN = null;      // Map district_id -> dir_agreement_n (exact denominator)
  let bandSeq = 0;          // stale-render guard: only the latest render paints
  let mapSeq = 0;           // same for the choropleth
  let divApi = null;        // SPI–SPEI divergence choropleth (lazy)
  let divValues = null;     // Map district_id -> {spi, spei, d} current frame
  let divSeq = 0;           // stale-render guard for the divergence map
  let rankingData = null;   // parsed data/ranking.json (M5.5)
  let baselineEvents = null; // parsed data/events/baseline_1981_2014.json (M5.8, window per register D6)
  let seamSd = null;         // X7: Map district_id -> SD(era B - era A) SPEI-12 (M6.8)

  const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function track(control, value) {
    if (DIE.Telemetry) {
      try { DIE.Telemetry.track("proj_control", { control, value }); } catch (e) {}
    }
  }

  /* ---- catalog ---------------------------------------------------------- */
  /* Shared promise through the engine service when available (dedupes with
   * Engine Lab); direct no-store fetch as the fallback (P1/P2). */

  function fetchCatalogDirect() {
    const url = new URL("/data/parquet/catalog.json", location.origin).href;
    return fetch(url, { cache: "no-store" }).then((r) => {
      if (!r.ok) throw new Error("catalog.json HTTP " + r.status);
      return r.json();
    });
  }

  function getCatalog() {
    if (DIE.Engine && DIE.Engine.ensureCatalog) return DIE.Engine.ensureCatalog();
    return fetchCatalogDirect();   // engine module missing: fresh fetch
  }

  function eraC() {
    return catalog && catalog.eras && catalog.eras.projections;
  }

  function projVariable(id) {
    return (catalog.variables || []).find((v) => v.id === id) || null;
  }

  // Published era-C record window, read from the COMMITTED catalog (never
  // hard-coded): 2015-2050 while the SSP inputs stopped at 2050, 2015-2100
  // once the full record is published. Every clamp, custom-range bound and
  // the late-century window option derive from this.
  function projRecordRange() {
    const ec = eraC();
    const ys = ((ec && ec.years) || []).map(Number).filter(Number.isFinite);
    if (!ys.length) return { from: 2015, to: 2015, n: 0 };
    return { from: Math.min(...ys), to: Math.max(...ys), n: ys.length };
  }

  /* ---- helpers ----------------------------------------------------------- */

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }

  function windowRange() {
    if (state.window === "custom") {
      let a = clampYear(state.customFrom);
      let b = clampYear(state.customTo);
      return a <= b ? [a, b] : [b, a];
    }
    const w = WINDOWS[state.window];
    return [w.from, w.to];
  }

  function clampYear(y) {
    const rec = projRecordRange();
    const n = Number(y) || rec.from;
    return Math.max(rec.from, Math.min(rec.to, Math.round(n)));
  }

  // Keep the time-window selector honest against the published record: the
  // late-century option is enabled only when the store really covers at least
  // 10 years of 2081-2100 (the direction statistic's minimum window, D6), and
  // the custom inputs are bounded by the record itself.
  function syncRecordRangeUI() {
    const rec = projRecordRange();
    const sel = $("projWindow");
    const late = sel && sel.querySelector('option[value="late"]');
    if (late) {
      const covered = Math.max(
        0, Math.min(rec.to, 2100) - Math.max(rec.from, 2081) + 1
      );
      const ok = covered >= 10;
      late.disabled = !ok;
      late.textContent = ok
        ? "Late century (2081–2100)"
        : "Late century (2081–2100) — inputs pending (record ends " + rec.to + ")";
      if (!ok && state.window === "late") {
        state.window = "mid";
        sel.value = "mid";
      }
    }
    for (const id of ["projFromYear", "projToYear"]) {
      const el = $(id);
      if (!el) continue;
      el.min = String(rec.from);
      el.max = String(rec.to);
    }
    const cf = $("projFromYear"), ct = $("projToYear");
    if (cf) cf.value = String(clampYear(state.customFrom));
    if (ct) ct.value = String(clampYear(state.customTo));
  }

  /* ---- banner + status --------------------------------------------------- */

  function renderBanner() {
    const el = $("projBanner");
    const ec = DIE.meta && DIE.meta.era_c;
    if (!ec) { el.innerHTML = ""; return; }
    // M5.7 refinement: honest ensemble n (X3), median always shown with its
    // 25–75 % range, model disagreement framed as a finding (not noise),
    // explicit era labels and the no-splice rule — verbatim where possible.
    const en = ec.ensemble || null;
    const nLine = en
      ? "<b>Honest ensemble:</b> n = " + en.n +
        " best-subset models (" + en.subset.join(", ") +
        ") — selected by the committed stability criterion (largest-gap core " +
        "extended by reweighting-stability order), never a rank cutoff."
      : "";
    const spreadLine =
      "<b>The median is never shown alone:</b> every view pairs it with the " +
      "25–75 % model range, and model disagreement is a <b>finding</b>, " +
      "not noise to hide (agreement layers default first, X2).";
    const eraLine =
      "<b>Era labels:</b> era C (simulations, " + esc(ec.label) +
      ") is never spliced with era B (1981–2025, Gridded Multi-Source Product) — the two eras are " +
      "presented side by side only, with the seam visible.";
    el.innerHTML =
      "<b>Projections, not forecasts.</b> " + esc(ec.banner) +
      " Published as <b>" + esc(ec.label) + "</b>." +
      (nLine ? "<br>" + nLine : "") +
      "<br>" + spreadLine +
      "<br>" + eraLine;
  }

  function renderStatus() {
    const ec = eraC();
    const mc = DIE.meta && DIE.meta.era_c;
    const meta = $("projStatusMeta");
    if (!ec) {
      meta.textContent = "catalog.json — projections era missing";
      $("projStatusEra").textContent = "unavailable";
      return;
    }
    meta.textContent = "data/parquet/catalog.json";
    // honest wording from metadata.json (the contract), catalog as fallback
    $("projStatusEra").textContent = (mc && mc.status) ||
      (ec.available ? "available" : "pending — no files published");
    const scenarios = (mc && mc.scenarios) ||
      Object.keys(
        ((projVariable(state.variable) || {}).files || {}).projections || {});
    $("projStatusScenarios").textContent =
      scenarios.map((s) => SCENARIO_LABEL[s] || s).join(" · ");
    const ys = ec.years || [];
    $("projStatusYears").textContent = ys.length
      ? ys[0] + " – " + ys[ys.length - 1] + " (" + ys.length + " years)"
      : "—";
    const en = (DIE.meta && DIE.meta.era_c && DIE.meta.era_c.ensemble) || null;
    $("projStatusEnsemble").textContent = en
      ? "n = " + en.n + " bias-corrected models (best subset): " +
        en.subset.join(", ")
      : "—";
    const pet = (DIE.meta && DIE.meta.era_c && DIE.meta.era_c.pet) || null;
    $("projStatusPet").textContent = pet
      ? pet.method + " — per-era PET seam (era B ERA5-Land frozen; era C applied identically to reference and model temperature)"
      : "—";
  }

  /* ---- variable selector -------------------------------------------------- */
  /* Only variables that actually have published era C files are offered. */

  function renderVariableOptions() {
    const sel = $("projVariable");
    const ec = eraC();
    const avail = (catalog.variables || []).filter(
      (v) => v.files && v.files.projections &&
        Object.keys(v.files.projections).length > 0);
    sel.innerHTML = avail.map((v) => {
      const label = v.label || v.id;
      return '<option value="' + esc(v.id) + '">' + esc(label) + "</option>";
    }).join("");
    if (!avail.some((v) => v.id === state.variable) && avail.length) {
      state.variable = avail[0].id;
    }
    sel.value = state.variable;
    void ec;
  }

  /* ---- selection check ----------------------------------------------------- */
  /* Resolves the current selection against the committed catalog only. */

  function renderCheck() {
    const tbody = $("projCheckTable").querySelector("tbody");
    const note = $("projCheckNote");
    const meta = $("projCheckMeta");
    const ec = eraC();
    if (!ec || !ec.available) {
      tbody.innerHTML = "";
      note.textContent = "Era C products are not published yet — nothing to check.";
      return;
    }
    const v = projVariable(state.variable);
    if (!v) {
      tbody.innerHTML = "";
      note.textContent = "Selected variable has no published era C files.";
      return;
    }
    const scenFiles = (v.files.projections || {})[state.scenario] || {};
    const [from, to] = windowRange();
    const stats = STAT_PARTITIONS[state.statistic] || [];
    const label =
      SCENARIO_LABEL[state.scenario] + " · " + (v.label || v.id) + " · " +
      (state.statistic === "band" ? "median + p25 + p75" : STAT_LABEL[state.statistic]);

    let worst = "full";
    const rows = stats.map((st) => {
      const files = scenFiles[st] || [];
      const years = new Set();
      for (const f of files) {
        const m = YEAR_RE.exec(f.replace(/\\/g, "/") + "/");
        if (m) years.add(Number(m[1]));
      }
      if (st === "dir_agreement_drier") {
        // window-constant: report its own published span, never the selected
        // window's coverage (the statistic is not a monthly series)
        const ys = [...years].sort((a, b) => a - b);
        const span = ys.length
          ? ys[0] + "–" + ys[ys.length - 1] + " (window-constant)"
          : "not published";
        return "<tr><td>" + esc("stat=" + st) + "</td><td class=\"num\">" +
          files.length + "</td><td class=\"num\">" + ys.length +
          "</td><td>" + esc(span) + "</td></tr>";
      }
      let covered = 0;
      for (let y = from; y <= to; y++) if (years.has(y)) covered++;
      const total = to - from + 1;
      const missing = total - covered;
      let status;
      if (covered === 0) {
        status = "not published for this window";
        worst = "none";
      } else if (missing > 0) {
        status = "partial — " + missing + " of " + total + " years not published";
        if (worst !== "none") worst = "partial";
      } else {
        status = "full";
      }
      return "<tr><td>" + esc("stat=" + st) + "</td><td class=\"num\">" +
        files.length + "</td><td class=\"num\">" + covered + "/" + total +
        "</td><td>" + esc(status) + "</td></tr>";
    }).join("");

    tbody.innerHTML = rows;
    meta.textContent = label + " · window " + from + "–" + to;
    if (state.statistic === "dir_agreement_drier") {
      const win = dirWindowLabel();
      note.textContent =
        "Resolved against the committed catalog (no engine query yet). The " +
        "direction-of-change statistic is computed once per district over its " +
        "effective window" + (win ? " (" + win + ")" : "") + " and repeated " +
        "across the months inside it, so it is not a monthly series and the " +
        "time-window selector above does not apply to it. Coverage of each " +
        "statistic is listed in the table.";
      return;
    }
    note.innerHTML =
      "Resolved against the committed catalog (no engine query yet). " +
      (worst === "full"
        ? "The full window is covered by published partitions."
        : worst === "partial"
          ? "Part of the window is not published yet — charts (M5.3+) must show the gap, never fill it (R10)."
          : "No published partitions cover this window — the corresponding view must stay disabled with an explanation (section 7).");
  }

  /* ---- era C views (M5.3) ------------------------------------------------ */
  /* Band chart: ensemble median + 25–75 % band (model spread), scope set by
   * the geography selector. Choropleth: one (year, month) frame per stat.
   * Both consume the REAL era-C store via the engine service — no fixtures
   * (R3), no forecasts (R2), sample sizes reported (R10). */

  // metadata indicator object for a store id (store "spi_03" ↔ meta "spi_3")
  function metaIndicator(storeId) {
    if (!DIE.indicatorById) return null;
    return DIE.indicatorById.get(String(storeId).replace(/_0(\d)$/, "_$1")) || null;
  }

  // z-scores 2 dp; SMA/VCI percentages 1 dp
  function fmtVal(storeId, v) {
    if (!Number.isFinite(v)) return "no data";
    return /_0?(1|3|6|12)$/.test(storeId) ? v.toFixed(2) : v.toFixed(1);
  }

  // truncation thresholds (same constants as the v1.0 events engine):
  // McKee moderate −1.0 z, SMA −15 %, VCI 30 %
  const THRESHOLDS = { spi: -1.0, spei: -1.0, sma: -15, vci: 30 };
  function familyOf(storeId) {
    if (storeId.indexOf("spi") === 0) return "spi";
    if (storeId.indexOf("spei") === 0) return "spei";
    if (storeId.indexOf("sma") === 0) return "sma";
    if (storeId.indexOf("vci") === 0) return "vci";
    return null;
  }

  // agreement stat colours: share of models agreeing on the drought class,
  // 5 fraction bins; honest-n note ("x of 8 models") lives in the legend
  const AGREEMENT_COLORS = ["#EDF2F7", "#C3D4E3", "#84A9C9", "#41729E", "#211C15"];
  const AGREEMENT_BINS = [
    { test: (f) => f <= 0, label: "0 of 8 models", range: "0" },
    { test: (f) => f <= 0.25, label: "1–2 of 8 models", range: "(0, 0.25]" },
    { test: (f) => f <= 0.5, label: "3–4 of 8 models", range: "(0.25, 0.5]" },
    { test: (f) => f <= 0.75, label: "5–6 of 8 models", range: "(0.5, 0.75]" },
    { test: () => true, label: "7–8 of 8 models", range: "> 0.75" },
  ];
  function agreementBin(v) {
    if (!Number.isFinite(v)) return null;
    const f = Math.min(1, Math.max(0, v));
    return AGREEMENT_BINS.find((b) => b.test(f));
  }

  // direction-of-change colours: share of subset models whose effective-window
  // mean is drier (lower z) than their own 1981-2014 base mean (register D6).
  // Five share bins; the exact "N of M" count comes from the companion
  // dir_agreement_n partition and is stated in the tooltip (a count, never a
  // probability).
  const DIR_COLORS = ["#F7F3EC", "#E3D2BA", "#C9A97F", "#A57344", "#6E4523"];
  const DIR_BINS = [
    { test: (f) => f <= 0, label: "0 % of models drier", range: "0" },
    { test: (f) => f <= 0.25, label: "1–25 % of models drier", range: "(0, 0.25]" },
    { test: (f) => f <= 0.5, label: "26–50 % of models drier", range: "(0.25, 0.5]" },
    { test: (f) => f <= 0.75, label: "51–75 % of models drier", range: "(0.5, 0.75]" },
    { test: () => true, label: "76–100 % of models drier", range: "> 0.75" },
  ];
  function dirBin(v) {
    if (!Number.isFinite(v)) return null;
    const f = Math.min(1, Math.max(0, v));
    return DIR_BINS.find((b) => b.test(f));
  }
  function effectiveStat() {
    // the band statistic maps the median on the choropleth (explained in UI)
    return state.statistic === "band" ? "median" : state.statistic;
  }

  /* -- geography pickers --------------------------------------------------- */

  function renderGeoPickers() {
    if (!DIE.registry) return;
    const dSel = $("projDistrict"), sSel = $("projState");
    if (!dSel.options.length) {
      const frag = document.createDocumentFragment();
      for (const [sid, list] of DIE.registry.byState) {
        const s = DIE.registry.states.get(sid);
        const og = document.createElement("optgroup");
        og.label = s ? s.name : sid;
        for (const d of list) {
          const o = document.createElement("option");
          o.value = d.id;
          o.textContent = d.name;
          og.appendChild(o);
        }
        frag.appendChild(og);
      }
      dSel.appendChild(frag);
      dSel.value = state.district;
      if (dSel.selectedIndex === -1) {
        dSel.selectedIndex = 0;
        state.district = dSel.value;
      }
    }
    if (!sSel.options.length) {
      const states = [...DIE.registry.states.entries()]
        .sort((a, b) => a[1].name.localeCompare(b[1].name));
      const frag = document.createDocumentFragment();
      for (const [sid, s] of states) {
        const o = document.createElement("option");
        o.value = sid;
        o.textContent = s.name;
        frag.appendChild(o);
      }
      sSel.appendChild(frag);
      sSel.value = state.stateSid;
      if (sSel.selectedIndex === -1) {
        sSel.selectedIndex = 0;
        state.stateSid = sSel.value;
      }
    }
    updateGeoVisibility();
  }

  function updateGeoVisibility() {
    $("projDistrict").hidden = state.geography !== "district";
    $("projState").hidden = state.geography !== "state";
  }

  function syncGeoControls() {
    $("projGeography").value = state.geography;
    updateGeoVisibility();
    if (DIE.registry) {
      const dSel = $("projDistrict");
      if (DIE.registry.districts.has(state.district)) dSel.value = state.district;
      const sSel = $("projState");
      if (DIE.registry.states.has(state.stateSid)) sSel.value = state.stateSid;
    }
  }

  /* -- aggregation (v1.0 area-weighting rule) ------------------------------ */

  // weight = registry area_km2, renormalised over the districts with a finite
  // value in that exact month (missing data drops the district for that month
  // only — never imputed, R10). Never an unweighted mean (R9).
  function aggregateWeighted(rows, filterFn) {
    const groups = new Map(); // year*100+month -> {y, m, s, w, n}
    for (const r of rows) {
      if (filterFn && !filterFn(r.district_id)) continue;
      if (!Number.isFinite(r.value)) continue;
      const d = DIE.registry && DIE.registry.districts.get(r.district_id);
      if (!d || !Number.isFinite(d.area) || d.area <= 0) continue;
      const key = r.year * 100 + r.month;
      let g = groups.get(key);
      if (!g) groups.set(key, (g = { y: r.year, m: r.month, s: 0, w: 0, n: 0 }));
      g.s += r.value * d.area;
      g.w += d.area;
      g.n += 1;
    }
    const out = [];
    for (const g of groups.values()) {
      out.push({ year: g.y, month: g.m, value: g.s / g.w, n: g.n });
    }
    out.sort((a, b) => a.year - b.year || a.month - b.month);
    return out;
  }

  /* -- band chart ------------------------------------------------------------ */

  function chartYearRange() {
    const [from, to] = windowRange();
    // published era-C years; clamping keeps custom windows from opening
    // partitions that were never written (the check table reports the gap)
    const rec = projRecordRange();
    const a = Math.max(from, rec.from), b = Math.min(to, rec.to);
    return a <= b ? [a, b] : [rec.from, rec.from];
  }

  async function ensurePlotly() {
    if (window.Plotly) return true;
    if (window.DIE_LIBS && window.DIE_LIBS.ensure) {
      const ok = await window.DIE_LIBS.ensure("Plotly");
      if (ok && window.Plotly) return true;
    }
    return false;
  }

  async function drawBand() {
    const seq = ++bandSeq;
    const meta = $("projBandMeta"), note = $("projBandNote");
    const chartEl = $("projBandChart");
    if (!catalog || !eraC() || !eraC().available) return;
    const ind = metaIndicator(state.variable);
    if (!ind) return;
    const [from, to] = chartYearRange();
    const district = state.geography === "district" ? state.district : null;

    const base = "era C · " + SCENARIO_LABEL[state.scenario] + " · " + ind.label +
      " · " + from + "–" + to;
    meta.textContent = base;
    note.textContent = "querying the era-C store…";

    try {
      let medianRows, p25Rows, p75Rows, scopeLabel, nNote;
      if (district) {
        const opts = (stat) => ({
          scenario: state.scenario, variable: state.variable,
          stat, yearRange: [from, to], district,
        });
        [medianRows, p25Rows, p75Rows] = await Promise.all([
          DIE.Engine.ensemble(opts("median")),
          DIE.Engine.ensemble(opts("p25")),
          DIE.Engine.ensemble(opts("p75")),
        ]);
        if (seq !== bandSeq) return;   // a newer selection superseded this render
        const reg = DIE.registry && DIE.registry.districts.get(district);
        scopeLabel = reg ? reg.name + " (" + reg.state + ")" : district;
        nNote = "district-level slice";
      } else {
        const sid = state.stateSid;
        const filterFn = state.geography === "state"
          ? (id) => {
              const d = DIE.registry && DIE.registry.districts.get(id);
              return !!d && d.sid === sid;
            }
          : null;
        const opts = (stat) => ({
          scenario: state.scenario, variable: state.variable,
          stat, yearRange: [from, to],
        });
        [medianRows, p25Rows, p75Rows] = await Promise.all([
          DIE.Engine.ensemble(opts("median")),
          DIE.Engine.ensemble(opts("p25")),
          DIE.Engine.ensemble(opts("p75")),
        ]);
        if (seq !== bandSeq) return;   // a newer selection superseded this render
        const agg = (rows) => aggregateWeighted(rows, filterFn);
        medianRows = agg(medianRows);
        p25Rows = agg(p25Rows);
        p75Rows = agg(p75Rows);
        const s = DIE.registry && DIE.registry.states.get(sid);
        scopeLabel = state.geography === "state" && s
          ? s.name + " (state)"
          : "India (national, area-weighted)";
        let nMin = Infinity, nMax = -Infinity;
        for (const r of medianRows) {
          if (r.n < nMin) nMin = r.n;
          if (r.n > nMax) nMax = r.n;
        }
        nNote = Number.isFinite(nMin)
          ? "area-weighted mean, " + nMin + "–" + nMax + " districts with data per month"
          : "no districts with data";
      }

      // x spine from the median series; p25/p75 looked up per key (nulls kept)
      const p25 = new Map(p25Rows.map((r) => [r.year * 100 + r.month, r.value]));
      const p75 = new Map(p75Rows.map((r) => [r.year * 100 + r.month, r.value]));
      const xs = [], med = [], lo = [], hi = [];
      for (const r of medianRows) {
        const key = r.year * 100 + r.month;
        xs.push(r.year + "-" + String(r.month).padStart(2, "0") + "-01");
        med.push(Number.isFinite(r.value) ? r.value : null);
        lo.push(p25.has(key) && Number.isFinite(p25.get(key)) ? p25.get(key) : null);
        hi.push(p75.has(key) && Number.isFinite(p75.get(key)) ? p75.get(key) : null);
      }

      const traces = [
        {
          x: xs, y: hi, type: "scatter", mode: "lines",
          line: { width: 0 }, hoverinfo: "skip", showlegend: false,
        },
        {
          x: xs, y: lo, type: "scatter", mode: "lines",
          fill: "tonexty", fillcolor: "rgba(178,92,61,0.20)",
          line: { width: 0 }, hoverinfo: "skip", showlegend: true,
          name: "25–75 % of models",
        },
        {
          x: xs, y: med, type: "scatter", mode: "lines",
          line: { color: "#b25c3d", width: 2 }, showlegend: true,
          name: "ensemble median",
          hovertemplate: "%{x|%Y-%m}: %{y:.2f}<extra>" +
            esc(scopeLabel) + "</extra>",
        },
      ];

      const layout = {
        font: { family: "Inter, IBM Plex Sans, sans-serif", size: 11, color: "#2E2820" },
        margin: { l: 52, r: 16, t: 14, b: 34 },
        hovermode: "x unified",
        showlegend: true,
        legend: { orientation: "h", y: 1.14, font: { size: 10 } },
        shapes: [],
        annotations: [],
        xaxis: { gridcolor: "#EFE8D8", linecolor: "#CFC2A8", tickfont: { size: 9.5 } },
        yaxis: {
          title: { text: ind.label + " (" + ind.units + ")", font: { size: 10.5, color: "#6E6250" } },
          gridcolor: "#EFE8D8", linecolor: "#CFC2A8", tickfont: { size: 10 },
        },
      };
      const fam = familyOf(state.variable);
      const th = fam ? THRESHOLDS[fam] : null;
      if (th !== null && th !== undefined) {
        layout.shapes.push({
          type: "line", xref: "paper", x0: 0, x1: 1,
          yref: "y", y0: th, y1: th,
          line: { color: "#8F252F", width: 1, dash: "dash" },
        });
        layout.annotations.push({
          xref: "paper", x: 1, yref: "y", y: th,
          text: "moderate drought τ = " + th,
          showarrow: false, xanchor: "right",
          font: { size: 9, color: "#8F252F" }, yanchor: "bottom",
        });
      }

      if (seq !== bandSeq) return;     // guard again after the (slow) aggregation
      if (await ensurePlotly()) {
        if (seq !== bandSeq) return;
        await Plotly.react(chartEl, traces, layout, { displayModeBar: false, responsive: true });
      } else {
        chartEl.innerHTML =
          '<p class="table-help" style="padding:14px">Plotly could not be loaded — the band chart is unavailable (data itself was served fine).</p>';
      }

      const missMed = med.filter((v) => v === null).length;
      note.innerHTML =
        esc(scopeLabel) + " · " + esc(nNote) +
        " · median across the honest 8-model subset, band = model spread (p25–p75). " +
        "Era C projection — <strong>not a forecast</strong>. Months rendered, not imputed" +
        (missMed ? " (" + missMed + " of " + med.length + " months missing in this window)" : "") + ".";
    } catch (err) {
      console.warn("[projections] band chart failed:", err);
      note.textContent = "Band chart unavailable: " + String(err && err.message || err);
    }
  }

  /* -- choropleth -------------------------------------------------------------- */

  function catalogYears(scenario, statKey) {
    const v = projVariable(state.variable);
    const files = ((v && v.files && v.files.projections &&
      v.files.projections[scenario]) || {})[statKey] || [];
    const years = new Set();
    for (const f of files) {
      const m = YEAR_RE.exec(f.replace(/\\/g, "/") + "/");
      if (m) years.add(Number(m[1]));
    }
    return [...years].sort((a, b) => a - b);
  }

  /* -- direction-of-change availability / window --------------------------- */
  /* The statistic is published only when step 07 emitted it and step 09
   * exported it. Its window is whatever the pipeline recorded (catalog years
   * are the source of truth; metadata.json is the fallback). */

  function dirPublished() {
    return (catalog.variables || []).some((v) => {
      const p = (v.files && v.files.projections) || {};
      return Object.keys(p).some((s) =>
        !!(p[s] && p[s].dir_agreement_drier && p[s].dir_agreement_drier.length));
    });
  }

  function dirWindowYears() {
    const own = catalogYears(state.scenario, "dir_agreement_drier");
    if (own.length) return own;
    const other = state.scenario === "ssp585" ? "ssp245" : "ssp585";
    return catalogYears(other, "dir_agreement_drier");
  }

  function dirWindowLabel() {
    const ys = dirWindowYears();
    if (ys.length) return ys[0] + "–" + ys[ys.length - 1];
    const md = (DIE.meta && DIE.meta.era_c && DIE.meta.era_c.dir_agreement) || null;
    return md && md.window_effective
      ? String(md.window_effective).replace("-", "–") : null;
  }

  function dirWindowNote() {
    const md = (DIE.meta && DIE.meta.era_c && DIE.meta.era_c.dir_agreement) || null;
    return md && md.window_note ? String(md.window_note) : "";
  }

  function syncStatisticOptions() {
    const sel = $("projStatistic");
    const opt = [...sel.options].find((o) => o.value === "dir_agreement_drier");
    if (!opt) return;
    const ok = dirPublished();
    opt.disabled = !ok;
    opt.textContent = ok
      ? "Direction of change — models agreeing drier"
      : "Direction of change — models agreeing drier (awaiting published partitions)";
    if (!ok && state.statistic === "dir_agreement_drier") {
      state.statistic = "agreement_moderate";
      sel.value = state.statistic;
    }
  }

  function populateMapPeriods() {
    const years = catalogYears(state.scenario, effectiveStat());
    const ySel = $("projMapYear"), mSel = $("projMapMonth");
    if (!mSel.options.length) {
      for (let i = 1; i <= 12; i++) {
        const o = document.createElement("option");
        o.value = String(i);
        o.textContent = MONTH_NAMES[i - 1];
        mSel.appendChild(o);
      }
      mSel.value = String(state.mapMonth);
    }
    const wanted = String(state.mapYear);
    ySel.innerHTML = "";
    for (const y of years) {
      const o = document.createElement("option");
      o.value = String(y);
      o.textContent = String(y);
      ySel.appendChild(o);
    }
    ySel.value = years.includes(state.mapYear)
      ? wanted
      : String(years[Math.floor(years.length / 2)]);
    state.mapYear = Number(ySel.value);
  }

  function renderLegend(statKey) {
    const el = $("projLegend");
    el.innerHTML = "";
    const row = (color, label, range) => {
      const div = document.createElement("div");
      div.className = "legend-row";
      div.innerHTML =
        '<span class="legend-swatch" style="background:' + color + '"></span>' +
        "<span>" + esc(label) + "</span>" +
        '<span class="legend-range">' + esc(range) + "</span>";
      el.appendChild(div);
    };
    if (statKey === "dir_agreement_drier") {
      const head = document.createElement("div");
      head.className = "legend-head";
      const win = dirWindowLabel();
      head.textContent = "Share of subset models whose window mean is drier " +
        "than their own 1981–2014 base" + (win ? " — window " + win : "");
      el.appendChild(head);
      DIR_BINS.forEach((b, i) =>
        row(DIR_COLORS[i], b.label, b.range));
    } else if (statKey.indexOf("agreement") === 0) {
      const head = document.createElement("div");
      head.className = "legend-head";
      // exact definition (M5.4): count of subset models at/below the
      // threshold in that month — a count, never a probability
      head.textContent = statKey === "agreement_severe"
        ? "Subset models ≤ −1.5 (severe) — count of the honest 8-model ensemble"
        : "Subset models ≤ −1.0 (moderate) — count of the honest 8-model ensemble";
      el.appendChild(head);
      AGREEMENT_BINS.forEach((b, i) =>
        row(AGREEMENT_COLORS[i], b.label, b.range));
    } else {
      const ind = metaIndicator(state.variable);
      if (ind) {
        const head = document.createElement("div");
        head.className = "legend-head";
        head.textContent = ind.label + " classes (" + ind.units + ")";
        el.appendChild(head);
        for (const c of ind.classes) row(c.color, c.label, classRange(c));
      }
    }
    row("#E8E1D2", "No data", "missing month");
  }

  function classRange(c) {
    const lo = c.min === null || c.min === undefined ? "−∞" : c.min;
    const hi = c.max === null || c.max === undefined ? "+∞" : c.max;
    return String(lo).replace("-", "−") + " … " + String(hi).replace("-", "−");
  }

  function bindMapTooltips() {
    // bound ONCE with function tooltips: content re-evaluates against the
    // latest lastMapValues on every hover, so frames never re-bind 724 layers
    for (const [id, layer] of mapApi.layerById) {
      layer.bindTooltip(() => {
        const d = DIE.registry && DIE.registry.districts.get(id);
        const v = lastMapValues ? lastMapValues.get(id) : undefined;
        const statKey = lastMapStat;
        const label = STAT_LABEL[statKey] || statKey;
        if (!d) return esc(label) + ": " + esc(fmtVal(state.variable, v));
        let line2;
        if (statKey === "dir_agreement_drier") {
          const nRaw = lastDirN ? lastDirN.get(id) : undefined;
          const m = Number.isFinite(nRaw) && nRaw > 0 ? nRaw : null;
          const win = dirWindowLabel();
          // exact definition: a COUNT of subset models whose window mean is
          // drier than their own base mean — never a probability (R9)
          if (!Number.isFinite(v) || m === null) {
            line2 = "no data";
          } else {
            const count = Math.round(Math.min(1, Math.max(0, v)) * m);
            line2 = count + " of " + m + " subset models drier than their " +
              "1981–2014 base" + (win ? " (window " + win + ")" : "") +
              " — count, not a probability";
          }
        } else if (statKey && statKey.indexOf("agreement") === 0) {
          const models = Number.isFinite(v) ? Math.round(Math.min(1, Math.max(0, v)) * 8) : null;
          // exact definition (M5.4): a COUNT of subset models at or below the
          // truncation threshold in this month — never a probability (R9)
          const th = statKey.indexOf("severe") !== -1 ? "−1.5" : "−1.0";
          line2 = models === null
            ? "no data"
            : models + " of 8 subset models ≤ " + th +
              " (count, not a probability)";
        } else {
          const ind = metaIndicator(lastMapVar);
          const c = ind && Number.isFinite(v) ? DIE.classify(v, ind) : null;
          line2 = Number.isFinite(v)
            ? fmtVal(lastMapVar, v) + " " + (ind ? ind.units : "") +
              (c ? " — " + c.label : "")
            : "no data (rendered, never imputed)";
        }
        return "<strong>" + esc(d.name) + "</strong><br>" + esc(d.state) +
          "<br>" + esc(label) + ": " + line2 + seamTooltipLine(id);
      }, { sticky: true });
    }
  }

  /* X7 seam uncertainty (M6.8). Quoted only for SPEI-12: that is the series
   * the X7 memo names and the one the cross-validation builder measures. It is
   * the measured SD of the era A - era B difference over 1981-2014 — a
   * historical disagreement, never a projection confidence interval. */
  function seamTooltipLine(id) {
    if (lastMapVar !== "spei_12" || !seamSd || !seamSd.has(id)) return "";
    return "<br>seam SD ±" + seamSd.get(id).toFixed(2) +
      " z (era A − era B, 1981–2014; not a confidence interval)";
  }

  async function ensureSeam() {
    if (seamSd) return seamSd;
    try {
      seamSd = await DIE.Engine.seamUncertainty();
    } catch (err) {
      console.warn("[projections] seam uncertainty unavailable:", err);
      seamSd = new Map();   // no line; never a placeholder value
    }
    return seamSd;
  }

  function seamStats() {
    if (!seamSd || !seamSd.size) return null;
    const vals = Array.from(seamSd.values()).sort((a, b) => a - b);
    const mid = Math.floor(vals.length / 2);
    const median = vals.length % 2
      ? vals[mid] : (vals[mid - 1] + vals[mid]) / 2;
    return { n: vals.length, median };
  }

  async function renderMap() {
    const seq = ++mapSeq;
    const mapEl = $("projMap");
    const note = $("projMapNote"), meta = $("projMapMeta");
    if (!catalog || !eraC() || !eraC().available || !DIE.MapView) return;
    const statKey = effectiveStat();
    if (statKey === "dir_agreement_drier" && !dirWindowYears().length) {
      note.textContent = "Direction of change is not published for this " +
        "indicator yet (step-07/09 products pending).";
      return;
    }
    try {
      if (!mapApi) {
        mapApi = DIE.MapView.createChoropleth(mapEl, {
          tooltip: false,
          onDistrictClick: (id) => {
            // a map click selects the district for the band chart
            state.district = id;
            state.geography = "district";
            syncGeoControls();
            drawBand();
          },
        });
        lastMapValues = new Map();
        lastMapStat = statKey;
        lastMapVar = state.variable;
        bindMapTooltips();
      }
      populateMapPeriods();
      await ensureSeam();
      meta.textContent = "era C · " + SCENARIO_LABEL[state.scenario] + " · " +
        (STAT_LABEL[statKey] || statKey) + " · " + state.mapYear + "-" +
        MONTH_NAMES[state.mapMonth - 1];
      note.textContent = "querying the era-C store…";

      const rows = await DIE.Engine.ensemble({
        scenario: state.scenario,
        variable: state.variable,
        stat: statKey,
        yearRange: [state.mapYear, state.mapYear],
      });
      let nRows = null;
      if (statKey === "dir_agreement_drier") {
        // exact denominator for the tooltip ("N of M subset models drier")
        nRows = await DIE.Engine.ensemble({
          scenario: state.scenario,
          variable: state.variable,
          stat: "dir_agreement_n",
          yearRange: [state.mapYear, state.mapYear],
        });
      }
      if (seq !== mapSeq) return;      // a newer frame superseded this render
      lastMapValues = new Map();
      lastDirN = new Map();
      for (const r of rows) {
        if (r.month === state.mapMonth && Number.isFinite(r.value)) {
          lastMapValues.set(r.district_id, r.value);
        }
      }
      if (nRows) {
        for (const r of nRows) {
          if (r.month === state.mapMonth && Number.isFinite(r.value)) {
            lastDirN.set(r.district_id, r.value);
          }
        }
      }
      lastMapStat = statKey;
      lastMapVar = state.variable;

      const selectedId = state.geography === "district" ? state.district : null;
      let colorFn;
      if (statKey === "dir_agreement_drier") {
        colorFn = (id) => {
          const b = dirBin(lastMapValues.get(id));
          return b ? DIR_COLORS[DIR_BINS.indexOf(b)] : "#E8E1D2";
        };
      } else if (statKey.indexOf("agreement") === 0) {
        colorFn = (id) => {
          const b = agreementBin(lastMapValues.get(id));
          return b ? AGREEMENT_COLORS[AGREEMENT_BINS.indexOf(b)] : "#E8E1D2";
        };
      } else {
        const ind = metaIndicator(state.variable);
        colorFn = (id) => {
          const c = ind && Number.isFinite(lastMapValues.get(id))
            ? DIE.classify(lastMapValues.get(id), ind)
            : null;
          return c ? c.color : "#E8E1D2";
        };
      }
      mapApi.applyData(null, 0, null, selectedId,
        (id) => lastMapValues.get(id), colorFn);
      renderLegend(statKey);

      const nWith = lastMapValues.size;
      let noteText =
        "724 districts at " + state.mapYear + "-" + String(state.mapMonth).padStart(2, "0") +
        " · " + nWith + " with values (missing rendered grey, never imputed). ";
      if (statKey === "dir_agreement_drier") {
        const win = dirWindowLabel();
        noteText +=
          "Direction of change = share of the honest 8-model subset whose " +
          "window mean is drier (lower z) than their own 1981–2014 base mean" +
          (win ? " — window " + win : "") +
          ". Window-constant per district: repeated across the months inside " +
          "the window, absent outside it. A count of models, never a " +
          "probability. ";
        const wn = dirWindowNote();
        if (wn) noteText += "Pipeline window note: " + wn + ". ";
      } else if (statKey.indexOf("agreement") === 0) {
        noteText +=
          "Agreement = count of the honest 8-model subset with the index ≤ " +
          (statKey === "agreement_severe" ? "−1.5 (severe)" : "−1.0 (moderate)") +
          " in this month — a count, not a probability. ";
      } else {
        noteText += "Median across the honest 8-model subset; era C " +
          "projection, not a forecast. ";
      }
      const seam = seamStats();
      if (seam) {
        noteText += "Historical seam uncertainty (X7): per-district SD of era " +
          "A − era B SPEI-12 over 1981–2014, median ±" +
          seam.median.toFixed(2) + " z across " + seam.n + " districts; shown " +
          "in tooltips when SPEI-12 is selected. It measures disagreement " +
          "between the two historical records — not a projection confidence " +
          "interval.";
      } else {
        noteText += "Historical seam uncertainty is unavailable in this " +
          "checkout; no placeholder value is shown (R3).";
      }
      note.textContent = noteText;
    } catch (err) {
      console.warn("[projections] map failed:", err);
      note.textContent = "Choropleth unavailable: " + String(err && err.message || err);
    }
  }

  /* -- ranking panel (M5.5) -------------------------------------------------- */
  /* Multi-metric composite from step-08 validation outputs (via the build-time
   * data/ranking.json). NEVER a single-metric ranking; the subset is the
   * committed stability criterion, not a rank cutoff (R3/R9). */

  async function fetchJSON(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(url + " HTTP " + r.status);
    return r.json();
  }

  function fmtMetric(v, dp) {
    return Number.isFinite(v) ? v.toFixed(dp) : "—";
  }

  async function renderRanking() {
    const note = $("projRankingNote");
    const tbody = $("projRankingTable").querySelector("tbody");
    if (!rankingData) {
      try {
        rankingData = await fetchJSON("data/ranking.json");
      } catch (err) {
        console.warn("[projections] ranking.json unavailable:", err);
        tbody.innerHTML = "";
        note.textContent = "Ranking artifact unavailable (" +
          String(err && err.message || err) +
          ") — run scripts/build_ranking_data.py after step 08. Nothing is fabricated here (R3).";
        return;
      }
    }
    const rows = rankingData.ranking || [];
    tbody.innerHTML = rows.map((r) => {
      const m = r.metrics || {};
      return "<tr" + (r.in_subset ? ' class="rk-subset"' : "") + ">" +
        '<td class="num">' + r.rank + "</td>" +
        "<td>" + esc(r.model) + "</td>" +
        "<td>" + (r.in_subset ? '<span class="rk-badge">subset</span>' : "—") +
        "</td>" +
        '<td class="num">' + r.composite.toFixed(4) + "</td>" +
        '<td class="num">' + fmtMetric(m.pearson_r, 3) + "</td>" +
        '<td class="num">' + fmtMetric(m.abs_bias, 3) + "</td>" +
        '<td class="num">' + fmtMetric(m.rmsd, 3) + "</td>" +
        '<td class="num">' + fmtMetric(m.class_agreement, 3) + "</td>" +
        '<td class="num">' + fmtMetric(m.freq_ratio, 3) + "</td>" +
        '<td class="num">' + fmtMetric(m.duration_ratio, 3) + "</td>" +
        '<td class="num">' + fmtMetric(m.severity_ratio, 3) + "</td>" +
        '<td class="num">' + fmtMetric(m.spatial_r, 3) + "</td>" +
        "</tr>";
    }).join("");

    const w = rankingData.weights_verbatim || {};
    const weightStr = Object.keys(w).map((k) => k + " " + w[k]).join(" · ");
    const cr = rankingData.criterion || {};
    note.innerHTML =
      "Composite = weighted mean of 8 min–max-normalised skill metrics vs IMD " +
      esc((rankingData.source && rankingData.source.window || []).join("–")) +
      " (weights verbatim: " + esc(weightStr) + "). " +
      "Subset n = " + rankingData.ensemble_n + " by the committed stability criterion " +
      "(largest-gap core " + (cr.core_size || "—") + ", gap " +
      (cr.core_gap !== undefined ? cr.core_gap.toFixed(4) : "—") +
      ", " + (cr.stability_draws || "—") + " Dirichlet draws). " +
      "<strong>Historical skill is not future skill</strong>; free-running " +
      "model realisations are not correlated with observations. Where the 8 " +
      "metrics disagree, that disagreement is information — this is why no " +
      "single-metric ranking is shown (R9).";
  }

  /* -- SPI–SPEI divergence map (M5.6) ---------------------------------------- */
  /* Divergence d = SPI-3 − SPEI-3 (both ensemble medians, same 8 models, same
   * scenario/month): d > 0 means the demand (PET) term decouples the two
   * indices — "rainfall alone does not decide India's drought future; demand
   * does half the work." Computed from shipped products only. */

  const DIV_BINS = [
    { test: (d) => d >= 0.5, label: "strong demand-driven", range: "SPI−SPEI ≥ +0.5", color: "#A63B34" },
    { test: (d) => d >= 0.25, label: "mild demand-driven", range: "+0.25 … +0.5", color: "#D08746" },
    { test: (d) => d > -0.25, label: "balanced", range: "−0.25 … +0.25", color: "#E7E2D8" },
    { test: (d) => d > -0.5, label: "mild rainfall-driven", range: "−0.5 … −0.25", color: "#7FA3C4" },
    { test: () => true, label: "strong rainfall-driven", range: "≤ −0.5", color: "#33608A" },
  ];
  function divBin(d) {
    if (!Number.isFinite(d)) return null;
    return DIV_BINS.find((b) => b.test(d));
  }

  function divYearList() {
    // published years for the spi_03 median partitions (same layout for spei)
    return catalogYears("ssp245", "median").length
      ? catalogYears(state.scenario, "median")
      : [];
  }

  function populateDivPeriods() {
    const years = divYearList();
    const ySel = $("projDivYear"), mSel = $("projDivMonth");
    if (!mSel.options.length) {
      for (let i = 1; i <= 12; i++) {
        const o = document.createElement("option");
        o.value = String(i);
        o.textContent = MONTH_NAMES[i - 1];
        mSel.appendChild(o);
      }
      mSel.value = String(state.divMonth);
    }
    ySel.innerHTML = "";
    for (const y of years) {
      const o = document.createElement("option");
      o.value = String(y);
      o.textContent = String(y);
      ySel.appendChild(o);
    }
    ySel.value = years.includes(state.divYear)
      ? String(state.divYear)
      : String(years[Math.floor(years.length / 2)]);
    state.divYear = Number(ySel.value);
  }

  function bindDivTooltips() {
    for (const [id, layer] of divApi.layerById) {
      layer.bindTooltip(() => {
        const d = DIE.registry && DIE.registry.districts.get(id);
        const f = divValues ? divValues.get(id) : undefined;
        if (!d) return "divergence: —";
        if (!f || !Number.isFinite(f.d)) {
          return "<strong>" + esc(d.name) + "</strong><br>" + esc(d.state) +
            "<br>divergence: no data (rendered, never imputed)";
        }
        const bin = divBin(f.d);
        return "<strong>" + esc(d.name) + "</strong><br>" + esc(d.state) +
          "<br>SPI-3 " + (f.spi === null ? "—" : f.spi.toFixed(2)) +
          " · SPEI-3 " + (f.spei === null ? "—" : f.spei.toFixed(2)) +
          "<br>divergence " + (f.d >= 0 ? "+" : "−") +
          Math.abs(f.d).toFixed(2) +
          (bin ? " — " + esc(bin.label) : "");
      }, { sticky: true });
    }
  }

  function renderDivLegend() {
    const el = $("projDivLegend");
    el.innerHTML = "";
    const head = document.createElement("div");
    head.className = "legend-head";
    head.textContent = "SPI-3 median − SPEI-3 median (same 8 models, same month)";
    el.appendChild(head);
    DIV_BINS.forEach((b) => {
      const div = document.createElement("div");
      div.className = "legend-row";
      div.innerHTML =
        '<span class="legend-swatch" style="background:' + b.color + '"></span>' +
        "<span>" + esc(b.label) + "</span>" +
        '<span class="legend-range">' + esc(b.range) + "</span>";
      el.appendChild(div);
    });
    const nd = document.createElement("div");
    nd.className = "legend-row";
    nd.innerHTML =
      '<span class="legend-swatch" style="background:#E8E1D2"></span>' +
      "<span>No data</span>" +
      '<span class="legend-range">missing month</span>';
    el.appendChild(nd);
  }

  async function renderDivergence() {
    const note = $("projDivNote"), meta = $("projDivMeta");
    const mapEl = $("projDivMap");
    if (!catalog || !eraC() || !eraC().available || !DIE.MapView) return;
    const seq = ++divSeq;
    try {
      if (!divApi) {
        divApi = DIE.MapView.createChoropleth(mapEl, {
          tooltip: false,
          onDistrictClick: (id) => {
            state.district = id;
            state.geography = "district";
            syncGeoControls();
            drawBand();
          },
        });
        divValues = new Map();
        bindDivTooltips();
      }
      populateDivPeriods();
      meta.textContent = "era C · " + SCENARIO_LABEL[state.scenario] +
        " · " + state.divYear + "-" + MONTH_NAMES[state.divMonth - 1];
      note.textContent = "querying the era-C store…";

      const opts = (variable) => ({
        scenario: state.scenario, variable, stat: "median",
        yearRange: [state.divYear, state.divYear],
      });
      const [spiRows, speiRows] = await Promise.all([
        DIE.Engine.ensemble(opts("spi_03")),
        DIE.Engine.ensemble(opts("spei_03")),
      ]);
      if (seq !== divSeq) return;   // a newer frame superseded this render
      const spei = new Map(speiRows
        .filter((r) => r.month === state.divMonth)
        .map((r) => [r.district_id, r.value]));
      divValues = new Map();
      for (const r of spiRows) {
        if (r.month !== state.divMonth) continue;
        const sv = Number.isFinite(r.value) ? r.value : null;
        const ev = spei.get(r.district_id);
        const e2 = Number.isFinite(ev) ? ev : null;
        divValues.set(r.district_id, {
          spi: sv, spei: e2,
          d: (sv !== null && e2 !== null) ? sv - e2 : null,
        });
      }
      divApi.applyData(null, 0, null, null, (id) => {
        const f = divValues.get(id);
        return f ? f.d : null;
      }, (id) => {
        const f = divValues.get(id);
        const bin = f && divBin(f.d);
        return bin ? bin.color : "#E8E1D2";
      });
      renderDivLegend();

      const nWith = [...divValues.values()].filter((f) => Number.isFinite(f.d));
      const strongDemand = nWith.filter((f) => f.d >= 0.5).length;
      const mildDemand = nWith.filter((f) => f.d >= 0.25 && f.d < 0.5).length;
      const balanced = nWith.filter((f) => f.d > -0.25 && f.d < 0.25).length;
      const rainfallDriven = nWith.filter((f) => f.d <= -0.25).length;
      note.innerHTML =
        "724 districts at " + state.divYear + "-" +
        String(state.divMonth).padStart(2, "0") + " · " + nWith.length +
        " with both indices · strong demand-driven " + strongDemand +
        " · mild demand-driven " + mildDemand + " · balanced " + balanced +
        " · rainfall-driven " + rainfallDriven +
        ". Both indices are ensemble medians of the SAME 8 models — the " +
        "divergence shows where the Hargreaves PET (demand) term decouples " +
        "SPEI from precipitation-only SPI. It is a property of index " +
        "construction, not a causal attribution (R9). " +
        "<em>Rainfall alone does not decide India's drought future; demand " +
        "does half the work.</em>";
    } catch (err) {
      console.warn("[projections] divergence failed:", err);
      note.textContent = "Divergence map unavailable: " + String(err && err.message || err);
    }
  }

  /* -- future drought events (M5.8 / E14) ------------------------------------- */
  /* Frozen v1.0 runs analysis (DIE.Analytics.findEvents: runs ≤ threshold,
   * min 3 months, severity Σ(τ−x), NaN breaks runs) on era-C ensemble-median
   * series, compared against the era-B 1981–2014 baseline built by
   * scripts/build_events_baseline.py (window = register D6, the GCM-native
   * historical window). Agreement reported alongside (X2);
   * windows are median-based and labelled as such. */

  const EVENTS_ROW_LIMIT = 15;

  function findEventMetrics(values, years) {
    // values: ordered monthly array (null -> NaN); runs on continuous series
    // threshold: the frozen McKee moderate bound (−1.0 z for SPI/SPEI — era C
    // publishes these two families only)
    const events = DIE.Analytics.findEvents(
      values, values.map((_, i) => String(i)),
      THRESHOLDS[familyOf(state.variable)], 3);
    const dur = events.map((e) => e.duration);
    const n = events.length;
    return {
      n_events: n,
      events_per_year: years > 0 ? n / years : null,
      mean_duration: n ? dur.reduce((a, b) => a + b, 0) / n : null,
      max_duration: n ? Math.max(...dur) : 0,
      total_severity: events.reduce((s, e) => s + e.severity, 0),
      n_censored: events.filter(
        (e) => e.startIdx === 0 || e.endIdx === values.length - 1).length,
      valid_months: values.filter(Number.isFinite).length,
    };
  }

  async function ensureBaseline() {
    if (baselineEvents) return baselineEvents;
    baselineEvents = await fetchJSON("data/events/baseline_1981_2014.json");
    return baselineEvents;
  }

  async function renderEvents() {
    const note = $("projEventsNote"), meta = $("projEventsMeta");
    const tbody = $("projEventsTable").querySelector("tbody");
    if (!catalog || !eraC() || !eraC().available) return;
    const ind = metaIndicator(state.variable);
    const th = THRESHOLDS[familyOf(state.variable)];
    if (!ind || !Number.isFinite(th) || !DIE.Analytics ||
      !DIE.Analytics.findEvents) return;
    const [from, to] = chartYearRange();
    const years = to - from + 1;
    meta.textContent = "era C · " + SCENARIO_LABEL[state.scenario] + " · " +
      ind.label + " · " + from + "–" + to + " · median-based, agreement alongside";
    note.textContent = "computing events (frozen runs analysis)…";
    try {
      const [medianRows, agreeRows] = await Promise.all([
        DIE.Engine.ensemble({
          scenario: state.scenario, variable: state.variable,
          stat: "median", yearRange: [from, to],
        }),
        DIE.Engine.ensemble({
          scenario: state.scenario, variable: state.variable,
          stat: "agreement_moderate", yearRange: [from, to],
        }),
      ]);
      // group median rows per district, ordered by (year, month)
      const byDistrict = new Map();
      for (const r of medianRows) {
        let list = byDistrict.get(r.district_id);
        if (!list) byDistrict.set(r.district_id, (list = []));
        list.push(r);
      }
      const agreeSum = new Map();
      const agreeN = new Map();
      for (const r of agreeRows) {
        if (!Number.isFinite(r.value)) continue;
        agreeSum.set(r.district_id,
          (agreeSum.get(r.district_id) || 0) + r.value);
        agreeN.set(r.district_id, (agreeN.get(r.district_id) || 0) + 1);
      }
      const base = await ensureBaseline();
      const baseVar = base.variables && base.variables[state.variable];
      const rows = [];
      for (const [id, list] of byDistrict) {
        list.sort((a, b) => a.year - b.year || a.month - b.month);
        const values = list.map((r) => (Number.isFinite(r.value) ? r.value : NaN));
        const met = findEventMetrics(values, years);
        if (!met.valid_months) continue;
        const b = baseVar && baseVar.districts && baseVar.districts[id];
        const agreeMean = agreeN.get(id) ? agreeSum.get(id) / agreeN.get(id) : null;
        rows.push({
          id, met, b, agreeMean,
          baseName: (DIE.registry && DIE.registry.districts.get(id)) || null,
        });
      }
      const sortKey = $("projEventsMetric").value;
      for (const r of rows) {
        r.freqRatio = r.b && r.b.n_events > 0
          ? (r.met.events_per_year || 0) / r.b.events_per_year
          : null;
        r.durChange = r.b && r.b.mean_duration !== null &&
          r.met.mean_duration !== null
          ? r.met.mean_duration - r.b.mean_duration
          : null;
        r.sevRatio = r.b && r.b.total_severity > 0
          ? (r.met.total_severity / years) / (r.b.total_severity / 40)
          : null;
      }
      const sorters = {
        freq: (a, b2) => (b2.freqRatio || -1) - (a.freqRatio || -1),
        duration: (a, b2) => (b2.durChange || -99) - (a.durChange || -99),
        severity: (a, b2) => (b2.sevRatio || -1) - (a.sevRatio || -1),
      };
      rows.sort(sorters[sortKey] || sorters.freq);

      const fmt = (v, dp) => (Number.isFinite(v) ? v.toFixed(dp) : "—");
      tbody.innerHTML = rows.slice(0, EVENTS_ROW_LIMIT).map((r) => {
        const name = r.baseName ? r.baseName.name +
          " (" + r.baseName.state + ")" : r.id;
        return "<tr>" +
          "<td>" + esc(name) + "</td>" +
          '<td class="num">' +
          (r.b ? r.b.events_per_year.toFixed(2) : "—") + "</td>" +
          '<td class="num">' + fmt(r.met.events_per_year || 0, 2) + "</td>" +
          '<td class="num">' + fmt(r.freqRatio, 2) + "</td>" +
          '<td class="num">' +
          (r.b && r.b.mean_duration !== null ? r.b.mean_duration.toFixed(1) : "—") +
          " &#8594; " + fmt(r.met.mean_duration, 1) + "</td>" +
          '<td class="num">' + r.met.max_duration + "</td>" +
          '<td class="num">' + fmt(r.sevRatio, 2) + "</td>" +
          '<td class="num">' +
          (r.agreeMean === null ? "—" :
            Math.round(r.agreeMean * 8 * 10) / 10 + "/8") + "</td>" +
          '<td class="num">' + r.met.valid_months + "</td>" +
          "</tr>";
      }).join("");

      // national summary: medians across districts with data (robust, R10)
      const withFreq = rows.filter((r) => r.freqRatio !== null);
      const med = (arr) => {
        if (!arr.length) return null;
        const s = arr.slice().sort((a, b2) => a - b2);
        return s.length % 2 ? s[(s.length - 1) / 2]
          : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
      };
      const medFreq = med(withFreq.map((r) => r.freqRatio));
      const medDur = med(rows.filter((r) => r.durChange !== null)
        .map((r) => r.durChange));
      const medSev = med(rows.filter((r) => r.sevRatio !== null)
        .map((r) => r.sevRatio));
      const censored = rows.reduce((s, r) => s + r.met.n_censored, 0);
      note.innerHTML =
        "Top " + Math.min(EVENTS_ROW_LIMIT, rows.length) + " of " +
        rows.length + " districts with data (sorted by " +
        esc($("projEventsMetric").selectedOptions[0].textContent
          .replace(/^Sort by /i, "").toLowerCase()) +
        "). <strong>National median:</strong> frequency ratio " +
        fmt(medFreq, 2) + " ×, duration change " + fmt(medDur, 1) +
        " months, severity ratio " + fmt(medSev, 2) +
        " × vs the era-B 1981–2014 baseline (same frozen machinery, " +
        "threshold −1.0, min 3 months, no imputation; " + censored +
        " era-C events touch window edges — flagged censored, not dropped). " +
        "Computed on the <strong>ensemble median</strong> — not a single " +
        "realisation; the agreement column (mean models ≤ −1.0 across the " +
        "window) is the honest spread companion (X2). " +
        "A ratio is a comparison to the era-B baseline, <strong>not a " +
        "forecast</strong>. Baseline: " + esc(base.source) + ".";
    } catch (err) {
      console.warn("[projections] events failed:", err);
      tbody.innerHTML = "";
      note.textContent = "Events view unavailable: " + String(err && err.message || err);
    }
  }

  /* ---- wiring -------------------------------------------------------------- */

  function wire() {
    document.querySelectorAll('input[name="projScenario"]').forEach((r) => {
      r.addEventListener("change", () => {
        state.scenario = r.value;
        track("scenario", r.value);
        renderCheck();
        drawBand();
        renderMap();
        renderDivergence();
        renderEvents();
      });
    });
    $("projVariable").addEventListener("change", (e) => {
      // an assigned value with no matching option yields "" — keep the old
      // selection rather than leaving the state with an empty id
      if (!e.target.value) { e.target.value = state.variable; return; }
      state.variable = e.target.value;
      track("variable", e.target.value);
      renderCheck();
      drawBand();
      renderMap();
      renderEvents();
    });
    $("projStatistic").addEventListener("change", (e) => {
      if (!e.target.value) { e.target.value = state.statistic; return; }
      state.statistic = e.target.value;
      track("statistic", e.target.value);
      renderCheck();
      renderMap();   // the band chart always shows median + p25 + p75
    });
    $("projWindow").addEventListener("change", (e) => {
      state.window = e.target.value;
      track("window", e.target.value);
      $("projCustomYears").hidden = state.window !== "custom";
      renderCheck();
      drawBand();
      renderEvents();
    });
    const custom = () => {
      state.customFrom = clampYear($("projFromYear").value);
      state.customTo = clampYear($("projToYear").value);
      $("projFromYear").value = state.customFrom;
      $("projToYear").value = state.customTo;
      track("window_custom", state.customFrom + "-" + state.customTo);
      renderCheck();
      drawBand();
      renderEvents();
    };
    $("projFromYear").addEventListener("change", custom);
    $("projToYear").addEventListener("change", custom);
    $("projGeography").addEventListener("change", (e) => {
      state.geography = e.target.value;
      track("geography", e.target.value);
      updateGeoVisibility();
      drawBand();
      if (mapApi) {
        if (state.geography === "state") mapApi.fitRegion("state", state.stateSid);
        else if (state.geography === "district") mapApi.fitRegion("district", state.district);
        else mapApi.fitRegion(null, null);
      }
    });
    $("projDistrict").addEventListener("change", (e) => {
      state.district = e.target.value;
      track("district", e.target.value);
      drawBand();
      if (mapApi) mapApi.fitRegion("district", state.district);
    });
    $("projState").addEventListener("change", (e) => {
      state.stateSid = e.target.value;
      track("state", e.target.value);
      drawBand();
      if (mapApi) mapApi.fitRegion("state", state.stateSid);
    });
    $("projMapYear").addEventListener("change", (e) => {
      state.mapYear = Number(e.target.value);
      track("map_year", state.mapYear);
      renderMap();
    });
    $("projMapMonth").addEventListener("change", (e) => {
      state.mapMonth = Number(e.target.value);
      track("map_month", state.mapMonth);
      renderMap();
    });
    $("projDivYear").addEventListener("change", (e) => {
      state.divYear = Number(e.target.value);
      track("div_year", state.divYear);
      renderDivergence();
    });
    $("projDivMonth").addEventListener("change", (e) => {
      state.divMonth = Number(e.target.value);
      track("div_month", state.divMonth);
      renderDivergence();
    });
    $("projEventsMetric").addEventListener("change", (e) => {
      track("events_sort", e.target.value);
      // sorting is client-side over already-fetched rows — re-render cheaply
      renderEvents();
    });
    $("projReloadBtn").addEventListener("click", () => {
      if (DIE.Engine && DIE.Engine.reset) {
        // a failed catalog promise is not cached by the engine service; the
        // reset hook also clears any stale query cache for a clean retry
        DIE.Engine.reset();
      }
      init();
    });
  }

  function showError(err) {
    $("projStatusMeta").textContent = "catalog unavailable";
    $("projStatusEra").textContent = "catalog.json could not be loaded";
    $("projCheckTable").querySelector("tbody").innerHTML = "";
    $("projCheckNote").textContent =
      "The catalog could not be fetched (" + String(err && err.message || err) +
      "). Serving over HTTP with server.py is required.";
    $("projReloadBtn").hidden = false;
  }

  /* ---- init / render -------------------------------------------------------- */

  async function init() {
    $("projReloadBtn").hidden = true;
    if (!Proj.ready) {
      wire();
      Proj.ready = true;
    }
    renderBanner();
    try {
      catalog = await getCatalog();
    } catch (err) {
      console.warn("[projections] catalog load failed:", err);
      showError(err);
      return;
    }
    if (!catalog.eras || !catalog.eras.projections) {
      showError(new Error("no projections era block in catalog"));
      return;
    }
    renderStatus();
    syncRecordRangeUI();
    renderVariableOptions();
    syncStatisticOptions();
    renderGeoPickers();
    renderCheck();
    await Promise.allSettled([
      drawBand(), renderMap(), renderRanking(),
      renderDivergence(), renderEvents(),
    ]);
  }

  /** Size hooks for app.js: recalc the Leaflet container after tab switches
   *  or window resizes (re-querying is near-free via the engine query cache). */
  function mapSize() {
    if (mapApi) mapApi.invalidateSize();
    if (divApi) divApi.invalidateSize();
  }
  function invalidate() {
    if (!Proj.ready || !catalog) return;
    renderGeoPickers();
    mapSize();
    drawBand();
    renderMap();
    renderDivergence();
    renderEvents();
  }

  /** Test hook (pattern: Engine.reset): read-only view of the live map frame
   *  so verification can recompute expected colours without touching state. */
  function snapshot() {
    return {
      mapApi,                       // choropleth api (map, layerById, …)
      values: lastMapValues,        // Map district_id -> value (current frame)
      dirN: lastDirN,               // Map district_id -> dir_agreement_n
      stat: lastMapStat,
      variable: lastMapVar,
      divApi,                       // divergence choropleth api
      divValues,                    // Map district_id -> {spi, spei, d}
    };
  }

  DIE.Projections = { init, state, invalidate, mapSize, snapshot };
})();
