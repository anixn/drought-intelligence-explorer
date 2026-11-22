/* ---------------------------------------------------------------------------
 * DIE v2.0 — District profile (#/district/<id>, task M10.6).
 *
 * One district, read as a page: the headline answer for the selected month,
 * all ten era-B indicators in one query, the long-term trend, the frozen
 * drought-event catalogue, and the era context (B record, A overlap/seam,
 * C projection link). Era labels sit on every block; missing values are shown
 * as no-data and never imputed (R10).
 *
 * The route is the dedicated path #/district/<id>; Permalink.parse/build
 * understands it, so Copy link and the shared study context work unchanged.
 * ------------------------------------------------------------------------- */
(function () {
  "use strict";

  const DIE = (window.DIE = window.DIE || {});
  const $ = (id) => document.getElementById(id);

  const DP = { ready: false };
  let seq = 0;
  let wired = false;
  let crossvalCache = new Map();   // district id -> Promise<row|null>

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const SEASON_LABEL = {
    all: "all months", cold: "cold season", pre_monsoon: "pre-monsoon",
    sw_monsoon: "south-west monsoon", post_monsoon: "post-monsoon",
  };

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }
  function pct(v, dp) {
    return Number.isFinite(v) ? (v * 100).toFixed(dp === undefined ? 0 : dp) + "%" : "—";
  }
  function num(v, dp) {
    return Number.isFinite(v) ? v.toFixed(dp === undefined ? 2 : dp) : "—";
  }
  function signed(v, dp) {
    return Number.isFinite(v) ? (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(dp === undefined ? 2 : dp) : "—";
  }
  function track(control, value) {
    if (DIE.Telemetry) {
      try { DIE.Telemetry.track("district_profile", { control, value }); } catch (e) {}
    }
  }
  function metaVarId(v) { return String(v).replace(/_0(\d)$/, "_$1"); }

  function district() {
    const id = DIE.state && DIE.state.districtId;
    return id && DIE.registry ? DIE.registry.districts.get(id) : null;
  }
  function activeDataset() {
    return DIE.datasets && DIE.datasets.get(DIE.state.indicator);
  }
  function dateLabel(ym) {
    return ym && DIE.dates ? DIE.dates.label(ym) : "—";
  }

  /* ---- one district, ten indicators (engine) ---------------------------- */
  async function renderStrip(d, ym, mySeq) {
    const el = $("dpStrip");
    const note = $("dpStripNote");
    if (!el) return;
    let byVar = new Map();
    let viaEngine = false;
    if (DIE.Engine && DIE.Engine.observedAt) {
      try {
        const rows = await DIE.Engine.observedAt({ district: d.id, date: ym });
        rows.forEach((r) => byVar.set(metaVarId(r.variable), r.value));
        viaEngine = true;
      } catch (err) {
        console.warn("[district] indicator strip query failed:", err);
      }
    }
    if (mySeq !== seq) return;

    el.innerHTML = DIE.meta.indicators.map((ind) => {
      let v = byVar.get(ind.id);
      if (!viaEngine) {
        // Honest fallback: only indicators already parsed can be shown.
        const ds = DIE.datasets.get(ind.id);
        if (ds && ds.districtIndex.has(d.id)) {
          const idx = ds.dateIndex.get(ym);
          const row = ds.values[ds.districtIndex.get(d.id)];
          v = idx !== undefined && row ? row[idx] : undefined;
        } else {
          v = undefined;
        }
      }
      const finite = Number.isFinite(v);
      const c = finite ? DIE.classify(v, ind) : null;
      const chip = c
        ? '<span class="dp-class" style="background:' + c.color + ";color:" +
          DIE.inkOn(c.color) + '">' + esc(c.label) + "</span>"
        : '<span class="dp-class is-nodata">no data</span>';
      return '<button type="button" class="dp-chip" data-ind="' + esc(ind.id) +
        '" aria-pressed="' + String(ind.id === DIE.state.indicator) +
        '" title="Make ' + esc(ind.label) + ' the active indicator">' +
        '<span class="dp-name">' + esc(ind.label) + "</span>" +
        '<span class="dp-val">' +
        (finite ? esc(DIE.fmt.val(v, ind)) + " " + esc(ind.units) : "—") +
        "</span>" + chip + "</button>";
    }).join("");

    el.querySelectorAll("button[data-ind]").forEach((b) => {
      b.addEventListener("click", () => {
        const id = b.getAttribute("data-ind");
        track("indicator", id);
        DIE.Filters.set({ indicator: id });
      });
    });

    $("dpStripMeta").textContent = "Era B · " + dateLabel(ym) +
      (viaEngine ? " · one Parquet query for ten indicators" : " · parsed indicators only");
    note.textContent = viaEngine
      ? "Values are the same standardised indices as the maps (era B, reference " +
        DIE.meta.reference_period + "). Click any indicator to make it the active " +
        "indicator across the dashboard. Missing values are absent, never imputed (R10)."
      : "The DuckDB engine is unavailable in this session, so only indicators already " +
        "parsed can be shown; no values are fabricated (R3).";
  }

  /* ---- headline answer -------------------------------------------------- */
  function renderHeadline(d, ds, stats) {
    const ym = DIE.Filters.dateYm();
    const ind = ds.indicator;
    const i = ds.districtIndex.get(d.id);
    const row = i === undefined ? null : ds.values[i];
    const j = ds.dateIndex.get(ym);
    const v = row && j !== undefined ? row[j] : NaN;

    // Rank of the selected month within the district's full valid record.
    let n = 0, asDry = 0;
    if (row) {
      for (const x of row) {
        if (!Number.isFinite(x)) continue;
        n += 1;
        if (Number.isFinite(v) && x <= v) asDry += 1;
      }
    }
    const c = Number.isFinite(v) ? DIE.classify(v, ind) : null;
    const parts = [];
    if (!Number.isFinite(v)) {
      parts.push("In <b>" + esc(dateLabel(ym)) + "</b> this indicator has no value " +
        "for <b>" + esc(d.name) + "</b> — missing values are never imputed (R10).");
    } else {
      parts.push("In <b>" + esc(dateLabel(ym)) + "</b>, <b>" + esc(d.name) +
        "</b> (" + esc(d.state) + ") was in <b>" + esc(c ? c.label : "an unclassified state") +
        "</b> for " + esc(ind.label) + " (<b>" + esc(DIE.fmt.val(v, ind)) + " " +
        esc(ind.units) + "</b>).");
      if (n) {
        if (asDry === 0) {
          parts.push("No other month in its " + n + " valid months was as dry or drier.");
        } else {
          parts.push(asDry + " of its " + n + " valid months (" +
            pct(asDry / n, 0) + ") were as dry or drier.");
        }
      }
      if (stats && Number.isFinite(stats.droughtPct)) {
        parts.push(num(stats.droughtPct, 0) + "% of months in the analysis period were " +
          "at or below the drought threshold.");
      }
    }
    $("dpHeadline").innerHTML = parts.join(" ");

    $("dpTitle").textContent = d.name;
    $("dpSub").textContent = d.state + " · " + ind.label + " · " +
      dateLabel(ym) + " · era B";
    $("dpReceipts").textContent =
      "Era B · Gridded Multi-Source Product · record " +
      (ds.availableFrom || DIE.meta.period.start) + "–" +
      (ds.availableTo || DIE.meta.period.end) +
      " · reference " + DIE.meta.reference_period +
      " · " + (stats ? stats.validMonths + " valid months" : "no valid months") +
      " · area " + DIE.fmt.int.format(Math.round(d.area)) + " km²" +
      " · district id " + d.id +
      " · analysis " + DIE.state.period.from + "–" + DIE.state.period.to +
      " (" + (SEASON_LABEL[DIE.state.period.season] || DIE.state.period.season) + ")" +
      " · ";
    $("dpReceipts").insertAdjacentHTML("beforeend",
      '<a class="ev-how" href="#data/k-methodology/method-trends">How this page is made →</a>');
  }

  /* ---- trend ------------------------------------------------------------ */
  function renderTrend(d, ds) {
    const period = DIE.state.period;
    const ts = DIE.Analytics.trendSeries(ds, [d.id], period,
      { granularity: "annual", season: period.season });
    const vals = [];
    const xs = [];
    ts.values.forEach((v, k) => { if (Number.isFinite(v)) { vals.push(v); xs.push(k); } });

    let sen = null, mk = null;
    if (vals.length >= 4) {
      sen = DIE.Stats.senSlope(vals, 0.10);
      mk = DIE.Stats.mannKendall(vals, sen.slope);
      if (sen && Number.isFinite(sen.slope)) {
        const m = DIE.Stats.mean(vals);
        sen.intercept = m - sen.slope * xs[Math.floor(xs.length / 2)];
      }
    }

    $("dpTrendMeta").textContent = ds.indicator.label + " · annual means · " +
      period.from + "–" + period.to +
      (period.season === "all" ? "" : " · " + (SEASON_LABEL[period.season] || period.season));

    const stats = $("dpTrendStats");
    if (!sen || !Number.isFinite(sen.slope)) {
      stats.innerHTML = '<div><div class="k">Trend test</div><div class="v">' +
        "not calculable</div></div>" +
        '<div><div class="k">Valid years</div><div class="v">' + vals.length + "</div></div>";
    } else {
      const dir = sen.slope < 0 ? "drying" : "wetting";
      const sig = mk && Number.isFinite(mk.p) && mk.p < 0.05;
      stats.innerHTML =
        '<div><div class="k">Sen slope</div><div class="v">' + signed(sen.slope, 3) +
          " " + esc(ds.indicator.units) + "/yr</div></div>" +
        '<div><div class="k">90% CI</div><div class="v">' + signed(sen.ci[0], 3) + " to " +
          signed(sen.ci[1], 3) + "</div></div>" +
        '<div><div class="k">Mann–Kendall p</div><div class="v">' +
          (mk && Number.isFinite(mk.p) ? (mk.p < 0.001 ? "<0.001" : mk.p.toFixed(3)) : "—") +
          "</div></div>" +
        '<div><div class="k">Direction</div><div class="v">' + dir +
          (sig ? " (significant, 5%)" : " (not significant at 5%)") + "</div></div>" +
        '<div><div class="k">Valid years</div><div class="v">' + vals.length + "</div></div>" +
        '<div><div class="k">Autocorrelation</div><div class="v">' +
          (mk && mk.hr && mk.hr.applied
            ? "Hamed–Rao applied (effective n = " + mk.hr.nEff.toFixed(1) + ")"
            : "none significant") + "</div></div>";
    }

    const chartEl = $("dpTrendChart");
    if (chartEl) {
      if (window.Plotly && DIE.Charts && DIE.Charts.trendChart) {
        try {
          DIE.Charts.trendChart(chartEl, {
            keys: ts.keys, values: ts.values, granularity: "annual",
            indicator: ds.indicator, label: d.name, sen,
          });
        } catch (err) {
          console.warn("[district] trend chart failed:", err);
          chartEl.textContent = "Chart unavailable; the statistics are shown below.";
        }
      } else {
        chartEl.textContent = "Chart library unavailable; the statistics are shown below.";
      }
      chartEl.setAttribute("aria-label", "Annual " + ds.indicator.label +
        " series for " + d.name + ", " + period.from + " to " + period.to +
        (sen && Number.isFinite(sen.slope)
          ? ", Sen slope " + sen.slope.toFixed(3) + " " + ds.indicator.units + " per year"
          : ", trend not calculable"));
    }

    $("dpTrendFoot").textContent =
      "Non-parametric Mann–Kendall test with tie-corrected variance and Sen slope " +
      "(median pairwise slope, rank-based 90% CI). Hamed–Rao variance correction is " +
      "applied when significant serial autocorrelation exists. Input: annual means over " +
      "the shared analysis period" +
      (period.season === "all" ? "" : " restricted to " + (SEASON_LABEL[period.season] || period.season)) +
      "; missing months are excluded, never imputed (R10).";
  }

  /* ---- events ----------------------------------------------------------- */
  function renderEvents(d, ds, stats) {
    const tbody = $("dpEventTable").querySelector("tbody");
    const events = stats && stats.events ? stats.events.slice() : [];
    events.sort((a, b) => (a.startDate < b.startDate ? 1 : a.startDate > b.startDate ? -1 : 0));
    const shown = events.slice(0, 8);
    tbody.innerHTML = shown.length
      ? shown.map((e) => (
        "<tr><td>" + esc(e.startDate) + "</td><td>" + esc(e.endDate) +
        '</td><td class="num">' + e.duration +
        '</td><td class="num">' + num(e.minValue, 2) +
        '</td><td class="num">' + num(e.severity, 2) +
        '</td><td class="num">' + (e.recoveryMonths === null ? "—" : e.recoveryMonths) +
        "</td><td>" + (e.censoring ? esc(e.censoring) : "complete") + "</td></tr>"
      )).join("")
      : '<tr><td colspan="7">No drought events at this threshold and minimum duration in the selected period.</td></tr>';

    $("dpEventMeta").textContent = ds.indicator.label + " · ≤ " +
      num(DIE.Analytics.droughtThreshold(ds.indicator), 2) + " · min 3 months · most recent first";
    const nComplete = events.filter((e) => !e.censoring).length;
    $("dpEventNote").textContent =
      (stats ? stats.nEvents : 0) + " complete event(s) and " +
      (stats ? stats.nEventsCensored : 0) + " censored at the record/period edge; " +
      "longest " + (stats ? stats.maxDuration : 0) + " months; mean duration " +
      num(stats && stats.meanDuration, 1) + " months. Frozen v1.0 runs analysis " +
      "(Yevjevich 1967), threshold = upper bound of the moderate class, minimum 3 " +
      "consecutive months, missing months break runs. Severity = Σ(threshold − value) " +
      "over the event; censored events are listed but excluded from duration/severity " +
      "summary statistics. Analysis period " + DIE.state.period.from + "–" +
      DIE.state.period.to + ".";
  }

  /* ---- era context ------------------------------------------------------ */
  function crossvalFor(id) {
    if (crossvalCache.has(id)) return crossvalCache.get(id);
    const p = (DIE.Engine && DIE.Engine.crossval)
      ? DIE.Engine.crossval({ variable: "spei_12", district: id })
          .then((rows) => rows[0] || null)
          .catch(() => null)
      : Promise.resolve(null);
    crossvalCache.set(id, p);
    return p;
  }

  async function renderEra(d, ds, stats, mySeq) {
    const el = $("dpEra");
    if (!el) return;
    const ym = DIE.Filters.dateYm();
    const sid = d.sid;
    const q = (extra) => extra;
    const linkProjections = "#projections?ind=" + encodeURIComponent(DIE.state.indicator) +
      "&ext=district&state=" + encodeURIComponent(sid) + "&dist=" + encodeURIComponent(d.id) +
      "&date=" + encodeURIComponent(ym) +
      q("&pGeo=district&pStateId=" + encodeURIComponent(sid) +
        "&pDistrict=" + encodeURIComponent(d.id) +
        "&pVariable=spi_03&pStat=agreement_moderate&pWindow=late");
    const linkCrossval = "#crossval?cVariable=spei_12&cMetric=bias&ind=spei_12" +
      "&ext=district&state=" + encodeURIComponent(sid) + "&dist=" + encodeURIComponent(d.id);
    const linkRecord = "#overview?ind=" + encodeURIComponent(DIE.state.indicator) +
      "&ext=district&state=" + encodeURIComponent(sid) + "&dist=" + encodeURIComponent(d.id) +
      "&date=" + encodeURIComponent(ym);

    el.innerHTML =
      '<div class="dp-era-card" data-era="b"><h3>Era B · Gridded Multi-Source Product</h3>' +
        "<p>1981–2025 record, " + (stats ? stats.validMonths + " valid months (" +
        pct(stats.completeness, 1) + ")" : "no valid months") +
        ". Sources: CHIRPS precipitation, ERA5-Land PET/soil moisture, MODIS NDVI.</p>" +
        '<a href="' + linkRecord + '">Open this district in the Record →</a></div>' +
      '<div class="dp-era-card" data-era="a"><h3>Era A · Drought Atlas reconstruction</h3>' +
        '<p id="dpEraA">1901–2025 station-based SPEI. Loading the 1981–2014 overlap…</p>' +
        '<a href="' + linkCrossval + '">Open the cross-validation panel →</a></div>' +
      '<div class="dp-era-card" data-era="c"><h3>Era C · CMIP6 projections</h3>' +
        "<p>2015–2100, 8-model committed subset, SSP2-4.5 / SSP5-8.5. Simulations, " +
        "never forecasts; never spliced with era B.</p>" +
        '<a href="' + linkProjections + '">Open this district in Projections →</a></div>';

    $("dpEraNote").textContent =
      "Eras are labelled and never spliced (R2). Era A and era B are compared only " +
      "over their 1981–2014 overlap (register D6); the seam SD is a measured " +
      "historical disagreement, not a projection confidence interval (X7).";

    const row = await crossvalFor(d.id);
    if (mySeq !== seq) return;
    const aEl = $("dpEraA");
    if (!aEl) return;
    if (row) {
      aEl.innerHTML = "1901–2025 station-based SPEI. Overlap 1981–2014 (" +
        row.n + " matched months): r = <b>" + num(row.r, 3) +
        "</b>, bias = <b>" + signed(row.bias, 2) + " z</b>, RMSD " + num(row.rmsd, 2) +
        " z, seam SD <b>±" + num(row.sd_diff, 2) + " z</b> (SPEI-12).";
    } else {
      aEl.innerHTML = "No Atlas grid cells for this district (documented ocean mask) — " +
        "era A context is absent, never imputed (R10).";
    }
  }

  /* ---- render orchestration -------------------------------------------- */
  async function render() {
    const mySeq = ++seq;
    const d = district();
    if (!d) {
      $("dpHeadline").textContent = "Choose a district from the map or the filter panel.";
      $("dpStrip").innerHTML = "";
      $("dpEventTable").querySelector("tbody").innerHTML = "";
      $("dpEra").innerHTML = "";
      return;
    }
    if (!DIE.registry || !DIE.meta) return;

    const ds = activeDataset();
    if (!ds) {
      $("dpHeadline").textContent = "Loading the indicator record…";
      try {
        await DIE.loader.indicator(DIE.state.indicator);
      } catch (err) {
        $("dpHeadline").textContent = "Indicator record unavailable: " +
          String(err && err.message || err);
        return;
      }
      if (mySeq !== seq) return;
      return render();          // re-enter with the dataset loaded
    }

    const period = DIE.state.period;
    const stats = DIE.Analytics.districtStats(ds, [d.id], period,
      { season: period.season })[0] || null;
    const ym = DIE.Filters.dateYm();

    $("dpBanner").innerHTML =
      "<b>One district, labelled eras.</b> The headline and indicator strip read the " +
      "era-B Gridded Multi-Source Product (1981–2025) at the selected month; trend and " +
      "events use the shared analysis period (" + period.from + "–" + period.to + ", " +
      (SEASON_LABEL[period.season] || period.season) + "). Era A (Atlas) and era C " +
      "(projections) are shown as context only and are never spliced into this record (R2).";

    renderHeadline(d, ds, stats);
    renderEvents(d, ds, stats);
    renderTrend(d, ds);
    await Promise.allSettled([
      renderStrip(d, ym, mySeq),
      renderEra(d, ds, stats, mySeq),
    ]);
  }

  /* ---- init / share ----------------------------------------------------- */
  function init() {
    if (!wired) {
      wired = true;
      const btn = $("dpShareBtn");
      if (btn) {
        btn.addEventListener("click", () => {
          track("share", DIE.state.districtId || "");
          if (DIE.Permalink) DIE.Permalink.copy("district");
        });
      }
    }
    DP.ready = true;
    return render();
  }

  function refresh() {
    if (!DP.ready) return init();
    return render();
  }

  DIE.DistrictProfile = { init, refresh };
})();
