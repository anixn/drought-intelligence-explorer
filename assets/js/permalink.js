/* ---------------------------------------------------------------------------
 * DIE v2.0 — state-encoding permalinks (task M10.4).
 *
 * One URL contract for every workspace:
 *
 *   #<tab>?<shared state>&<tab-specific state>
 *
 * Shared state (the sidebar / study context, honoured by every lens):
 *   ind    indicator id (metadata id, e.g. spi_3)
 *   date   observation month (YYYY-MM)
 *   ext    india | state | district
 *   state  state id (slug)
 *   dist   district id (slug)
 *   from   analysis period start year
 *   to     analysis period end year
 *   season season key (all, jjas, ... from metadata)
 *
 * Tab-specific state (only the tab that owns it reads/writes these):
 *   projections  pScenario pVariable pStat pWindow pGeo pStateId pDistrict
 *                pYear pMonth pDivYear pDivMonth
 *   summary      sScenario sVariable sWindow sMetric
 *   atlas        aVariable aYear aMonth
 *   crossval     cVariable cMetric
 *
 * Rules:
 *  - Existing hashes keep working: `#overview`, `#data`, `#data/doc-a-about`
 *    parse exactly as before; unknown or invalid parameters are ignored and
 *    the default retained (graceful fallback, never a broken view).
 *  - The URL is a presentation of already-validated state: nothing is loaded
 *    unless the catalog/registry/metadata already allow it, so a crafted link
 *    cannot inject a variable, a district or a year that does not exist.
 *  - The Copy-link control is authoritative for tab-specific controls; the
 *    address bar also tracks shared state and tab switches (replaceState, no
 *    history spam).
 * ------------------------------------------------------------------------- */
(function () {
  "use strict";

  const DIE = (window.DIE = window.DIE || {});
  const $ = (id) => document.getElementById(id);

  const SHARED_KEYS = ["ind", "date", "ext", "state", "dist",
    "from", "to", "season"];
  const PREFIX = {
    projections: /^p[A-Z]/,
    summary: /^s[A-Z]/,
    atlas: /^a[A-Z]/,
    crossval: /^c[A-Z]/,
  };

  /* Tab-specific state: each entry reads live module state and applies a
   * validated subset. Modules expose state objects at load time, so reading
   * works before the tab has ever been opened. */
  const MODULES = {
    projections: {
      get: () => DIE.Projections.permalinkState(),
      apply: (p) => DIE.Projections.applyPermalink(p),
      init: () => DIE.Projections.init(),
    },
    summary: {
      get: () => DIE.Summary.permalinkState(),
      apply: (p) => DIE.Summary.applyPermalink(p),
      init: () => DIE.Summary.init(),
    },
    atlas: {
      get: () => DIE.AtlasView.permalinkState(),
      apply: (p) => DIE.AtlasView.applyPermalink(p),
      init: () => DIE.AtlasView.init(),
    },
    crossval: {
      get: () => DIE.CrossvalView.permalinkState(),
      apply: (p) => DIE.CrossvalView.applyPermalink(p),
      init: () => DIE.CrossvalView.init(),
    },
  };

  let syncTimer = null;
  let wired = false;
  let routing = 0;

  const OWNERS = {
    projections: () => DIE.Projections,
    summary: () => DIE.Summary,
    atlas: () => DIE.AtlasView,
    crossval: () => DIE.CrossvalView,
  };

  /* ---- parsing ---------------------------------------------------------- */
  function parse(hash) {
    const raw = String(hash || "").replace(/^#/, "");
    // District profiles have a dedicated path route: #/district/<id>
    const dm = /^\/district\/([^?/]+)(?:\?(.*))?$/.exec(raw);
    if (dm) {
      return {
        tab: "district",
        doc: null,
        district: decodeURIComponent(dm[1]),
        params: new URLSearchParams(dm[2] || ""),
      };
    }
    const q = raw.indexOf("?");
    const path = q >= 0 ? raw.slice(0, q) : raw;
    const params = new URLSearchParams(q >= 0 ? raw.slice(q + 1) : "");
    const slash = path.indexOf("/");
    const tab = slash > 0 ? path.slice(0, slash) : path;
    const doc = slash > 0 ? path.slice(slash + 1) : null;
    return { tab, doc, params, district: null };
  }

  /* ---- validation helpers ---------------------------------------------- */
  function num(v, lo, hi) {
    const n = Number(v);
    return Number.isFinite(n) && n >= lo && n <= hi ? n : null;
  }
  function seasonKeys() {
    return (DIE.meta && DIE.meta.seasons) ? Object.keys(DIE.meta.seasons) : [];
  }

  /* ---- shared-state application (sidebar / study context) -------------- */
  async function applyShared(params) {
    if (!params) return false;
    const patch = {};

    const ind = params.get("ind");
    if (ind && DIE.indicatorById && DIE.indicatorById.has(ind) &&
        ind !== DIE.state.indicator) {
      try {
        await DIE.loader.indicator(ind);   // must exist before it is selected
        patch.indicator = ind;
      } catch (err) {
        console.warn("[permalink] indicator not loadable:", ind, err);
      }
    }

    const ds = DIE.datasets.get(patch.indicator || DIE.state.indicator);
    const date = params.get("date");
    if (date && ds && ds.dateIndex) {
      const idx = ds.dateIndex.get(date);
      if (idx !== undefined) patch.dateIdx = idx;
    }

    const ext = params.get("ext");
    if (ext === "india") {
      patch.extent = "india";
      patch.stateId = null;
      patch.districtId = null;
    } else if (ext === "state" && DIE.registry) {
      const sid = params.get("state");
      if (sid && DIE.registry.states.has(sid)) {
        patch.extent = "state";
        patch.stateId = sid;
        patch.districtId = null;
      }
    } else if (ext === "district" && DIE.registry) {
      const did = params.get("dist");
      const d = did && DIE.registry.districts.get(did);
      if (d) {
        patch.extent = "district";
        patch.stateId = d.sid;
        patch.districtId = did;
      }
    }

    const from = num(params.get("from"), 1901, 2100);
    const to = num(params.get("to"), 1901, 2100);
    if (from !== null) patch.period = Object.assign({}, patch.period, { from });
    if (to !== null) patch.period = Object.assign({}, patch.period, { to });
    if (patch.period && from !== null && to !== null && from > to) {
      patch.period.from = to;
      patch.period.to = from;
    }
    const season = params.get("season");
    if (season && seasonKeys().indexOf(season) !== -1) {
      patch.period = Object.assign({}, patch.period, { season });
    }

    if (!Object.keys(patch).length) return false;
    DIE.Filters.set(patch);
    // A region selection must also move the overview map to that region.
    if (DIE.MapView && DIE.MapView.fitRegion &&
        (patch.extent || patch.stateId !== undefined ||
         patch.districtId !== undefined)) {
      const type = DIE.state.districtId ? "district"
        : DIE.state.stateId ? "state" : null;
      DIE.MapView.fitRegion(type, DIE.state.districtId || DIE.state.stateId);
    }
    return true;
  }

  /* ---- tab-specific application ---------------------------------------- */
  async function applyTab(tab, params) {
    if (!params) return false;
    const mod = MODULES[tab];
    if (!mod) return false;
    let has = false;
    for (const k of params.keys()) {
      if (PREFIX[tab].test(k)) {
        has = true;
        break;
      }
    }
    if (!has) return false;
    try {
      const owner = OWNERS[tab] ? OWNERS[tab]() : null;
      if (owner && owner.whenReady) await owner.whenReady();
      else await mod.init();
      await mod.apply(params);
      return true;
    } catch (err) {
      console.warn("[permalink] tab state not applied:", tab, err);
      return false;
    }
  }

  /* ---- building -------------------------------------------------------- */
  function sharedQuery(q) {
    const st = DIE.state;
    if (!st) return;
    if (st.indicator) q.set("ind", st.indicator);
    const ym = DIE.Filters && DIE.Filters.dateYm ? DIE.Filters.dateYm() : null;
    if (ym) q.set("date", ym);
    q.set("ext", st.districtId ? "district" : st.stateId ? "state" : "india");
    if (st.stateId) q.set("state", st.stateId);
    if (st.districtId) q.set("dist", st.districtId);
    if (st.period && st.period.from != null) q.set("from", String(st.period.from));
    if (st.period && st.period.to != null) q.set("to", String(st.period.to));
    if (st.period && st.period.season) q.set("season", st.period.season);
  }

  function build(tab, doc) {
    const id = tab || DIE.currentTab || "overview";
    const q = new URLSearchParams();
    sharedQuery(q);
    const mod = MODULES[id];
    if (mod) {
      let extra = {};
      try { extra = mod.get() || {}; } catch (e) { extra = {}; }
      Object.keys(extra).forEach((k) => {
        const v = extra[k];
        if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
      });
    }
    const path = id === "district"
      ? "/district/" + (DIE.state.districtId || "gujarat-ahmedabad")
      : id + (id === "data" && doc ? "/" + doc : "");
    const qs = q.toString();
    return path + (qs ? "?" + qs : "");
  }

  function currentDoc() {
    if ((DIE.currentTab || "overview") !== "data") return null;
    return parse(location.hash).doc;
  }

  function urlFor(tab) {
    return location.href.split("#")[0] + "#" + build(tab, currentDoc());
  }

  /* ---- writing --------------------------------------------------------- */
  function sync(tab) {
    const id = tab || DIE.currentTab || "overview";
    const next = "#" + build(id, id === "data" ? parse(location.hash).doc : null);
    if (location.hash !== next) {
      history.replaceState(null, "", next);
    }
  }
  function scheduleSync() {
    if (routing) return;             // a permalink is being applied
    if (syncTimer) clearTimeout(syncTimer);
    syncTimer = setTimeout(() => {
      syncTimer = null;
      // Keep a documentation section anchor intact while the user is in the
      // docs workspace; state changes there are rare and the section is the
      // more specific link.
      const cur = DIE.currentTab || "overview";
      const parsed = parse(location.hash);
      if (cur === "data" && parsed.doc) return;
      sync(cur);
    }, 400);
  }

  /* ---- clipboard ------------------------------------------------------- */
  function legacyCopy(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.remove();
    return ok;
  }

  async function copy(tab) {
    const id = tab || DIE.currentTab || "overview";
    const url = urlFor(id);
    if (DIE.Telemetry) {
      try { DIE.Telemetry.track("share_copy", { tab: id, encoded: true }); } catch (e) {}
    }
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(url);
      } else if (!legacyCopy(url)) {
        throw new Error("clipboard unavailable");
      }
      if (DIE.toast) DIE.toast("Link copied",
        "Indicator, geography, period and this panel's settings are in the link.");
    } catch (err) {
      // Never silently fail a share action: show the URL so it can be copied.
      if (DIE.toast) DIE.toast("Could not copy automatically",
        "Select and copy this link: " + url, "warn");
      console.warn("[permalink] copy failed:", err);
    }
  }

  /* ---- wiring ---------------------------------------------------------- */
  function init() {
    if (wired) return;
    wired = true;
    const share = $("footShareBtn");
    if (share) share.addEventListener("click", () => copy());
    document.querySelectorAll("[data-share]").forEach((btn) => {
      btn.addEventListener("click", () => copy());
    });
    // Any control change (module-local or shared) updates the address bar
    // after the handler has committed its state. Debounced: sliders emit
    // input events continuously.
    document.addEventListener("change", scheduleSync);
    document.addEventListener("input", scheduleSync);
    if (DIE.bus && DIE.bus.on) DIE.bus.on("state", scheduleSync);
  }

  DIE.Permalink = {
    parse, build, urlFor, copy, sync, init,
    applyShared, applyTab,
    beginRoute: () => { routing += 1; if (syncTimer) { clearTimeout(syncTimer); syncTimer = null; } },
    endRoute: () => { routing = Math.max(0, routing - 1); },
    /* test hooks */
    modules: MODULES,
    sharedKeys: SHARED_KEYS.slice(),
  };
})();
