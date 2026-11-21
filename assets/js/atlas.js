/* ---------------------------------------------------------------------------
 * DIE v2.0 — Atlas 1901–2025 (#atlas, task M6.3 / era A).
 *
 * The era-A scrubber surface: the Drought Atlas of India reconstruction
 * (SPEI at 1/4/12-month scales, 0.05° grid area-weighted onto the 724-district
 * fabric, register OD4) rendered one year at a time. Per-year partition
 * fetch only (M6.3 rule): one query per frame against the committed store
 * (data/parquet/atlas, 375 partitions), cached per (variable, year).
 *
 * Honesty rules honoured here:
 *  - Era A is a RECONSTRUCTION — the banner renders attribution from the
 *    data contract (metadata.json → era_a.source), never hand-typed.
 *  - NEVER spliced with era B / era C (R2): this surface shows era A alone.
 *  - The six island districts have no Atlas grid cells (documented ocean
 *    mask): grey, never imputed (R10).
 *  - No synthetic placeholders (R3): a missing partition is a loud note.
 *  - Drought anchors (1918/1965/1972/1987/2002) are documented historical
 *    episodes used as pre-set views, not claims about any single month.
 * ------------------------------------------------------------------------- */
(function () {
  "use strict";

  const DIE = (window.DIE = window.DIE || {});
  const $ = (id) => document.getElementById(id);

  const Atlas = { ready: false };

  const state = {
    variable: "spei_01",
    year: 1901,
    month: 8,           // monsoon peak month (JJAS core) as the default view
  };

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const VAR_LABEL = { spei_01: "SPEI-1 (monthly)", spei_04: "SPEI-4",
    spei_12: "SPEI-12 (annual)" };
  const YEAR_MIN = 1901, YEAR_MAX = 2025;

  let catalog = null;
  let mapApi = null;
  let yearCache = new Map();     // key "var|year" -> Map(district_id -> value@month)
  let seq = 0;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }
  function track(control, value) {
    if (DIE.Telemetry) {
      try { DIE.Telemetry.track("atlas_control", { control, value }); } catch (e) {}
    }
  }
  function getCatalog() {
    if (DIE.Engine && DIE.Engine.ensureCatalog) return DIE.Engine.ensureCatalog();
    return fetch("data/parquet/catalog.json", { cache: "no-store" })
      .then((r) => { if (!r.ok) throw new Error("catalog HTTP " + r.status); return r.json(); });
  }
  function eraA() {
    return catalog && catalog.eras && catalog.eras.atlas;
  }
  function classifyFn() {
    // era A z-scores share the McKee 9-class table with the era-B SPEI family
    return DIE.indicatorById &&
      (DIE.indicatorById.get(state.variable) ||
       DIE.indicatorById.get("spei_03") ||
       DIE.indicatorById.get("spi_03"));
  }

  /* ---- controls ---------------------------------------------------------- */
  function wire() {
    $("atlasVariable").addEventListener("change", (e) => {
      state.variable = e.target.value;
      track("variable", state.variable);
      yearCache.clear();          // cache is keyed by var|year anyway; keep tidy
      renderAll();
    });
    $("atlasMonth").addEventListener("change", (e) => {
      state.month = +e.target.value;
      track("month", state.month);
      renderAll();
    });
    const year = $("atlasYear");
    year.addEventListener("input", () => {
      $("atlasYearReadout").textContent = year.value;
    });
    year.addEventListener("change", () => {
      state.year = +year.value;
      track("year", state.year);
      renderAll();
    });
    for (const btn of document.querySelectorAll(".atlas-anchor")) {
      btn.addEventListener("click", () => {
        state.year = +btn.dataset.year;
        year.value = String(state.year);
        $("atlasYearReadout").textContent = String(state.year);
        track("anchor", state.year);
        renderAll();
      });
    }
  }

  function renderBanner() {
    const el = $("atlasBanner");
    const src = DIE.meta && DIE.meta.era_a && DIE.meta.era_a.source;
    const ec = eraA();
    const cite = src && src.citation ? esc(src.citation) : "";
    const doi = src && src.doi ? esc(src.doi) : "";
    const lic = src && src.licence ? esc(src.licence) : "";
    el.innerHTML =
      "<b>Era A — a reconstruction, not an observation.</b> " +
      (ec && ec.label ? "Published as <b>" + esc(ec.label) + "</b>. " : "") +
      "SPEI at 1-, 4- and 12-month scales on the 724-district fabric, " +
      "area-weighted from the 0.05° grid (route OD4). Source: " + cite +
      " (DOI " + doi + ", " + lic + "). <b>Never spliced</b> with the era-B " +
      "Gridded Multi-Source Product or era-C projections — the 1981–2025 " +
      "overlap is cross-validation material, not a continuous record (R2).";
  }

  /* ---- data -------------------------------------------------------------- */
  async function yearMap() {
    const key = state.variable + "|" + state.year;
    if (yearCache.has(key)) return yearCache.get(key);
    if (!DIE.Engine || !DIE.Engine.atlasYear) {
      throw new Error("engine builder unavailable");
    }
    const rows = await DIE.Engine.atlasYear({
      variable: state.variable, year: state.year,
    });
    const byD = new Map();     // district_id -> {month -> value}
    for (const r of rows) {
      if (!Number.isFinite(r.value)) continue;
      let m = byD.get(r.district_id);
      if (!m) byD.set(r.district_id, (m = new Map()));
      m.set(r.month, r.value);
    }
    yearCache.set(key, byD);
    if (yearCache.size > 24) {           // bounded cache (12 years × 2 var)
      const first = yearCache.keys().next().value;
      yearCache.delete(first);
    }
    return byD;
  }

  /* ---- render ------------------------------------------------------------- */
  async function renderAll() {
    const mySeq = ++seq;
    const note = $("atlasScrubNote"), meta = $("atlasMapMeta");
    const mapNote = $("atlasMapNote");
    if (!DIE.Engine || !DIE.registry || !DIE.boundaries) return;
    meta.textContent = "querying the era-A store…";
    try {
      const byD = await yearMap();
      if (mySeq !== seq) return;
      const vals = new Map();            // district_id -> value at month
      for (const [id, m] of byD) {
        const v = m.get(state.month);
        if (Number.isFinite(v)) vals.set(id, v);
      }
      lastValues = vals;

      if (!mapApi) {
        mapApi = DIE.MapView.createChoropleth($("atlasMap"), { tooltip: false });
      }
      const ind = classifyFn();
      mapApi.applyData(null, 0, null, null,
        () => null,
        (id) => {
          const v = vals.get(id);
          const c = ind && Number.isFinite(v) ? DIE.classify(v, ind) : null;
          return c ? c.color : "#E8E1D2";
        });
      if (mySeq !== seq) return;

      meta.textContent = "era A · " + (VAR_LABEL[state.variable] || state.variable) +
        " · " + MONTHS[state.month - 1] + " " + state.year;
      const n = vals.size;
      mapNote.textContent =
        n + " districts with values at " + MONTHS[state.month - 1] + " " +
        state.year + " (the six island districts have no Atlas grid cells — " +
        "grey, never imputed). McKee classes on the era-A z-scores; click any " +
        "district to zoom it into the frame. A reconstruction, not an " +
        "observation: pre-1951 station density is lower (quantified in " +
        "#crossval).";

      // class shares (area-weighted, v1.0 LAEA registry areas)
      let area = 0, mod = 0, sev = 0, ext = 0, wet = 0;
      for (const [id, v] of vals) {
        const reg = DIE.registry.districts.get(id);
        if (!reg || !Number.isFinite(reg.area)) continue;
        area += reg.area;
        const cls = ind ? DIE.classify(v, ind) : null;
        const label = cls ? String(cls.label || "").toLowerCase() : "";
        if (v <= -2) ext += reg.area;
        else if (v <= -1.5) sev += reg.area;
        else if (v <= -1) mod += reg.area;
        else if (v > 0.5) wet += reg.area;
      }
      const pct = (x) => (area ? (x / area * 100).toFixed(1) + "%" : "—");
      $("atlasShareMod").textContent = pct(mod + sev + ext);
      $("atlasShareSev").textContent = pct(sev + ext);
      $("atlasShareExt").textContent = pct(ext);
      $("atlasShareWet").textContent = pct(wet);
      $("atlasShareN").textContent = String(vals.size);
      $("atlasShareMeta").textContent = "area-weighted · " +
        (VAR_LABEL[state.variable] || state.variable) + " · " +
        MONTHS[state.month - 1] + " " + state.year;
      $("atlasShareNote").textContent =
        "Shares of the LAEA national area (3,266,386 km² registry; era-A " +
        "comparable " + area.toFixed(0) + " km²) in each McKee drought class " +
        "for the displayed month: moderate ≤ −1.0, severe ≤ −1.5, " +
        "extreme ≤ −2.0 (cumulative); wetter-than-normal = z > +0.5. " +
        "n = districts with data this month.";
      note.textContent = "era A live · one year per frame, cached per " +
        "(timescale, year)";
      renderLegend(ind);
    } catch (err) {
      console.warn("[atlas] render failed:", err);
      meta.textContent = "unavailable";
      note.textContent = "Era-A render unavailable: " +
        String(err && err.message || err);
      mapNote.textContent = "The year partition for this frame could not be " +
        "read — no placeholder is shown (R3).";
    }
  }

  let lastValues = null;
  function renderLegend(ind) {
    const el = $("atlasLegend");
    if (!ind || !ind.classes) {
      el.innerHTML = '<span class="legend-head">McKee z-classes (era-A ' +
        "classification table unavailable in this session)</span>";
      return;
    }
    el.innerHTML =
      '<span class="legend-head">McKee classes — ' +
      esc(VAR_LABEL[state.variable] || state.variable) + " (z)</span>" +
      ind.classes.map((c) =>
        '<span class="legend-row"><span style="display:inline-block;' +
        "width:12px;height:12px;border-radius:2px;background:" + c.color +
        '"></span><span class="legend-range">' + esc(c.label) + "</span></span>"
      ).join("");
  }

  /* ---- init ---------------------------------------------------------------- */
  async function doInit() {
    if (!Atlas.ready) {
      wire();
      Atlas.ready = true;
    }
    if (!catalog) {
      try {
        catalog = await getCatalog();
      } catch (err) {
        console.warn("[atlas] catalog load failed:", err);
        $("atlasBanner").textContent =
          "Data contract unavailable — this workspace shows committed " +
          "catalog facts only (no synthetic placeholders, R3). Error: " +
          String(err && err.message || err);
        return;
      }
    }
    if (!eraA() || !eraA().available) {
      $("atlasBanner").textContent =
        "The atlas era has no promoted store yet; this workspace renders " +
        "nothing rather than a placeholder (R3).";
      return;
    }
    renderBanner();
    const msel = $("atlasMonth");
    if (!msel.options.length) {
      msel.innerHTML = MONTHS.map((m, i) =>
        '<option value="' + (i + 1) + '"' + (i + 1 === state.month ? " selected" : "") +
        ">" + m + "</option>").join("");
    }
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
  }

  /* ---- permalink state (M10.4) ------------------------------------------ */
  function permalinkState() {
    return { aVariable: state.variable, aYear: state.year, aMonth: state.month };
  }

  async function applyPermalink(p) {
    await whenReady();                 // never race the first render
    const v = p.get ? p.get("aVariable") : p.aVariable;
    const y = Number(p.get ? p.get("aYear") : p.aYear);
    const m = Number(p.get ? p.get("aMonth") : p.aMonth);
    if (v && VAR_LABEL[v]) state.variable = v;
    if (Number.isFinite(y) && y >= YEAR_MIN && y <= YEAR_MAX) state.year = y;
    if (Number.isFinite(m) && m >= 1 && m <= 12) state.month = m;
    const vSel = $("atlasVariable"), mSel = $("atlasMonth"), ySel = $("atlasYear");
    if (vSel) vSel.value = state.variable;
    if (mSel) mSel.value = String(state.month);
    if (ySel) ySel.value = String(state.year);
    const readout = $("atlasYearReadout");
    if (readout) readout.textContent = String(state.year);
    await renderAll();
  }

  DIE.AtlasView = { init, whenReady, invalidate, permalinkState, applyPermalink };
})();
