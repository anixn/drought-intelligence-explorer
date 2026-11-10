/* ===========================================================================
 * telemetry.js — deep application-event instrumentation (GTM/dataLayer)
 * ---------------------------------------------------------------------------
 * Every meaningful user action is pushed onto window.dataLayer as a
 * `die_*` event with a `value` weight that estimates how strongly the
 * action signals willingness to PAY for a professional/research tier of
 * this application (bulk exports, API access, custom regions, operational
 * feeds). Weights accumulate per session; tier crossings emit a dedicated
 * `die_user_tier` event, so the site owner can segment "people who will
 * pay" in GA4/GTM audiences without any backend.
 *
 *   browsing    < 12   — casual map browsing
 *   explorer   >= 12   — repeated analysis, date scrubbing, indicator swaps
 *   high_intent>= 40   — event deep-dives, propagation pairs, searches
 *   research_pro>= 100 — multiple data exports / heavy research workflow
 *
 * Design rules:
 *  - No PII: only interaction metadata (names of public regions, indicator
 *    ids, filenames) leaves the browser.
 *  - Fails silently: tracking never throws into the app's error path.
 *  - Transport-only via dataLayer (works with the GTM container and with
 *    a GA4 gtag config alike); a ring-buffer log is kept for debugging
 *    (DIE.Telemetry.log, DIE.Telemetry.state()).
 *  - Transient slider drags are filtered upstream; date changes are
 *    tracked once per committed change.
 * Event schema & value table: docs/analytics-events.md
 * =========================================================================== */
(function () {
  'use strict';

  const DIE = (window.DIE = window.DIE || {});

  /* ------------------------------------------------------ value model -- */
  const VALUES = {
    export_data: 25,        // any research file download (CSV/JSON/MD)
    chart_export: 10,       // Plotly toolbar export (PNG/CSV per chart)
    event_detail_open: 8,   // opening a single drought event deep-dive
    propagation_pair: 6,    // choosing a cross-indicator pair
    comparison_change: 6,   // changing the single-date comparison module
    sensitivity_scenario: 5,// re-running the catalogue under a scenario
    indicator_change: 4,    // swapping the drought indicator
    district_focus: 4,      // clicking a district (map or dropdown)
    animation_play: 3,      // playing the drought evolution
    tab_view: 2,            // visiting a workspace (tab-weighted, see below)
    docs_open: 2,           // opening a methodology/guide section
    table_search: 2,        // searching a table
    date_change: 1,         // committed observation-date change
    filter_change: 1,       // geography / period adjustments
    table_sort: 1,
    table_page: 1,
    table_level: 1,
    outbound_link: 1,
    share_copy: 3,          // copying an analysis deep link (share intent)
    validate_all: 2,
    drawer_toggle: 0,
    panel_toggle: 0,
    fullscreen: 0,
    reset_filters: 0,
    session_summary: 0
  };
  /* tab_view weight: analytical tabs show research intent, Overview does not */
  const TAB_WEIGHTS = { overview: 1, historical: 3, events: 3, propagation: 4, data: 2 };

  /* Emission thresholds: die_user_tier fires once per threshold crossed.
     'browsing' is the implicit baseline below 12 and is never emitted —
     every visitor would otherwise trigger a meaningless tier event. */
  const TIERS = [
    { min: 100, id: 'research_pro' },
    { min: 40, id: 'high_intent' },
    { min: 12, id: 'explorer' }
  ];
  const TIERS_ALL = TIERS.concat([{ min: 1, id: 'browsing' }]);

  /* ------------------------------------------------------------- state -- */
  const state = {
    value: 0,
    events: 0,
    exports: 0,
    tabs: {},          // tab -> visit count
    tiers: [],         // tiers reached this session
    startedAt: Date.now()
  };
  let sessionId = '';
  const log = [];      // ring buffer for console debugging
  let lastSummaryAt = 0;

  function sessionIdInit() {
    try {
      sessionId = sessionStorage.getItem('die.sid') || '';
      if (!sessionId) {
        sessionId = 's-' + Date.now().toString(36) + '-' +
          Math.random().toString(36).slice(2, 8);
        sessionStorage.setItem('die.sid', sessionId);
      }
    } catch (e) {
      sessionId = 's-anon-' + Math.random().toString(36).slice(2, 8);
    }
  }

  /** Current application context attached to every event. */
  function ctx() {
    try {
      return {
        tab: document.body.dataset.tab || 'overview',
        indicator: DIE.state ? DIE.state.indicator : null,
        region: (DIE.Filters && DIE.Filters.regionLabel()) || null
      };
    } catch (e) { return {}; }
  }

  function tierFor(v) {
    const t = TIERS_ALL.find((t) => v >= t.min);
    return t ? t.id : 'browsing';
  }

  function push(payload) {
    try { (window.dataLayer = window.dataLayer || []).push(payload); } catch (e) {}
  }

  /* ------------------------------------------------------------- track -- */
  /**
   * Track one application event.
   * @param {string} name   event name without the `die_` prefix
   * @param {object} params event parameters (strings/numbers only)
   * @param {number} [weight] override the default value weight
   */
  function track(name, params, weight) {
    params = params || {};
    let value = weight !== undefined ? weight : (VALUES[name] || 0);
    // tab_view is weighted by the analytical depth of the tab entered
    if (name === 'tab_view' && weight === undefined) {
      value = TAB_WEIGHTS[params.tab] || 1;
    }
    state.value += value;
    state.events++;
    if (name === 'export_data' || name === 'chart_export') state.exports++;
    if (name === 'tab_view') {
      const tab = params.tab || 'overview';
      state.tabs[tab] = (state.tabs[tab] || 0) + 1;
    }
    const c = ctx();
    const evt = Object.assign({
      event: 'die_' + name,
      value: value,                                        // GA4-style value
      engagement_tier: tierFor(state.value) || 'browsing',
      session_value: Math.round(state.value * 10) / 10,
      session_id: sessionId,
      die_tab: c.tab,
      die_indicator: c.indicator,
      die_region: c.region
    }, params);
    log.push({ t: Date.now(), name, params });
    if (log.length > 120) log.shift();
    push(evt);
    checkTier();
  }

  /** Emit die_user_tier the first time each value threshold is crossed. */
  function checkTier() {
    const tier = tierFor(state.value);
    if (tier && tier !== 'browsing' && state.tiers.indexOf(tier) === -1) {
      state.tiers.push(tier);
      push({
        event: 'die_user_tier',
        tier: tier,
        value: Math.round(state.value * 10) / 10,
        session_id: sessionId
      });
    }
  }

  /* -------------------------------------------------------------- wire -- */
  /** Subscribe to application events. Called once from app.js init(). */
  function wire() {
    sessionIdInit();
    push({ event: 'die_session_start', session_id: sessionId });

    /* All Filters.set() state changes funnel through the bus — one listener
       covers every geography/indicator/period/date control in the app. */
    if (DIE.bus) {
      DIE.bus.on('state', (p) => {
        if (!p || !p.changed || !p.changed.length) return;
        if (p.transient) return; // in-progress slider drags: not committed
        const st = DIE.state;
        if (p.changed.indexOf('indicator') !== -1) {
          track('indicator_change', { indicator: st.indicator });
          return;
        }
        if (p.changed.indexOf('dateIdx') !== -1) {
          track('date_change', { date: (DIE.Filters && DIE.Filters.dateYm && DIE.Filters.dateYm()) || null });
          return;
        }
        track('filter_change', {
          keys: p.changed.join(','),
          extent: st.extent,
          state_id: st.stateId || null,
          district_id: st.districtId || null,
          period: st.period.from + '-' + st.period.to,
          season: st.period.season
        });
      });
    }

    /* Delegated global clicks:
       · Plotly modebar exports (bypass the app's download funnel)
       · outbound links (author site, references) */
    document.addEventListener('click', (e) => {
      const target = e.target;
      if (!target || !target.closest) return;
      const modeBtn = target.closest('.modebar [data-title]');
      if (modeBtn) {
        track('chart_export', { tool: modeBtn.getAttribute('data-title') || 'modebar' });
        return;
      }
      const link = target.closest('a[href^="http"]');
      if (link && link.target === '_blank') {
        track('outbound_link', { destination: link.href });
      }
    });

    /* Session summary when the user leaves — mobile-friendly (fires on
       tab-hide; desktop also gets pagehide). Weight 0: never inflates. */
    const summary = () => {
      if (Date.now() - lastSummaryAt < 60000) return;
      lastSummaryAt = Date.now();
      track('session_summary', {
        seconds: Math.round((Date.now() - state.startedAt) / 1000),
        tabs_visited: Object.keys(state.tabs).join(',') || 'overview',
        exports: state.exports,
        event_count: state.events
      }, 0);
    };
    document.addEventListener('visibilitychange', () => { if (document.hidden) summary(); });
    window.addEventListener('pagehide', summary);
  }

  /* ----------------------------------------------------------- public -- */
  DIE.Telemetry = {
    track,
    wire,
    /** Ring buffer of the last 120 events (console debugging). */
    log,
    /** Snapshot of the session state (value, exports, tiers…). */
    state: () => JSON.parse(JSON.stringify(state))
  };
})();
