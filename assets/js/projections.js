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
 *    silently broken (section 7): the late-century window is unavailable
 *    while the 2051-2100 model inputs are pending.
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
  };

  const WINDOWS = {
    near: { from: 2026, to: 2040 },
    mid: { from: 2041, to: 2060 },     // partially covered (published to 2050)
    late: { from: 2081, to: 2100 },    // disabled option; inputs pending
  };

  // statistic -> era C partition groups in the published store
  // (scenario=<s>/stat=<st>/variable=<v>/year=<yyyy>/part-0.parquet)
  const STAT_PARTITIONS = {
    median: ["median"],
    band: ["median", "p25", "p75"],
    agreement_moderate: ["agreement_moderate"],
    agreement_severe: ["agreement_severe"],
  };
  const STAT_LABEL = {
    median: "median",
    p25: "p25",
    p75: "p75",
    agreement_moderate: "agreement (moderate)",
    agreement_severe: "agreement (severe)",
  };
  const SCENARIO_LABEL = { ssp245: "SSP2-4.5", ssp585: "SSP5-8.5" };
  const YEAR_RE = /year=(\d{4})\//;

  let catalog = null;       // shared catalog.json object (see getCatalog)

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
    const n = Number(y) || 2015;
    return Math.max(2015, Math.min(2050, Math.round(n)));
  }

  /* ---- banner + status --------------------------------------------------- */

  function renderBanner() {
    const el = $("projBanner");
    const ec = DIE.meta && DIE.meta.era_c;
    if (!ec) { el.innerHTML = ""; return; }
    el.innerHTML =
      "<b>Projections, not forecasts.</b> " + esc(ec.banner) +
      " Published as <b>" + esc(ec.label) + "</b>.";
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
      let covered = 0;
      for (let y = from; y <= to; y++) if (years.has(y)) covered++;
      const total = to - from + 1;
      const missing = total - covered;
      let status;
      if (covered === 0) {
        status = "not published for this window";
        worst = "none";
      } else if (missing > 0) {
        status = "partial — " + missing + " of " + total + " years pending (2051–2100 inputs pending)";
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
    note.innerHTML =
      "Resolved against the committed catalog (no engine query yet). " +
      (worst === "full"
        ? "The full window is covered by published partitions."
        : worst === "partial"
          ? "Part of the window is not published yet — charts (M5.3+) must show the gap, never fill it (R10)."
          : "No published partitions cover this window — the corresponding view must stay disabled with an explanation (section 7).");
  }

  /* ---- wiring -------------------------------------------------------------- */

  function wire() {
    document.querySelectorAll('input[name="projScenario"]').forEach((r) => {
      r.addEventListener("change", () => {
        state.scenario = r.value;
        track("scenario", r.value);
        renderCheck();
      });
    });
    $("projVariable").addEventListener("change", (e) => {
      state.variable = e.target.value;
      track("variable", e.target.value);
      renderCheck();
    });
    $("projStatistic").addEventListener("change", (e) => {
      state.statistic = e.target.value;
      track("statistic", e.target.value);
      renderCheck();
    });
    $("projWindow").addEventListener("change", (e) => {
      state.window = e.target.value;
      track("window", e.target.value);
      $("projCustomYears").hidden = state.window !== "custom";
      renderCheck();
    });
    const custom = () => {
      state.customFrom = clampYear($("projFromYear").value);
      state.customTo = clampYear($("projToYear").value);
      $("projFromYear").value = state.customFrom;
      $("projToYear").value = state.customTo;
      track("window_custom", state.customFrom + "-" + state.customTo);
      renderCheck();
    };
    $("projFromYear").addEventListener("change", custom);
    $("projToYear").addEventListener("change", custom);
    $("projGeography").addEventListener("change", (e) => {
      state.geography = e.target.value;
      track("geography", e.target.value);
      // geography shapes the M5.3+ chart scope; the file-level check is
      // geography-independent (partitions cover all 724 districts)
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
    renderVariableOptions();
    renderCheck();
  }

  DIE.Projections = { init, state };
})();
