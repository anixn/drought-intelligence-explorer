/* ---------------------------------------------------------------------------
 * DIE v2.0 — Era A vs Era B cross-validation (#crossval, task M6.6).
 *
 * The credibility surface: two independent drought records over the same
 * 1981–2014 window, compared — never averaged into one series, never spliced
 * (R2). Era A is the Drought Atlas reconstruction (station-based SPEI); era B
 * is the Gridded Multi-Source Product (CHIRPS precipitation / ERA5-Land PET).
 * Differences are expected and ARE the content (docs/v2/03 section 6).
 *
 * Reads the built product only (validation-studies/crossval/01_build_overlap.py):
 *   per_district — 718 districts x SPEI-1/SPEI-12 metrics (map + table source)
 *   monthly      — area-weighted national agreement series (chart)
 * The street-level overlap file is not fetched here (7.7 MB); it is the
 * download/evidence product.
 *
 * Metrics, all with their sample size:
 *   r                  Pearson correlation of the two district series
 *   bias               mean(era B - era A) in z units
 *   rmsd               root-mean-square difference
 *   state_agree        share of months where both agree on drought (<= -1.0)
 *   both_drought       share of months where both flag drought (co-occurrence)
 *   class_exact/near   same McKee class / within one class
 * ------------------------------------------------------------------------- */
(function () {
  "use strict";

  const DIE = (window.DIE = window.DIE || {});
  const $ = (id) => document.getElementById(id);

  const CV = { ready: false };
  const state = { variable: "spei_01", metric: "bias" };

  const VAR_LABEL = {
    spei_01: "SPEI-1 (monthly)",
    spei_12: "SPEI-12 (annual accumulation)",
  };
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  /* Diverging ramp for bias: negative = era B drier than era A (drought
   * colours), positive = era B wetter (blue). Sequential warm ramp for the
   * agreement metrics (darker = closer agreement). Chrome tokens only; the
   * published class palette is untouched (R1). */
  const DIV_COLORS = ["#7A3E14", "#C9955C", "#E9EDF2", "#9DB8D4", "#2F5F9E"];
  const SEQ_COLORS = ["#F3ECDF", "#DDCBAE", "#C3A377", "#9C713F", "#6B4523"];

  const METRICS = {
    bias: {
      short: "Bias (era B − era A)",
      bins: [-0.5, -0.2, 0.2, 0.5],
      colors: DIV_COLORS,
      labels: ["≤ −0.5 z (era B much drier)", "−0.5 to −0.2 z",
        "−0.2 to +0.2 z (little bias)", "+0.2 to +0.5 z",
        "> +0.5 z (era B much wetter)"],
      head: "Mean difference era B − era A per district, 1981–2014 (z units)",
      value: (r) => r.bias,
      worst: (r) => Math.abs(r.bias),
      note: "The divergence map: where the CHIRPS/ERA5-Land record sits above " +
        "or below the station-based Atlas reconstruction. A systematic offset " +
        "is a property of the two input chains (precipitation source, PET " +
        "method, fitting window), not an error in either record.",
    },
    r: {
      short: "Correlation r",
      bins: [0.5, 0.6, 0.7, 0.8],
      colors: SEQ_COLORS,
      labels: ["< 0.5", "0.5–0.6", "0.6–0.7", "0.7–0.8", "≥ 0.8"],
      head: "Pearson r between the two district series, 1981–2014",
      value: (r) => r.r,
      worst: (r) => (Number.isFinite(r.r) ? r.r : 2),
      note: "How closely the two records move together month to month. " +
        "Correlation says nothing about level (see the bias map) and is not " +
        "causation (R9). Districts with fewer than 12 paired months report " +
        "no r and stay grey.",
    },
    state_agree: {
      short: "Drought-state agreement",
      bins: [0.7, 0.8, 0.85, 0.9],
      colors: SEQ_COLORS,
      labels: ["< 70 %", "70–80 %", "80–85 %", "85–90 %", "≥ 90 %"],
      head: "Share of months where both records agree on drought state " +
        "(≤ −1.0 or > −1.0), 1981–2014",
      value: (r) => r.state_agree,
      worst: (r) => r.state_agree,
      note: "Operational agreement: the two records place the district on " +
        "the same side of the v1.0 drought truncation (−1.0 z) in this share " +
        "of matched months. This is the number to quote when the question is " +
        "\"would both records have called a drought?\".",
    },
    class_near: {
      short: "Severity class (within one)",
      bins: [0.6, 0.7, 0.8, 0.9],
      colors: SEQ_COLORS,
      labels: ["< 60 %", "60–70 %", "70–80 %", "80–90 %", "≥ 90 %"],
      head: "Share of months in the same or an adjacent McKee class, " +
        "1981–2014",
      value: (r) => r.class_near,
      worst: (r) => r.class_near,
      note: "Exact nine-class agreement is dominated by the near-normal bin " +
        "and is easy to misread, so the map shows within-one-class agreement. " +
        "The exact-class share is in the table and the CSV.",
    },
    rmsd: {
      short: "RMSD",
      bins: [0.5, 0.65, 0.8, 1.0],
      colors: SEQ_COLORS,
      labels: ["≤ 0.5 z", "0.5–0.65 z", "0.65–0.8 z", "0.8–1.0 z", "> 1.0 z"],
      head: "Root-mean-square difference between the two series, 1981–2014 (z)",
      value: (r) => r.rmsd,
      worst: (r) => r.rmsd,
      note: "Magnitude of disagreement including both bias and scatter; " +
        "compare with the median across districts reported above.",
    },
  };

  let catalog = null;
  let mapApi = null;
  let rowsCache = null;
  let monthlyCache = null;
  let seq = 0;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }
  function track(control, value) {
    if (DIE.Telemetry) {
      try { DIE.Telemetry.track("crossval_control", { control, value }); } catch (e) {}
    }
  }
  function getCatalog() {
    if (DIE.Engine && DIE.Engine.ensureCatalog) return DIE.Engine.ensureCatalog();
    return fetch("data/parquet/catalog.json", { cache: "no-store" })
      .then((r) => { if (!r.ok) throw new Error("catalog HTTP " + r.status); return r.json(); });
  }
  function block() {
    return catalog && catalog.crossval;
  }
  function fmt(v, dp, suffix) {
    return Number.isFinite(v) ? v.toFixed(dp) + (suffix || "") : "—";
  }
  function pct(v) {
    return Number.isFinite(v) ? (v * 100).toFixed(1) + "%" : "—";
  }

  /* ---- controls ---------------------------------------------------------- */
  function wire() {
    $("cvVariable").addEventListener("change", (e) => {
      state.variable = e.target.value;
      track("variable", state.variable);
      renderAll();
    });
    $("cvMetric").addEventListener("change", (e) => {
      state.metric = e.target.value;
      track("metric", state.metric);
      renderAll();
    });
    $("cvCsvBtn").addEventListener("click", exportCsv);
  }

  /* ---- banner ------------------------------------------------------------ */
  function renderBanner() {
    const el = $("cvBanner");
    const cv = block();
    const w = cv && cv.window ? cv.window : [1981, 2014];
    el.innerHTML =
      "<b>Two independent records, compared — not merged.</b> Era A is the " +
      "Drought Atlas reconstruction (station-based SPEI); era B is the " +
      "Gridded Multi-Source Product (CHIRPS precipitation with ERA5-Land " +
      "PET). Both are standardised separately and keyed to different fitting " +
      "baselines, so a difference here is <b>expected and is the content</b>. " +
      "The panel covers <b>" + w[0] + "–" + w[1] + "</b> (register D6, the " +
      "GCM-native comparison window); the full 1981–2025 overlap is a " +
      "sensitivity variant, not part of this build. Nothing is spliced into " +
      "one series (R2).";
  }

  /* ---- data -------------------------------------------------------------- */
  async function load() {
    if (!DIE.Engine || !DIE.Engine.crossval) {
      throw new Error("the DuckDB engine is unavailable in this session");
    }
    const [per, mon] = await Promise.all([
      DIE.Engine.crossval({ variable: state.variable, part: "per_district" }),
      DIE.Engine.crossval({ variable: state.variable, part: "monthly" }),
    ]);
    const reg = DIE.registry && DIE.registry.districts;
    return {
      rows: per.map((r) => {
        const d = reg ? reg.get(r.district_id) : null;
        return Object.assign({}, r, {
          name: d ? d.name : r.district_id,
          stateName: d ? d.state : "—",
          area: d && Number.isFinite(d.area) ? d.area : NaN,
        });
      }),
      monthly: mon,
    };
  }

  /* ---- statistics -------------------------------------------------------- */
  function renderStats(rows, monthly) {
    const areaOf = (r) => (Number.isFinite(r.area) ? r.area : 0);
    const area = rows.reduce((s, r) => s + areaOf(r), 0);
    const w = (fn) => (area
      ? rows.reduce((s, r) => s + areaOf(r) * fn(r), 0) / area : NaN);
    const rs = rows.filter((r) => Number.isFinite(r.r)).map((r) => r.r)
      .sort((a, b) => a - b);
    const medianR = rs.length
      ? (rs.length % 2 ? rs[(rs.length - 1) / 2]
        : (rs[rs.length / 2 - 1] + rs[rs.length / 2]) / 2) : NaN;
    const rms = rows.map((r) => r.rmsd).filter(Number.isFinite)
      .sort((a, b) => a - b);
    const medianRmsd = rms.length
      ? (rms.length % 2 ? rms[(rms.length - 1) / 2]
        : (rms[rms.length / 2 - 1] + rms[rms.length / 2]) / 2) : NaN;

    $("cvDistricts").textContent = String(rows.length);
    $("cvMonths").textContent = rows.reduce((s, r) => s + r.n, 0)
      .toLocaleString("en-US");
    $("cvMedianR").textContent = fmt(medianR, 3);
    $("cvBias").textContent = fmt(w((r) => r.bias), 3, " z");
    $("cvRmsd").textContent = fmt(medianRmsd, 3, " z");
    $("cvState").textContent = pct(w((r) => r.state_agree));
    $("cvClass").textContent = pct(w((r) => r.class_near));
    $("cvBoth").textContent = pct(w((r) => r.both_drought));
    $("cvStatMeta").textContent = VAR_LABEL[state.variable] + " · 1981–2014 · " +
      "district metrics; area-weighted means across districts";
    const m = monthly.filter((r) => Number.isFinite(r.n_districts));
    $("cvStatNote").textContent =
      "n = " + rows.length + " districts with matched data (" +
      rows.reduce((s, r) => s + r.n, 0).toLocaleString("en-US") +
      " district-months; " + (m.length ? m.length : 0) + " calendar months. " +
      "Median r is the unweighted median across districts; the area-weighted " +
      "figures use the v1.0 LAEA district areas. Both-drought is the share " +
      "of months where BOTH records flag ≤ −1.0 — it is co-occurrence, not " +
      "agreement. Missing pairs are absent, never imputed (R10).";
  }

  /* ---- map --------------------------------------------------------------- */
  function metricColor(r, m) {
    const v = m.value(r);
    if (!Number.isFinite(v)) return null;
    const b = m.bins;
    if (v <= b[0]) return m.colors[0];
    if (v <= b[1]) return m.colors[1];
    if (v <= b[2]) return m.colors[2];
    if (v < b[3]) return m.colors[3];
    return m.colors[4];
  }

  function renderMap(rows) {
    const m = METRICS[state.metric];
    const meta = $("cvMapMeta");
    const note = $("cvMapNote");
    try {
      if (!mapApi) {
        mapApi = DIE.MapView.createChoropleth($("cvMap"), { tooltip: false });
      }
      const byId = new Map(rows.map((r) => [r.district_id, r]));
      mapApi.applyData(null, 0, null, null,
        () => null,
        (id) => {
          const r = byId.get(id);
          return r ? (metricColor(r, m) || "#E8E1D2") : "#E8E1D2";
        });
      meta.textContent = VAR_LABEL[state.variable] + " · " + m.short +
        " · 1981–2014";
      $("cvLegend").innerHTML =
        '<span class="legend-head">' + esc(m.head) + "</span>" +
        m.labels.map((lab, i) =>
          '<span class="legend-row"><span style="display:inline-block;' +
          "width:12px;height:12px;border-radius:2px;background:" +
          m.colors[i] + '"></span><span class="legend-range">' + esc(lab) +
          "</span></span>").join("");
      const shown = rows.filter((r) => Number.isFinite(m.value(r))).length;
      note.textContent = m.note + " n = " + shown + " districts with a " +
        "calculable value; the six island districts have no Atlas grid cells " +
        "and stay grey, never imputed (R10). Click any district to zoom it " +
        "into the frame.";
    } catch (err) {
      console.warn("[crossval] map failed:", err);
      note.textContent = "Map unavailable: " + String(err && err.message || err);
    }
  }

  /* ---- table ------------------------------------------------------------- */
  function renderTable(rows) {
    const m = METRICS[state.metric];
    const tbody = $("cvTable").querySelector("tbody");
    const sorted = rows.slice().sort((a, b) => {
      const av = m.worst(a), bv = m.worst(b);
      const aOk = Number.isFinite(av), bOk = Number.isFinite(bv);
      if (!aOk && !bOk) return a.name.localeCompare(b.name);
      if (!aOk) return 1;
      if (!bOk) return -1;
      if (state.metric === "bias" || state.metric === "rmsd") return bv - av;
      return av - bv;
    });
    const top = sorted.slice(0, 30);
    tbody.innerHTML = top.map((r) => (
      "<tr><td>" + esc(r.name) + "</td><td>" + esc(r.stateName) + "</td>" +
      '<td class="num">' + r.n + "</td>" +
      '<td class="num">' + fmt(r.r, 3) + "</td>" +
      '<td class="num">' + fmt(r.bias, 3) + "</td>" +
      '<td class="num">' + fmt(r.sd_diff, 3) + "</td>" +
      '<td class="num">' + pct(r.state_agree) + "</td>" +
      '<td class="num">' + pct(r.class_exact) + "</td>" +
      '<td class="num">' + pct(r.class_near) + "</td></tr>"
    )).join("");
    $("cvTableMeta").textContent = "worst " + top.length + " of " +
      rows.length + " districts · sorted by " +
      (state.metric === "bias" ? "|bias|" : m.short);
    $("cvTableNote").textContent =
      "Worst-first ordering, not a ranking of district performance. Seam SD is " +
      "the per-district population SD of the era B − era A difference over " +
      "1981–2014 — the X7 seam uncertainty quoted in projection tooltips for " +
      "SPEI-12. It measures historical disagreement between the two records, " +
      "not a confidence interval. Exact class agreement is shown for " +
      "transparency; it is low by construction (nine classes, a dominant " +
      "near-normal bin) and the within-one-class column is the fairer summary. " +
      "Full 718-district table in the CSV.";
  }

  /* ---- monthly agreement chart ------------------------------------------ */
  function renderMonthly(monthly) {
    const el = $("cvMonthlyChart");
    const note = $("cvMonthlyNote");
    if (!monthly.length) {
      note.textContent = "No monthly series available.";
      return;
    }
    const x = monthly.map((r) => r.date);
    const y = monthly.map((r) => r.state_agree * 100);
    const lo = Math.min.apply(null, y), hi = Math.max.apply(null, y);
    const avg = y.reduce((s, v) => s + v, 0) / y.length;
    note.textContent =
      "Area-weighted drought-state agreement per month, 1981–2014: time-mean " +
      avg.toFixed(1) + "%, range " + lo.toFixed(1) + "–" + hi.toFixed(1) +
      "%. Each month's value is the share of the matched district area where " +
      "both records agree on the drought state, so a month with fewer matched " +
      "districts weights only the area that has both records. Months where the " +
      "two records disagree most are the months to read alongside the district " +
      "table; the series is evidence, not a correction.";
    el.setAttribute("aria-label",
      "Line chart of monthly drought-state agreement between era A and era B, " +
      "1981 to 2014. Mean " + avg.toFixed(1) + " percent, range " +
      lo.toFixed(1) + " to " + hi.toFixed(1) + " percent.");
    if (typeof Plotly === "undefined") {
      note.textContent += " Chart library unavailable; the series is in the CSV.";
      return;
    }
    Plotly.react(el, [{
      x: x, y: y, type: "scatter", mode: "lines",
      line: { color: "#6B2B1F", width: 1.5 },
      hovertemplate: "%{x}<br>agreement %{y:.1f}%<extra></extra>",
    }], {
      margin: { l: 46, r: 12, t: 10, b: 30 },
      height: 230,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: "Inter, sans-serif", size: 11, color: "#5B5145" },
      xaxis: { showgrid: false, linecolor: "#CFC2A8", ticks: "outside",
        tickfont: { size: 10 } },
      yaxis: { title: { text: "% of matched area", font: { size: 10 } },
        range: [Math.max(0, Math.min(50, lo - 12)), 100],
        gridcolor: "#E1D7C3", zeroline: false },
      shapes: [{
        type: "line", xref: "paper", x0: 0, x1: 1, y0: avg, y1: avg,
        line: { color: "#B08947", width: 1, dash: "dot" },
      }],
      showlegend: false,
      hovermode: "x unified",
    }, { displayModeBar: false, responsive: true });
  }

  /* ---- render orchestration --------------------------------------------- */
  async function renderAll() {
    const mySeq = ++seq;
    const meta = $("cvMapMeta");
    const note = $("cvMapNote");
    if (!DIE.Engine) return;
    if (!block()) {
      $("cvBanner").textContent =
        "The cross-validation product is not built in this checkout; this " +
        "workspace renders nothing rather than a placeholder (R3).";
      return;
    }
    meta.textContent = "querying the cross-validation store…";
    note.textContent = "loading…";
    try {
      const out = await load();
      if (mySeq !== seq) return;
      rowsCache = out.rows;
      monthlyCache = out.monthly;
      renderStats(rowsCache, monthlyCache);
      renderMap(rowsCache);
      renderTable(rowsCache);
      renderMonthly(monthlyCache);
    } catch (err) {
      if (mySeq !== seq) return;
      console.warn("[crossval] render failed:", err);
      meta.textContent = "unavailable";
      note.textContent = "Cross-validation render unavailable: " +
        String(err && err.message || err) + " — no placeholder is shown (R3).";
    }
  }

  /* ---- CSV export -------------------------------------------------------- */
  function exportCsv() {
    if (!rowsCache || !rowsCache.length) return;
    const m = METRICS[state.metric];
    const L = [];
    if (DIE.App && DIE.App.citationLines) {
      DIE.App.citationLines().forEach((l) => L.push(l));
    }
    L.push("# panel: #crossval — era A vs era B agreement");
    L.push("# indicator: " + state.variable + " (" +
      VAR_LABEL[state.variable] + ")");
    L.push("# window: 1981-2014 (register D6 comparison window)");
    L.push("# era A: Drought Atlas of India reconstruction (station-based SPEI)");
    L.push("# era B: Gridded Multi-Source Product (CHIRPS precipitation, ERA5-Land PET)");
    L.push("# drought threshold: -1.0 z (v1.0 moderate-class upper bound); class table from data/metadata.json");
    L.push("# seam SD (sd_diff): per-district population SD of era B - era A over 1981-2014; the X7 seam uncertainty, not a confidence interval");
    L.push("# built by validation-studies/crossval/01_build_overlap.py; per-district file");
    L.push("# areas: LAEA km2 (v1.0 registry); missing pairs are absent, never imputed (R10)");
    L.push("# map statistic at export time: " + m.short);
    L.push("district_id,district_name,state,area_km2,n_months,n_window,coverage," +
      "r,bias,rmsd,sd_diff,state_agree,both_drought,severe_agree,class_exact," +
      "class_near,era_a_drought_share,era_b_drought_share,era_a_mean,era_b_mean");
    const cell = (v, dp) => (Number.isFinite(v) ? v.toFixed(dp) : "");
    for (const r of rowsCache) {
      L.push([
        r.district_id, '"' + String(r.name).replace(/"/g, '""') + '"',
        '"' + String(r.stateName).replace(/"/g, '""') + '"',
        Number.isFinite(r.area) ? r.area.toFixed(2) : "",
        r.n, r.n_window, cell(r.coverage, 4), cell(r.r, 4), cell(r.bias, 4),
        cell(r.rmsd, 4), cell(r.sd_diff, 4), cell(r.state_agree, 4),
        cell(r.both_drought, 4),
        cell(r.severe_agree, 4), cell(r.class_exact, 4), cell(r.class_near, 4),
        cell(r.a_drought_share, 4), cell(r.b_drought_share, 4),
        cell(r.a_mean, 4), cell(r.b_mean, 4),
      ].join(","));
    }
    const blob = new Blob([L.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "die-crossval_1981-2014_" + state.variable + ".csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    if (DIE.Telemetry) {
      try { DIE.Telemetry.track("crossval_export", { variable: state.variable }); } catch (e) {}
    }
  }

  /* ---- init / invalidate -------------------------------------------------- */
  async function doInit() {
    if (!CV.ready) {
      wire();
      CV.ready = true;
    }
    if (!catalog) {
      try {
        catalog = await getCatalog();
      } catch (err) {
        console.warn("[crossval] catalog load failed:", err);
        $("cvBanner").textContent =
          "Data contract unavailable — this workspace shows committed " +
          "catalog facts only (no synthetic placeholders, R3). Error: " +
          String(err && err.message || err);
        return;
      }
    }
    if (!block()) {
      $("cvBanner").textContent =
        "The cross-validation product is not built in this checkout; this " +
        "workspace renders nothing rather than a placeholder (R3).";
      return;
    }
    renderBanner();
    await renderAll();
  }

  /* init() re-renders on tab entry; whenReady() is the first-init promise the
   * permalink layer awaits before restoring controls (M10.4). */
  let bootReady = null;
  function init() {
    const p = doInit();
    if (!bootReady) bootReady = p;
    return p;
  }
  function whenReady() {
    if (!bootReady) bootReady = doInit();
    return bootReady;
  }

  function invalidate() {
    if (mapApi) mapApi.invalidateSize();
    const el = $("cvMonthlyChart");
    if (el && typeof Plotly !== "undefined" && el.data) {
      try { Plotly.Plots.resize(el); } catch (e) {}
    }
  }

  /* ---- permalink state (M10.4) ------------------------------------------ */
  function permalinkState() {
    return { cVariable: state.variable, cMetric: state.metric };
  }

  async function applyPermalink(p) {
    await whenReady();                 // never race the first render
    const v = p.get ? p.get("cVariable") : p.cVariable;
    const m = p.get ? p.get("cMetric") : p.cMetric;
    if (v && VAR_LABEL[v]) state.variable = v;
    if (m && METRICS[m]) state.metric = m;
    const vSel = $("cvVariable"), mSel = $("cvMetric");
    if (vSel) vSel.value = state.variable;
    if (mSel) mSel.value = state.metric;
    await renderAll();
  }

  DIE.CrossvalView = { init, whenReady, invalidate, permalinkState, applyPermalink };
})();
