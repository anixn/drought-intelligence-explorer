/* ===========================================================================
 * app.js — application orchestration (five-tab edition)
 * ---------------------------------------------------------------------------
 *  - Boot sequence (metadata -> boundaries -> registry -> indicator).
 *  - Hash-based tab routing (#overview|#historical|#events|#propagation|#data);
 *    geography/indicator/period state is shared across tabs (single DIE.state).
 *  - View controllers:
 *      Overview      — date controls, KPI snapshot, map, time series,
 *                      district ranking, historical-context timeline.
 *      Historical    — frequency/duration/severity (existing engine), spatial
 *                      statistic maps, Mann-Kendall + Sen trends, recurrence,
 *                      district-wise ranking table.
 *      Events        — catalogue (runs analysis per district), onset timeline,
 *                      duration/severity distribution, event detail view,
 *                      definition sensitivity scenarios.
 *      Propagation   — lagged cross-correlation with block-bootstrap CI,
 *                      correlation heatmap, district optimal-lag map, the
 *                      migrated single-date spatial comparison, and a clearly
 *                      marked unavailable hydrological-drought section.
 *      Data & Methods— metadata tables, data quality, methodology,
 *                      reproducible downloads.
 *  - Modals, fullscreen, mobile drawer, toasts, keyboard accessibility.
 * =========================================================================== */
(function () {
  'use strict';

  const DIE = (window.DIE = window.DIE || {});
  const $ = (id) => document.getElementById(id);
  const A = () => DIE.Analytics;
  const S = () => DIE.Stats;

  const TABS = [
    { id: 'overview', btn: 'tabOverview', view: 'viewOverview' },
    { id: 'historical', btn: 'tabHistorical', view: 'viewHistorical' },
    { id: 'events', btn: 'tabEvents', view: 'viewEvents' },
    { id: 'propagation', btn: 'tabPropagation', view: 'viewPropagation' },
    { id: 'data', btn: 'tabData', view: 'viewData' }
  ];
  let currentTab = 'overview';
  // Tabs are marked dirty on state changes while hidden and re-render only
  // when entered. This avoids updating 5 workspaces on every slider tick.
  const DIRTY = { overview: true, historical: true, events: true, propagation: true, data: true };
  const markDirty = (tab) => { DIRTY[tab] = true; };

  /** Run work when the browser is idle (never blocks interaction). */
  function idle(fn) {
    if ('requestIdleCallback' in window) {
      window.requestIdleCallback(() => run(fn), { timeout: 2500 });
    } else {
      setTimeout(() => run(fn), 900);
    }
  }

  /* ------------------------------------------------------------ helpers -- */
  function setBoot(msg, pct) {
    const s = $('bootStatus'), f = $('bootBarFill');
    if (s) s.textContent = msg;
    if (f && pct !== undefined) f.style.width = pct + '%';
  }
  function fatal(title, body) {
    const ov = $('bootOverlay');
    ov.classList.remove('is-hidden');
    setBoot('');
    ov.querySelector('.boot-card').innerHTML =
      '<div class="boot-title" style="color:#B94747">' + title + '</div>' +
      '<p class="boot-error" style="white-space:pre-line">' + body + '</p>' +
      '<button class="btn btn-solid" style="margin-top:14px" onclick="location.reload()">Retry</button>';
  }

  function toast(title, body, type) {
    const stack = $('toastStack');
    if (!stack) return;
    const t = document.createElement('div');
    t.className = 'toast' + (type ? ' ' + type : '');
    t.innerHTML = '<div><div class="t-title">' + title + '</div>' +
      (body ? '<div class="t-body">' + body + '</div>' : '') + '</div>' +
      '<button aria-label="Dismiss">&times;</button>';
    t.querySelector('button').onclick = () => t.remove();
    stack.appendChild(t);
    setTimeout(() => t.remove(), 7000);
  }

  function currentDataset() { return DIE.datasets.get(DIE.state.indicator); }
  function ids() { return DIE.Filters.regionIds(); }
  function isDemo() { return /synthetic|demonstration/i.test(String(DIE.meta.data_mode || '')); }
  function run(fn) { try { fn(); } catch (e) { console.error(e); } }
  function debounce(fn, ms) {
    let t;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  }
  const periodLabel = () => DIE.state.period.from + '–' + DIE.state.period.to +
    (DIE.state.period.season === 'all' ? '' : ' · ' + $('seasonSelect').selectedOptions[0].textContent);

  /* ------------------------------------------------- busy cursor state --
   * `body.is-busy` shows the progress (waiting) cursor on every element so
   * long loads and heavy computations signal that work is in progress.
   * A counter supports overlapping async operations; deferBusy() yields one
   * paint before a synchronous block so the cursor actually appears. */
  let busyCount = 0;
  function busy(on) {
    busyCount = Math.max(0, busyCount + (on ? 1 : -1));
    document.body.classList.toggle('is-busy', busyCount > 0);
  }
  function deferBusy(fn) {
    busy(true);
    setTimeout(() => {
      try { fn(); } finally { busy(false); }
    }, 30);
  }

  /* ============================================================== BOOT == */
  async function init() {
    try {
      if (!window.L || !window.Papa) {
        fatal('Required libraries failed to load',
          'Leaflet and/or PapaParse could not be loaded from the bundled copy or the CDN fallback.\n\n' +
          'Check your network connection, or serve the application over HTTP (see README).');
        return;
      }
      if (DIE.isLocalFile) {
        toast('Running from the file system',
          'Browsers block fetch() on file:// — start a local server, e.g. python3 -m http.server', 'warn');
      }
      setBoot('Loading dataset metadata…', 12);
      await DIE.loader.metadata();

      // Boundaries, registries and the current indicator CSV all load in
      // parallel; only parsing waits for the registry (browser-cache hit).
      setBoot('Loading boundaries, registries and indicator data…', 38);
      const indLabel = DIE.indicatorById.get(DIE.state.indicator).label;
      await Promise.all([
        DIE.loader.boundaries(),
        DIE.loader.registry(),
        DIE.loader.prefetchIndicator(DIE.state.indicator)
      ]);

      setBoot('Parsing ' + indLabel + '…', 66);
      await DIE.loader.indicator(DIE.state.indicator);

      const ds0 = currentDataset();
      DIE.state.dateIdx = ds0.availableEndIndex >= 0
        ? ds0.availableEndIndex : ds0.dates.length - 1;
      DIE.state.period.from = +(ds0.availableFrom || DIE.meta.period.start).slice(0, 4);
      DIE.state.period.to = +(ds0.availableTo || DIE.meta.period.end).slice(0, 4);

      setBoot('Building interface…', 84);
      DIE.Filters.renderIndicators();
      DIE.Filters.wire();
      DIE.Filters.render();
      DIE.MapView.init();
      DIE.MapView.fitRegion();

      wireShell();
      renderStaticText();
      routeFromHash();

      setBoot('Ready', 100);
      setTimeout(() => { $('bootOverlay').classList.add('is-hidden'); busy(false); }, 250);
      // Warm the next likely indicators while the main thread is idle; CSV
      // text is cached without parsing until the user actually switches.
      idle(() => {
        ['spei_3', 'spi_6', 'vci'].forEach((id) => {
          if (id !== DIE.state.indicator) DIE.loader.prefetchIndicator(id);
        });
      });
      console.info('[DIE] ready · base path: ' + DIE.base, DIE_DIAG);
    } catch (err) {
      console.error(err);
      busy(false);
      fatal('Failed to initialise',
        String(err && err.message || err) +
        '\n\nTroubleshooting: serve the folder over HTTP and confirm data/metadata.json is reachable at ' + DIE.base + 'data/metadata.json');
    }
  }

  /* ============================================================== ROUTER == */
  function switchTab(which, push) {
    const tab = TABS.find((t) => t.id === which) || TABS[0];
    currentTab = tab.id;
    TABS.forEach((t) => {
      const btn = $(t.btn), view = $(t.view);
      const active = t.id === tab.id;
      view.hidden = !active;
      btn.setAttribute('aria-selected', String(active));
      btn.tabIndex = active ? 0 : -1;
    });
    if (push !== false && location.hash !== '#' + tab.id) {
      history.replaceState(null, '', '#' + tab.id);
    }
    // Lazy init + render only when the tab needs it. DIRTY starts true for
    // every tab and is set on state changes while the tab is hidden.
    if (DIRTY[tab.id]) {
      run(() => Views[tab.id] && Views[tab.id]());
      DIRTY[tab.id] = false;
    }
    // Leaflet needs a size recalculation after its container becomes visible.
    setTimeout(() => {
      if (tab.id === 'overview') {
        if (DIE.MapView.main) DIE.MapView.main.invalidateSize();
        if (DIE.MapView.evoMap) DIE.MapView.evoMap.invalidateSize();
      } else if (tab.id === 'historical') {
        ['durMap', 'sevMap'].forEach((id) => DIE.MapView[id] && DIE.MapView[id].invalidateSize());
      } else if (tab.id === 'propagation') {
        if (DIE.MapView.propMap) DIE.MapView.propMap.invalidateSize();
        if (Propagation.mapA) Propagation.mapA.invalidateSize();
        if (Propagation.mapB) Propagation.mapB.invalidateSize();
      } else if (tab.id === 'events' && DIE.MapView.evtDetailMap) {
        DIE.MapView.evtDetailMap.invalidateSize();
      }
    }, 60);
    document.body.dataset.tab = tab.id;
  }

  function routeFromHash() {
    const h = (location.hash || '').replace('#', '');
    switchTab(TABS.some((t) => t.id === h) ? h : 'overview', false);
  }

  /* =========================================================== SHELL UI == */
  function wireShell() {
    // modals
    document.querySelectorAll('[data-modal]').forEach((btn) => {
      btn.addEventListener('click', () => openModal($(btn.dataset.modal)));
    });
    document.querySelectorAll('.modal-scrim').forEach((scrim) => {
      scrim.addEventListener('click', (e) => { if (e.target === scrim) closeModal(scrim); });
      scrim.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', () => closeModal(scrim)));
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') document.querySelectorAll('.modal-scrim:not([hidden])').forEach(closeModal);
      // "?" opens the user guide unless the user is typing in a control.
      const typing = /^(INPUT|SELECT|TEXTAREA)$/.test((document.activeElement || {}).tagName || '');
      if (e.key === '?' && !typing && e.target === document.body) {
        const g = $('modalGuide');
        if (g && g.hidden) { openModal(g); e.preventDefault(); }
      }
      // arrow-key tab navigation on the tablist
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        const idx = TABS.findIndex((t) => t.id === currentTab);
        if (idx >= 0 && document.activeElement && document.activeElement.role === 'tab') {
          const next = TABS[(idx + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length];
          $(next.btn).focus();
          switchTab(next.id);
          e.preventDefault();
        }
      }
    });

    // tabs
    TABS.forEach((t) => $(t.btn).addEventListener('click', () => switchTab(t.id)));
    window.addEventListener('hashchange', routeFromHash);

    // fullscreen
    $('fullscreenBtn').addEventListener('click', () => {
      if (!document.fullscreenElement) {
        (document.documentElement.requestFullscreen || document.documentElement.webkitRequestFullscreen || function () {}).call(document.documentElement);
      } else {
        (document.exitFullscreen || document.webkitExitFullscreen || function () {}).call(document);
      }
    });

    // mobile drawer
    const drawerMq = window.matchMedia('(max-width: 1024px)');
    $('navToggle').addEventListener('click', () => {
      if (!drawerMq.matches) return;
      const open = $('sidebar').classList.toggle('is-open');
      $('navToggle').setAttribute('aria-expanded', String(open));
      $('scrim').hidden = !open;
    });
    $('sidebarClose').addEventListener('click', closeDrawer);
    $('scrim').addEventListener('click', closeDrawer);

    // clear district selection
    $('clearSelectionBtn').addEventListener('click', () => {
      DIE.Filters.set({
        extent: DIE.state.stateId ? 'state' : 'india',
        districtId: null
      });
    });

    // Overview contextual controls
    $('tsTrendChk').addEventListener('change', () => renderTimeSeries());
    $('mapPngBtn').addEventListener('click', () => DIE.MapView.exportPNG());
    document.querySelectorAll('input[name="rankBy"]').forEach((r) =>
      r.addEventListener('change', () => renderRanking()));

    // Historical controls
    document.querySelectorAll('input[name="trendGran"]').forEach((r) =>
      r.addEventListener('change', () => Historical.renderTrend()));

    // Events controls
    $('evtMinDur').addEventListener('change', () => EventsView.refresh());
    $('evtThreshold').addEventListener('change', () => EventsView.refresh());
    $('evtSearch').addEventListener('input', () => EventsView.renderTable());
    $('evtYear').addEventListener('change', () => EventsView.renderTable());
    $('evtCsvBtn').addEventListener('click', () => EventsView.exportCSV());
    document.querySelectorAll('#evtTable th.sortable').forEach((th) => {
      th.addEventListener('click', () => {
        const key = th.dataset.key;
        if (EventsView.sortKey === key) EventsView.sortDir *= -1;
        else { EventsView.sortKey = key; EventsView.sortDir = key === 'district' || key === 'state' || key === 'start' || key === 'end' ? 1 : -1; }
        EventsView.renderTable();
      });
    });
    $('evtDetailClose').addEventListener('click', () => { $('evtDetailPanel').hidden = true; });
    document.querySelectorAll('input[name="sensMode"]').forEach((r) =>
      r.addEventListener('change', () => EventsView.renderSensitivity()));

    // Propagation controls
    $('propIndA').addEventListener('change', () => { Propagation.renderMain(); Propagation.renderDistrictLagMap(); });
    $('propIndB').addEventListener('change', () => { Propagation.renderMain(); Propagation.renderDistrictLagMap(); });

    // Data tab
    $('methDocBtn').addEventListener('click', async () => {
      try {
        const text = await DIE.loader.fetchText('docs/methodology.md');
        A().toText('methodology.md', text, 'text/markdown;charset=utf-8');
      } catch (err) { toast('Download failed', String(err.message || err), 'error'); }
    });
    if ($('validateAllBtn')) {
      $('validateAllBtn').addEventListener('click', () => DataView.validateAll());
    }
    // User-guide download buttons live outside #downloadsTab (guide panel).
    document.addEventListener('click', async (e) => {
      const btn = e.target.closest && e.target.closest('[data-dl="userguide"]');
      if (!btn || btn.closest('#downloadsTab')) return;
      try {
        const text = await DIE.loader.fetchText('docs/user-guide.md');
        A().toText('user-guide.md', text, 'text/markdown;charset=utf-8');
        toast('User guide saved', 'docs/user-guide.md');
      } catch (err) { toast('Download failed', String(err.message || err), 'error'); }
    });

    // comparison table controls (Historical tab)
    document.querySelectorAll('#compTable th.sortable').forEach((th) => {
      th.addEventListener('click', () => {
        const key = th.dataset.key;
        if (Table.sortKey === key) Table.sortDir *= -1;
        else { Table.sortKey = key; Table.sortDir = key === 'name' ? 1 : -1; }
        renderTable();
      });
    });
    $('tableSearch').addEventListener('input', () => { Table.page = 0; renderTable(); });
    $('tableLevel').addEventListener('change', () => { Table.page = 0; renderTable(); });
    $('tableCsvBtn').addEventListener('click', exportTableCSV);

    // state changes — recompute only what the change affects, only for the
    // visible view. Hidden tabs are marked dirty and refresh on entry.
    DIE.bus.on('state', ({ changed, transient }) => {
      const needsData = changed.includes('indicator');
      const needsGeo = changed.some((k) => ['extent', 'stateId', 'districtId'].includes(k));
      const needsDate = changed.includes('dateIdx');
      const needsPeriod = changed.includes('period');
      const needsMapCfg = changed.some((k) => ['map', 'colourMode', 'basemap'].includes(k));
      const onOverview = currentTab === 'overview';

      if (needsData) {
        busy(true);
        $('bootOverlay').classList.remove('is-hidden');
        setBoot('Loading indicator ' + DIE.indicatorById.get(DIE.state.indicator).label + '…', 60);
        DIE.loader.indicator(DIE.state.indicator)
          .then(() => {
            if (DIE.state.dateIdx < 0) DIE.state.dateIdx = currentDataset().dates.length - 1;
            setBoot('Ready', 100);
            // Every tab depends on the indicator, so all become stale.
            Object.keys(DIRTY).forEach(markDirty);
            renderAll();
            setTimeout(() => { $('bootOverlay').classList.add('is-hidden'); busy(false); }, 200);
          })
          .catch((err) => {
            $('bootOverlay').classList.add('is-hidden');
            busy(false);
            toast('Could not load indicator', String(err.message || err), 'error');
          });
        return;
      }

      // Slider drag: update only the cheap layers (map colours, KPI text,
      // selection and the animation frame). Charts wait for the final change.
      if (transient) {
        if (onOverview) {
          run(renderTopbar);
          if (needsDate) {
            run(() => DIE.MapView.refresh());
            run(renderKPIs);
            run(renderSelectedInfo);
            run(renderRegionSummary);
            if (Evo.ready) run(() => { Evo.frame = DIE.state.dateIdx; Evo.drawFrame(); });
          }
        }
        return;
      }

      if (needsMapCfg || needsGeo) {
        if (onOverview) run(() => { if (needsGeo) DIE.MapView.fitRegion(); DIE.MapView.refresh(); });
        else markDirty('overview');
      } else if (needsDate && onOverview) {
        run(() => DIE.MapView.refresh());
      }

      if (onOverview) {
        run(renderTopbar);
        if (needsGeo || needsDate) {
          run(renderKPIs);
          run(renderDistChart);
          run(renderSelectedInfo);
          run(renderRegionSummary);
        }
        if (needsGeo || needsPeriod || needsDate) run(renderTimeSeries);
        if (needsGeo || needsDate || needsPeriod) run(renderRanking);
        if (needsGeo || needsPeriod) run(() => Evo.render(true));
        else if (needsDate && Evo.ready) run(() => { Evo.frame = DIE.state.dateIdx; Evo.drawFrame(); });
      } else {
        markDirty('overview');
      }

      // Hidden analytical tabs: flag stale instead of computing off-screen.
      if (needsGeo || needsPeriod) {
        if (Historical.ready) {
          if (currentTab === 'historical') run(() => Historical.renderAll());
          else markDirty('historical');
        }
        if (EventsView.ready) {
          if (currentTab === 'events') run(() => EventsView.refresh());
          else markDirty('events');
        }
      }
      // Propagation analyses are date-independent (period/geography only).
      if (needsGeo || needsPeriod) {
        if (Propagation.ready) {
          if (currentTab === 'propagation') run(() => Propagation.refresh());
          else markDirty('propagation');
        }
      }

      if (window.innerWidth <= 1024) closeDrawer();
    });

    DIE.bus.on('dataset:loaded', () => run(renderTopbar));

    // Plotly starts in the background. When it finishes, redraw the visible
    // workspace so the "engine loading" placeholders are replaced.
    DIE.bus.on('lib:ready', (name) => {
      if (name !== 'Plotly' || !window.Plotly) return;
      if (Views[currentTab]) {
        DIRTY[currentTab] = false;
        run(() => Views[currentTab]());
      }
    });
    DIE.bus.on('lib:failed', (name) => {
      if (name !== 'Plotly') return;
      toast('Chart engine unavailable',
        'Charts cannot render, but maps, statistics, tables and exports remain fully functional.', 'warn');
      if (Views[currentTab]) run(() => Views[currentTab]());
    });

    window.addEventListener('resize', debounce(() => {
      if (!drawerMq.matches) closeDrawer();
      if (DIE.MapView.main) DIE.MapView.main.invalidateSize();
      ['durMap', 'sevMap', 'propMap', 'evtDetailMap', 'evoMap'].forEach((id) => {
        if (DIE.MapView[id]) DIE.MapView[id].invalidateSize();
      });
      if (Propagation.mapA) Propagation.mapA.invalidateSize();
      if (Propagation.mapB) Propagation.mapB.invalidateSize();
    }, 250));
  }

  function closeDrawer() {
    $('sidebar').classList.remove('is-open');
    $('navToggle').setAttribute('aria-expanded', 'false');
    $('scrim').hidden = true;
  }

  function openModal(scrim) {
    if (!scrim) return;
    scrim.hidden = false;
    const close = scrim.querySelector('[data-close]');
    if (close) close.focus();
  }
  function closeModal(scrim) {
    scrim.hidden = true;
    const opener = document.querySelector('[data-modal="' + scrim.id + '"]');
    if (opener) opener.focus();
  }

  /* ===================================================== STATIC TEXTS === */
  function renderStaticText() {
    $('chipUpdated').textContent = 'Updated · ' + DIE.meta.last_updated;

    // provenance banner — driven entirely by data_mode in metadata.json
    const demo = isDemo();
    const bpEl = $('bannerPeriod');
    if (bpEl) {
      const shortRecords = DIE.meta.indicators
        .filter((i) => i.available_from &&
          +i.available_from.slice(0, 4) > +DIE.meta.period.start.slice(0, 4) + 1)
        .map((i) => i.label + ' from ' + i.available_from.slice(0, 4));
      bpEl.textContent = (demo ? 'demonstration build' : 'research build') + ' · ' +
        DIE.meta.period.start.slice(0, 4) + '–' + DIE.meta.period.end.slice(0, 4) +
        (shortRecords.length ? ' · ' + shortRecords.join(' · ') : '');
    }
    $('bannerTitle').textContent = demo
      ? 'Demonstration dataset (synthetic).'
      : 'Historical research dataset.';
    $('bannerBody').textContent = demo
      ? 'All indicator values are generated by a seeded stochastic model to exercise the interface and methodology — they are not observed measurements and must not be cited as hydroclimatic evidence.'
      : 'District-month indicators are derived from CHIRPS precipitation, ERA5-Land evapotranspiration and soil moisture, and MODIS NDVI, aggregated with Google Earth Engine — they are model- and observation-based estimates, not operational monitoring products.';
    $('bannerLink').addEventListener('click', () => switchTab('data'));
    $('mapTag').textContent = demo ? 'synthetic demonstration data' : 'GEE-derived research data';
    ['kpiTag1', 'kpiTag2', 'kpiTag3', 'kpiTag4'].forEach((id) => {
      const el = $(id);
      el.textContent = demo ? 'SYN' : 'GEE';
      el.title = demo
        ? 'Value derived from the synthetic demonstration dataset'
        : 'Value derived from the GEE-based historical dataset';
    });

    $('aboutDataMode').innerHTML = demo
      ? '<strong>This build ships a synthetic demonstration dataset</strong> (seeded stochastic generator, seed ' +
        DIE.meta.random_seed + ') processed end-to-end by the reference pipeline to validate the indicator ' +
        'computations, event identification and export chain. Values are not observed measurements. The data layer ' +
        'remains a documented, swappable contract: the static CSVs under <span class="mono">data/drought/</span> can ' +
        'be replaced with a real Earth-Engine extract without code changes (see README and ' +
        '<span class="mono">data-pipeline/docs/gee-update-guide.md</span>).'
      : '<strong>This build ships a historical research dataset</strong> derived with Google Earth Engine from CHIRPS, ERA5-Land and MODIS MOD13A3. SPI, SPEI and the soil-moisture anomaly cover January 1981 to December 2025; the Vegetation Condition Index starts in February 2000 (MODIS record). The data layer is a documented, swappable contract.';

    if ($('chipDataMode')) {
      $('chipDataMode').textContent = 'Data mode · ' +
        (DIE.meta.data_mode === 'static-research' ? 'Static research data'
          : DIE.meta.data_mode === 'static-demonstration' ? 'Static demonstration data (synthetic)'
          : DIE.meta.data_mode);
    }

    let versionText = 'Methodology version ' + DIE.meta.methodology_version +
      ' · data mode: ' + DIE.meta.data_mode + ' · generated ' + DIE.meta.last_updated;
    if (DIE.meta.random_seed !== null && DIE.meta.random_seed !== undefined) {
      versionText += ' (numpy default_rng, seed ' + DIE.meta.random_seed + ')';
    }
    $('methVersion').textContent = versionText;
    $('methCitation').textContent = DIE.meta.citation;
    $('methReferencePeriod').textContent = DIE.meta.reference_period;
    $('aboutCitation').textContent = DIE.meta.citation;
    $('aboutDataModeTab').innerHTML = $('aboutDataMode').innerHTML;
    $('aboutCitationTab').textContent = DIE.meta.citation;
    $('footerProvenance').textContent = DIE.meta.data_provenance;
    $('footerDisclaimer').textContent = DIE.meta.disclaimer;
    $('footerVersion').textContent = 'v' + DIE.meta.version + ' · methodology ' + DIE.meta.methodology_version +
      ' · ' + (demo ? 'demonstration build (synthetic data)' : 'historical research build (GEE-derived data)');

    // methodology classification table
    const spi = DIE.indicatorById.get('spi_3');
    const rowsHtml = spi.classes.map((c) =>
      '<tr><td><span class="sw" style="background:' + c.color + '"></span>' + c.label + '</td>' +
      '<td class="mono">' + fmtRangeLoose(c, spi) + '</td></tr>').join('');
    $('methClassTable').innerHTML =
      '<thead><tr><th>SPI / SPEI class</th><th>Value range (z-score)</th></tr></thead><tbody>' + rowsHtml + '</tbody>' +
      '<tbody>' + ['sma', 'vci'].map((k) => {
        const ind = DIE.indicatorById.get(k);
        return '<tr><td colspan="2" style="background:#FAFBFC"><b>' + ind.label + '</b> (' + ind.units +
          '): ' + ind.classes.map((c) => c.label + ' ' + fmtRangeLoose(c, ind)).join(' · ') + '</td></tr>';
      }).join('') + '</tbody>';

    $('sidebarFootMeta') && ($('sidebarFootMeta').textContent = '');
    $('footPeriod').textContent = 'Observations ' + DIE.meta.period.start + ' – ' + DIE.meta.period.end;
    $('footRes').textContent = DIE.meta.temporal_resolution + ' · ' + DIE.meta.spatial_units;
    $('footMode').textContent = isDemo()
      ? 'Demonstration dataset (synthetic · seed ' + DIE.meta.random_seed + ')'
      : 'Data mode: ' + DIE.meta.data_mode;
  }

  function fmtRangeLoose(c, ind) {
    const dec = ind.family === 'land' ? 0 : 2;
    const f = (v) => (v === null || v === undefined ? '' : v.toFixed(dec).replace('-', '−'));
    if (c.min === null || c.min === undefined) return '≤ ' + f(c.max);
    if (c.max === null || c.max === undefined) return '≥ ' + f(c.min);
    return f(c.min) + ' to ' + f(c.max);
  }

  /* ====================================================== TOPBAR CHIPS == */
  function renderTopbar() {
    const ds = currentDataset();
    const ym = DIE.Filters.dateYm();
    $('chipDate').textContent = 'View · ' + (ym ? DIE.dates.label(ym) : '—');
    $('chipAvail').textContent = 'Availability · ' + (ds
      ? (ds.report.completeness * 100).toFixed(1) + '% valid' : '—');

    const note = $('indicatorAvailability');
    if (ds && note) {
      const from = ds.availableFrom || DIE.meta.period.start;
      const to = ds.availableTo || DIE.meta.period.end;
      const fullRecord = from.slice(0, 4) <= DIE.meta.period.start.slice(0, 4);
      note.textContent = fullRecord
        ? 'Available ' + DIE.dates.label(from) + ' – ' + DIE.dates.label(to) + ' (full record)'
        : 'Available ' + DIE.dates.label(from) + ' – ' + DIE.dates.label(to) +
          ' · source record begins ' + from.slice(0, 4);
      $('chipAvail').title = ds.indicator.label + ' has valid values from ' +
        DIE.dates.label(from) + ' to ' + DIE.dates.label(to) + '.';
    }
  }

  /* ============================================== VIEW 1 · OVERVIEW ===== */
  function renderKPIs() {
    const ds = currentDataset();
    if (!ds) return;
    const regionIds = ids();
    const s = A().regionStats(ds, DIE.state.dateIdx, regionIds);

    const ind = ds.indicator;
    const ymLabel = DIE.dates.label(DIE.Filters.dateYm() || '');

    setKpi('kpiArea', {
      value: Number.isFinite(s.affectedArea) ? DIE.fmt.area(s.affectedArea) : 'N/A',
      share: 'of ' + DIE.fmt.area(s.totalArea) + ' · ' + DIE.fmt.pct(s.affectedPct),
      delta: deltaHtml(s),
      foot: 'Mild drought or worse · ' + ymLabel
    });

    setKpi('kpiSevere', {
      value: Number.isFinite(s.severeArea) ? DIE.fmt.area(s.severeArea) : 'N/A',
      share: 'of ' + DIE.fmt.area(s.totalArea) + ' · ' + DIE.fmt.pct(s.severePct),
      foot: 'Severe + extreme classes · ' + ymLabel
    });

    const c = s.meanClass;
    $('kpiIntensity').querySelector('[data-value]').textContent = DIE.fmt.val(s.mean, ind);
    $('kpiIntensity').querySelector('[data-value]').classList.toggle('is-na', !Number.isFinite(s.mean));
    $('kpiIntensity').querySelector('[data-class]').innerHTML =
      (c ? '<span class="cat-chip" style="background:' + c.color + '">' + c.label + '</span>' : '—') +
      ' <span class="small">(' + ind.label + ', ' + ind.units + ')</span>';
    $('kpiIntensity').querySelector('[data-agg]').textContent =
      'Area-weighted mean · ' + (Number.isFinite(s.n) ? Math.round(s.n) : 0) + '/' + s.districtsTotal +
      ' districts with data · ' + ymLabel;

    const dVal = $('kpiDistricts');
    dVal.querySelector('[data-value]').textContent =
      (Number.isFinite(s.nDrought) ? Math.round(s.nDrought) : 'N/A') + ' / ' + s.districtsTotal;
    dVal.querySelector('[data-severe]').innerHTML =
      '<b style="color:#8F252F">' + (Number.isFinite(s.nSevere) ? Math.round(s.nSevere) : 'N/A') +
      '</b> under severe or extreme drought';
    dVal.querySelector('[data-coverage]').textContent =
      'districts in drought · ' + ymLabel;

    $('mapPanelMeta').textContent = ind.label + ' · ' + DIE.Filters.regionLabel() + ' · ' + ymLabel;
  }

  function setKpi(id, o) {
    const card = $(id);
    const v = card.querySelector('[data-value]');
    v.textContent = o.value;
    v.classList.toggle('is-na', o.value === 'N/A');
    card.querySelector('[data-share]').textContent = o.share || '';
    if (o.delta !== undefined) card.querySelector('[data-delta]').innerHTML = o.delta;
    if (o.foot) card.querySelector('.kpi-foot').textContent = o.foot;
  }

  function deltaHtml(s) {
    if (!s.prev) return '<span class="flat">— first available observation</span>';
    const dArea = s.affectedArea - s.prev.affectedArea;
    const dPct = (s.affectedPct || 0) - (s.prev.affectedPct || 0);
    if (!Number.isFinite(dArea) || Math.abs(dArea) < 1) {
      return '<span class="flat">no change vs ' + DIE.dates.label(currentDataset().dates[s.prevDateIdx]) + '</span>';
    }
    const up = dArea > 0;
    return '<span class="' + (up ? 'up' : 'down') + '">' + (up ? '▲ +' : '▼ ') +
      DIE.fmt.int.format(Math.round(Math.abs(dArea))) + ' km² (' +
      (up ? '+' : '−') + Math.abs(dPct).toFixed(1) + ' pp)</span>' +
      '<span class="flat"> vs ' + DIE.dates.label(currentDataset().dates[s.prevDateIdx]) + '</span>';
  }

  function renderSelectedInfo() {
    const ds = currentDataset();
    const box = $('selectedInfo');
    const btn = $('clearSelectionBtn');
    const id = DIE.state.districtId;
    if (!id || !ds) {
      box.innerHTML = '<p class="side-note">Click a district on the map, or choose one in the filter panel.</p>';
      btn.hidden = true;
      return;
    }
    const d = DIE.registry.districts.get(id);
    const i = ds.districtIndex.get(id);
    const v = (i === undefined) ? NaN : ds.values[i][DIE.state.dateIdx];
    const c = DIE.classify(v, ds.indicator);
    const comp = DIE.MapView.districtCompleteness(ds, id);
    box.innerHTML =
      '<div class="sel-name">' + d.name + '</div>' +
      '<div class="sel-state">' + d.state + '</div>' +
      '<div class="sel-grid">' +
      '<div><div class="k">' + ds.indicator.label + '</div><div class="v">' + DIE.fmt.val(v, ds.indicator) + '</div></div>' +
      '<div><div class="k">Class</div><div class="v">' + (c ? c.label : 'No data') + '</div></div>' +
      '<div><div class="k">District area</div><div class="v">' + DIE.fmt.int.format(Math.round(d.area)) + ' km²</div></div>' +
      '<div><div class="k">Availability</div><div class="v">' + (comp * 100).toFixed(0) + '%</div></div>' +
      '</div>' +
      '<p class="rail-note">All tabs now focus on this district.</p>';
    btn.hidden = false;
  }

  function renderRegionSummary() {
    const ds = currentDataset();
    if (!ds) return;
    const regionIds = ids();
    const s = A().regionStats(ds, DIE.state.dateIdx, regionIds);
    const label = DIE.Filters.regionLabel();
    const c = s.meanClass;

    $('regionSummary').innerHTML =
      '<div class="rs-row"><span class="rs-k">Region</span><span class="rs-v">' + label + '</span></div>' +
      '<div class="rs-row"><span class="rs-k">Districts with data</span><span class="rs-v">' +
      s.n + ' / ' + s.districtsTotal + '</span></div>' +
      '<div class="rs-row"><span class="rs-k">Region area</span><span class="rs-v">' + DIE.fmt.area(s.totalArea) + '</span></div>' +
      '<div class="rs-row"><span class="rs-k">Area-weighted mean</span><span class="rs-v">' +
      DIE.fmt.val(s.mean, ds.indicator) + ' ' + (c ? '· ' + c.label : '') + '</span></div>' +
      '<div class="rs-row"><span class="rs-k">Affected area</span><span class="rs-v">' +
      DIE.fmt.pct(s.affectedPct) + ' · ' + DIE.fmt.int.format(Math.round(s.affectedArea)) + ' km²</span></div>' +
      '<div class="rs-row"><span class="rs-k">Severe + extreme</span><span class="rs-v">' +
      DIE.fmt.pct(s.severePct) + ' · ' + DIE.fmt.int.format(Math.round(s.severeArea)) + ' km²</span></div>' +
      '<p class="rail-note">Full ranking: see the Most-affected-districts panel below and the Historical tab.</p>';
  }

  function renderTimeSeries() {
    const ds = currentDataset();
    if (!ds) return;
    const regionIds = ids();
    const isDistrict = !!DIE.state.districtId;
    const series = isDistrict
      ? A().districtSeries(ds, DIE.state.districtId)
      : A().regionSeries(ds, regionIds);
    const label = DIE.Filters.regionLabel() + (isDistrict ? '' : ' (area-weighted mean)');

    let trend = null;
    const chk = $('tsTrendChk');
    const validN = series.pts.filter((p) => p.v !== null).length;
    chk.disabled = validN < 120;
    chk.parentElement.title = validN < 120
      ? 'Requires ≥ 120 valid observations (currently ' + validN + ')'
      : 'Ordinary least squares fit over valid months';
    if (chk.checked && validN >= 120) {
      const xs = [], ys = [];
      series.pts.forEach((p, j) => { if (p.v !== null) { xs.push(j); ys.push(p.v); } });
      const fit = A().ols(xs, ys);
      if (fit) trend = { ...fit, intercept: fit.intercept + fit.slope * xs[0], n: fit.n };
    }

    DIE.Charts.timeSeries($('tsChart'), { series, indicator: ds.indicator, regionLabel: label, trend });
    $('tsMeta').textContent = ds.indicator.label + ' · ' + label + ' · ' +
      (ds.availableFrom || DIE.meta.period.start) + '–' +
      (ds.availableTo || DIE.meta.period.end);
    $('tsFoot').textContent =
      'Solid grey: zero reference. Dotted red: drought-class thresholds (' +
      DIE.Charts.DIST_BINS.filter((b) => /drought/.test(b.key)).map((b) => b.label).join(', ') +
      '). Gaps are missing observations (never interpolated). ' +
      (trend ? 'Dashed red: OLS trend, slope ' + trend.slope.toFixed(4) + ' units/month over ' + trend.n +
        ' valid months (descriptive; inferential tests live in the Historical tab). ' : '') +
      'Spatial unit: district' + (isDistrict ? '' : 's, area-weighted') + '. Source: ' +
      (isDemo() ? 'demonstration dataset (synthetic)' : 'GEE-derived historical dataset') + '.';
  }

  function renderDistChart() {
    const ds = currentDataset();
    if (!ds) return;
    const regionIds = ids();
    const dist = A().severityDistribution(ds, DIE.state.dateIdx, regionIds);
    DIE.Charts.severityBars($('distChart'), { ...dist, indicator: ds.indicator });
    $('distMeta').textContent = DIE.Filters.regionLabel() + ' · ' + DIE.dates.label(DIE.Filters.dateYm() || '');
    $('distFoot').textContent =
      'Share of region area per severity class (' + DIE.fmt.area(dist.regionArea) +
      ' total). Wet conditions aggregate all wet classes. Source: ' +
      (isDemo() ? 'demonstration data (synthetic).' : 'GEE-derived historical data.');
  }

  /** Top-10 drought-affected districts at the current date. */
  function renderRanking() {
    const ds = currentDataset();
    if (!ds) return;
    const regionIds = ids();
    const byArea = (document.querySelector('input[name="rankBy"]:checked') || {}).value === 'area';
    const rows = regionIds.map((id) => {
      const d = DIE.registry.districts.get(id);
      const i = ds.districtIndex.get(id);
      const v = (i === undefined) ? NaN : ds.values[i][DIE.state.dateIdx];
      return { id, v, d };
    }).filter((r) => r.d && Number.isFinite(r.v));

    let top;
    if (byArea) {
      // sort districts in drought (mild or worse) by area descending
      top = rows.filter((r) => DIE.isDroughtClass(DIE.classify(r.v, ds.indicator)))
        .sort((a, b) => b.d.area - a.d.area).slice(0, 10);
    } else {
      top = rows.sort((a, b) => a.v - b.v).slice(0, 10);
    }

    const chartRows = top.map((r) => {
      const c = DIE.classify(r.v, ds.indicator);
      return {
        name: r.d.name, value: r.v, area: r.d.area,
        color: c ? c.color : '#9AA7B5',
        classLabel: c ? c.label : 'no data'
      };
    });
    DIE.Charts.rankingBars($('rankChart'), { rows: chartRows, byArea, indicator: ds.indicator });
    $('rankMeta').textContent = ds.indicator.label + ' · ' + DIE.Filters.regionLabel() + ' · ' +
      DIE.dates.label(DIE.Filters.dateYm() || '');
    $('rankFoot').textContent = byArea
      ? 'Largest districts currently in mild-or-worse drought (equal-area km²).'
      : 'Lowest indicator values (most severe conditions) at the selected date; colour = drought class.';
  }

  /* ------------------------------------- Drought evolution (map + play) -- */
  /**
   * Animated drought evolution: dedicated choropleth (separate from the main
   * map so its zoom/pan state is untouched), area-in-drought timeline, frame
   * statistics and playback (play/pause, step, speed). The animation drives
   * only the evolution view — the global observation date stays put until the
   * user scrubs the evolution slider, which then syncs the whole dashboard.
   */
  const Evo = {
    ready: false,
    playing: false,
    timer: null,
    speed: 600,
    frame: -1,          // local animation frame (not DIE.state.dateIdx)

    init() {
      if (this.ready) return;
      this.ready = true;
      const mk = () => DIE.MapView.createChoropleth('evoMap', {
        basemap: 'plain',
        onDistrictClick: (id) => {
          const d = DIE.registry.districts.get(id);
          if (d) DIE.Filters.set({ extent: 'district', stateId: d.sid, districtId: id });
        }
      });
      DIE.MapView.evoMap = mk();

      // synchronised playback controls
      $('evoPlay').addEventListener('click', () => this.togglePlay());
      $('evoPrev').addEventListener('click', () => { this.pause(); this.step(-1); });
      $('evoNext').addEventListener('click', () => { this.pause(); this.step(1); });
      $('evoSpeed').addEventListener('change', (e) => {
        this.speed = +e.target.value;
        if (this.playing) { this.pause(); this.play(); }
      });
      const slider = $('evoSlider');
      slider.addEventListener('input', () => {
        this.pause();
        const ds = currentDataset();
        if (!ds) return;
        const idx = Math.min(ds.dates.length - 1, Math.max(0, +slider.value));
        // scrubbing the record syncs the global observation date
        DIE.Filters.set({ dateIdx: idx });
      });
      document.addEventListener('visibilitychange', () => { if (document.hidden) this.pause(); });
      this.render(true);
    },

    togglePlay() { this.playing ? this.pause() : this.play(); },

    play() {
      const ds = currentDataset();
      if (!ds) return;
      // loop from the start when the record is exhausted
      if (this.frame < 0 || this.frame >= ds.dates.length - 1) this.frame = 0;
      this.playing = true;
      $('evoPlay').textContent = 'Pause';
      $('evoPlay').setAttribute('aria-label', 'Pause animation');
      this.timer = setInterval(() => this.step(1), this.speed);
    },

    pause() {
      this.playing = false;
      if (this.timer) { clearInterval(this.timer); this.timer = null; }
      const b = $('evoPlay');
      if (b) { b.textContent = 'Play'; b.setAttribute('aria-label', 'Play animation'); }
    },

    step(dir) {
      const ds = currentDataset();
      if (!ds) { this.pause(); return; }
      if (this.frame < 0) this.frame = DIE.state.dateIdx >= 0 ? DIE.state.dateIdx : ds.dates.length - 1;
      this.frame = Math.min(ds.dates.length - 1, Math.max(0, this.frame + dir));
      if (this.frame === 0 || this.frame === ds.dates.length - 1) this.pause();
      this.drawFrame();
    },

    /** Repaint one animation frame (map colours, corner date, timeline marker). */
    drawFrame() {
      const ds = currentDataset();
      const evoMap = DIE.MapView.evoMap;
      if (!ds || !evoMap) return;
      const idx = this.frame;
      evoMap.applyData(ds, idx, DIE.state.colourMode, null);
      $('evoDate').textContent = DIE.dates.label(ds.dates[idx]);
      $('evoMapTag').textContent = isDemo() ? 'synthetic demonstration data' : 'GEE-derived research data';
      const slider = $('evoSlider');
      if (+slider.value !== idx) slider.value = idx;

      // frame snapshot: affected share + weighted mean
      const s = A().regionStats(ds, idx, ids());
      $('evoFrameStats').innerHTML =
        '<b>' + DIE.dates.label(ds.dates[idx]) + '</b><br>' +
        'Area in drought: <b>' + DIE.fmt.pct(s.affectedPct) + '</b><br>' +
        'Severe + extreme: <b>' + DIE.fmt.pct(s.severePct) + '</b><br>' +
        'Area-weighted mean: <b>' + DIE.fmt.val(s.mean, ds.indicator) + '</b> ' + ds.indicator.units;
    },

    /** Full refresh (indicator / geography / period change). */
    render(fit) {
      if (!this.ready) return;
      const ds = currentDataset();
      const evoMap = DIE.MapView.evoMap;
      if (!ds || !evoMap) return;
      const slider = $('evoSlider');
      slider.max = String(ds.dates.length - 1);

      // default the animation frame to the current observation date
      this.frame = DIE.state.dateIdx >= 0 ? DIE.state.dateIdx : ds.dates.length - 1;
      if (fit) evoMap.fitRegion(DIE.Filters.regionType(), DIE.state.districtId || DIE.state.stateId);
      this.drawFrame();

      // timeline of % area in drought + current marker
      const series = A().droughtAreaPctSeries(ds, ids());
      DIE.Charts.areaTimeline($('evoTimeline'), {
        dates: series.dates, pct: series.pct, frameIdx: this.frame
      });

      // legend mirrors the main-map legend for the current colour mode
      DIE.MapView.renderLegend($('evoLegend'), ds.indicator, DIE.state.colourMode, {
        note: ds.indicator.family === 'land'
          ? 'Indicator-specific thresholds (' + ds.indicator.label + '); see methodology.'
          : 'Thresholds: McKee et al. (1993) / Vicente-Serrano et al. (2010) convention.'
      });

      $('evoPanelMeta').textContent = ds.indicator.label + ' · ' + DIE.Filters.regionLabel() +
        ' · share of region area in mild-or-worse drought · missing months are never interpolated';
      $('evoFoot').textContent = ds.indicator.label + ' · ' + DIE.Filters.regionLabel() +
        ' · press Play to animate the full record (use the speed selector for slower/faster playback); ' +
        'drag the slider to set the observation date for the whole dashboard; ' +
        (isDemo() ? 'demonstration data (synthetic)' : 'GEE-derived research data') + '.';
    }
  };

  /* =========================================== VIEW 2 · HISTORICAL ===== */
  const Historical = {
    ready: false,

    init() {
      if (this.ready) return;
      this.ready = true;
      // statistic choropleths via the shared factory
      const mk = (id, name) => DIE.MapView.createChoropleth(id, { noScroll: false });
      DIE.MapView.durMap = mk('durMap');
      DIE.MapView.sevMap = mk('sevMap');
      setTimeout(() => {
        DIE.MapView.durMap && DIE.MapView.durMap.invalidateSize();
        DIE.MapView.sevMap && DIE.MapView.sevMap.invalidateSize();
      }, 60);
      this.renderAll();
    },

    renderAll() {
      this.renderSummary();
      this.renderFrequency();
      this.renderMaps();
      this.renderTrend();
      this.renderRecurrence();
      renderTable();
    },

    renderSummary() {
      const ds = currentDataset();
      if (!ds) return;
      const h = A().historicalSummary(ds, ids(), DIE.state.period, DIE.state.period.season);
      const label = DIE.Filters.regionLabel();

      $('histMeta').textContent = ds.indicator.label + ' · ' + label;
      $('histScope').textContent = periodLabel();
      $('histStats').innerHTML =
        statCell(h.droughtMonths, 'months in drought (of ' + h.validScopeMonths + ' valid)') +
        statCell(h.nEvents, 'drought events (runs ≥ 3 months)') +
        statCell(DIE.fmt.pct(h.droughtMonths / Math.max(1, h.validScopeMonths) * 100), '% of valid months') +
        statCell(h.severity.total.toFixed(1), 'cumulative severity (Σ deficit)');
      $('histNote').textContent = 'Event definition (default methodology): runs analysis — ≥ 3 consecutive months with ' +
        ds.indicator.label + ' ≤ ' + h.threshold.toString().replace('-', '−') +
        ' (upper bound of the moderate-drought class). Severity = cumulative deficit below the truncation level; ' +
        'intensity = severity ÷ duration. Season filter applies to frequency statistics only.';
      this._h = h;
    },

    renderFrequency() {
      const ds = currentDataset();
      if (!ds) return;
      const h = this._h || A().historicalSummary(ds, ids(), DIE.state.period, DIE.state.period.season);
      const label = DIE.Filters.regionLabel();

      $('freqMeta').textContent = label + ' · ' + periodLabel();
      $('freqStats').innerHTML =
        '<span class="stat"><b>' + h.droughtMonths + '</b><i>months in drought (of ' + h.validScopeMonths + ' valid)</i></span>' +
        '<span class="stat"><b>' + h.nEvents + '</b><i>drought events (runs ≥ 3 months)</i></span>' +
        '<span class="stat"><b>' + DIE.fmt.pct(h.droughtMonths / Math.max(1, h.validScopeMonths) * 100) + '</b><i>of valid months</i></span>';
      DIE.Charts.frequencyByYear($('freqChart'), { years: h.years, counts: h.counts });

      // district-wise frequency histogram (share of months in drought)
      const stats = A().districtStats(ds, ids(), DIE.state.period, { season: DIE.state.period.season });
      const freqs = stats.map((s) => s.droughtPct).filter(Number.isFinite);
      if (freqs.length) {
        const bins = [];
        for (let lo = 0; lo < 100; lo += 10) bins.push(lo);
        const counts = bins.map((lo) => freqs.filter((f) => f >= lo && f < lo + 10).length);
        const nTail = freqs.filter((f) => f >= 100).length;
        if (window.Plotly) {
          Plotly.react($('freqDistChart'), [{
            type: 'bar',
            x: bins.map((lo) => lo + '–' + (lo + 10)).concat(nTail ? ['100'] : []),
            y: counts.concat(nTail ? [nTail] : []),
            marker: { color: '#B94747' },
            hovertemplate: '<b>%{x}%</b><br>%{y} districts<extra></extra>'
          }], {
            font: { family: 'Inter, sans-serif', size: 11, color: '#1F2937' },
            margin: { l: 34, r: 10, t: 8, b: 30 },
            paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: '#FFFFFF',
            xaxis: { title: { text: '% of valid months in drought', font: { size: 10, color: '#687588' } }, gridcolor: '#F0F3F7', linecolor: '#CBD5E1', tickfont: { size: 9 } },
            yaxis: { title: { text: 'districts', font: { size: 9.5, color: '#687588' } }, gridcolor: '#E2E7EE', linecolor: '#CBD5E1', rangemode: 'tozero' }
          }, { responsive: true, displaylogo: false, modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'] });
        }
      }
      $('freqFoot').textContent = 'Left: months below the truncation level per year (season filter applies). ' +
        'Right: distribution across districts of the share of valid months in drought.';
    },

    renderMaps() {
      const ds = currentDataset();
      if (!ds || !this.ready) return;
      const stats = A().districtStats(ds, ids(), DIE.state.period, { season: DIE.state.period.season });
      const label = DIE.Filters.regionLabel();
      const pl = periodLabel();

      // duration map + stats
      const durs = stats.filter((s) => Number.isFinite(s.meanDuration));
      const durLo = durs.length ? Math.min(...durs.map((s) => s.meanDuration)) : 0;
      const durHi = durs.length ? Math.max(...durs.map((s) => s.meanDuration)) : 1;
      $('durMeta').textContent = label + ' · ' + pl;
      $('durStats').innerHTML =
        statCell(fmtN(stats, 'meanDuration', 2), 'mean event duration (months)') +
        statCell(fmtN(stats, 'maxDuration', 0), 'max event duration (months)') +
        statCell(fmtN(stats, 'meanSeverity', 1), 'mean event severity');
      $('durNote').innerHTML = 'Mean event duration per district (complete events only; censored events excluded). ' +
        DIE.Charts.statLegendHtml('Mean duration', ' mo', durLo, durHi, DIE.Charts.statRampWarm);

      const durMapObj = DIE.MapView.durMap;
      if (durMapObj) {
        durMapObj.applyData(null, 0, 'classes', DIE.state.districtId, (id) => {
          const s = stats.find((x) => x.id === id);
          return s && Number.isFinite(s.meanDuration) ? s.meanDuration : NaN;
        }, (id) => {
          const s = stats.find((x) => x.id === id);
          return DIE.Charts.statRampWarm(s && Number.isFinite(s.meanDuration) ? s.meanDuration : NaN, durLo, Math.max(durHi, durLo + 0.01));
        });
      }

      // severity map + stats
      const sevs = stats.filter((s) => Number.isFinite(s.cumulativeSeverity));
      const sevLo = sevs.length ? Math.min(...sevs.map((s) => s.cumulativeSeverity)) : 0;
      const sevHi = sevs.length ? Math.max(...sevs.map((s) => s.cumulativeSeverity)) : 1;
      $('sevMeta').textContent = label + ' · ' + pl;
      $('sevStats').innerHTML =
        statCell(fmtN(stats, 'meanSeverity', 2), 'mean event severity') +
        statCell(fmtN(stats, 'maxSeverity', 1), 'max event severity') +
        statCell(sum(stats, 'cumulativeSeverity', 1), 'cumulative severity (Σ)');
      $('sevNote').innerHTML = 'Cumulative event severity per district (Σ deficit over complete events). ' +
        DIE.Charts.statLegendHtml('Cumulative severity', '', sevLo, sevHi, DIE.Charts.statRampWarm);

      const sevMapObj = DIE.MapView.sevMap;
      if (sevMapObj) {
        sevMapObj.applyData(null, 0, 'classes', DIE.state.districtId, (id) => {
          const s = stats.find((x) => x.id === id);
          return s && Number.isFinite(s.cumulativeSeverity) ? s.cumulativeSeverity : NaN;
        }, (id) => {
          const s = stats.find((x) => x.id === id);
          return DIE.Charts.statRampWarm(s && Number.isFinite(s.cumulativeSeverity) ? s.cumulativeSeverity : NaN, sevLo, Math.max(sevHi, sevLo + 0.01));
        });
      }

      function fmtN(rows, key, dec) {
        const vals = rows.map((r) => r[key]).filter(Number.isFinite);
        return vals.length ? (A().mean(vals)).toFixed(dec) : '—';
      }
      function sum(rows, key, dec) {
        const vals = rows.map((r) => r[key]).filter(Number.isFinite);
        return vals.length ? vals.reduce((a, b) => a + b, 0).toFixed(dec) : '—';
      }
    },

    renderTrend() {
      const ds = currentDataset();
      if (!ds) return;
      const gran = (document.querySelector('input[name="trendGran"]:checked') || {}).value || 'annual';
      const ts = A().trendSeries(ds, ids(), DIE.state.period, {
        granularity: gran, season: DIE.state.period.season
      });
      const label = DIE.Filters.regionLabel();

      // drop NaNs for the tests (chronological order preserved)
      const xs = [], vals = [];
      ts.values.forEach((v, i) => {
        if (Number.isFinite(v)) { xs.push(i); vals.push(v); }
      });

      let sen = null, mk = null;
      if (vals.length >= 4) {
        sen = S().senSlope(vals, 0.10);
        mk = S().mannKendall(vals, sen.slope);
      }

      // intercept for plotting: mean-centred
      if (sen && Number.isFinite(sen.slope)) {
        const m = S().mean(vals);
        sen.intercept = m - sen.slope * (xs.length ? xs[Math.floor(xs.length / 2)] : 0);
      }

      DIE.Charts.trendChart($('trendChart'), {
        keys: ts.keys, values: ts.values, granularity: gran,
        indicator: ds.indicator, label, sen
      });

      $('trendMeta').textContent = ds.indicator.label + ' · ' + label + ' · ' + periodLabel();
      const st = $('trendStats');
      if (!mk || !sen || !Number.isFinite(sen.slope)) {
        st.innerHTML = '<p class="side-note">Fewer than 4 valid ' +
          (gran === 'annual' ? 'years' : 'months') + ' in the analysis period — trend tests require at least 4.</p>';
      } else {
        const sig = mk.p < 0.001 ? 'p < 0.001' : 'p = ' + mk.p.toFixed(3);
        const sigClass = mk.p < 0.05 ? '<span class="vr-ok">' : '<span>';
        st.innerHTML =
          '<div class="stat-grid">' +
          statCell(sen.slope.toFixed(4), "Sen's slope (per " + (gran === 'annual' ? 'year' : 'month') + ')') +
          statCell('[' + sen.ci[0].toFixed(4) + ', ' + sen.ci[1].toFixed(4) + ']', '90% confidence interval') +
          statCell(mk.Z.toFixed(2), 'Mann-Kendall Z') +
          statCell(sigClass + sig + '</span>', 'two-sided significance') +
          statCell(String(mk.n), 'valid ' + (gran === 'annual' ? 'years' : 'months') + ' (n)') +
          statCell(mk.hr.applied ? 'yes (n* = ' + mk.hr.nEff.toFixed(1) + ')' : 'not triggered',
            'Hamed–Rao autocorrelation correction') +
          '</div>' +
          '<p class="rail-note">' +
          (mk.hr.applied
            ? 'Significant serial autocorrelation detected; the reported Z and p use the Hamed–Rao corrected variance. ' +
              (mk.hr.significantLags.slice(0, 4).map((l) => 'r' + l.k + '=' + l.r.toFixed(2)).join(', ')) + ' without correction: ' +
              'Z = ' + S().mannKendall(vals).Z.toFixed(2) + '. '
            : 'No significant serial autocorrelation at the 5% level; the plain Mann-Kendall variance is valid. ') +
          (mk.p < 0.05
            ? 'The ' + (gran === 'annual' ? 'annual' : 'monthly') + ' series shows a statistically significant ' +
              (sen.slope < 0 ? 'declining (drying)' : 'rising (wetting)') + ' tendency over ' + periodLabel() + '.'
            : 'No statistically significant tendency at the 5% level over ' + periodLabel() + ' — the Sen slope is a descriptive estimate only.') +
          '</p>';
      }
      $('trendFoot').textContent = 'Non-parametric Mann-Kendall test with tie-corrected variance; Sen slope = median pairwise slope with rank-based 90% CI (Gilbert 1987). ' +
        'When significant autocorrelation exists the Hamed–Rao (1998) variance correction is applied (effective sample size n*). ' +
        'Default input: annual area-weighted means over the analysis period' +
        (DIE.state.period.season === 'all' ? '' : ' restricted to the selected season') + '.';
    },

    renderRecurrence() {
      const ds = currentDataset();
      if (!ds) return;
      const h = this._h || A().historicalSummary(ds, ids(), DIE.state.period, DIE.state.period.season);
      const rec = A().recurrenceStats(h.events, DIE.state.period);
      $('recurMeta').textContent = DIE.Filters.regionLabel() + ' · ' + periodLabel();

      const rp = rec.returnPeriods.map((r) =>
        statCell(Number.isFinite(r.returnPeriod) ? r.returnPeriod.toFixed(1) + ' yr' : '—',
          'severity ≥ Q' + Math.round(r.quantile * 100) + ' (' + r.threshold.toFixed(1) + ') · ' + r.nExceeding + ' events'));
      $('recurStats').innerHTML =
        statCell(rec.nEvents, 'events identified') +
        statCell(Number.isFinite(rec.meanInterArrival) ? rec.meanInterArrival.toFixed(1) : '—', 'mean inter-arrival (months)') +
        statCell(Number.isFinite(rec.medianInterArrival) ? rec.medianInterArrival : '—', 'median inter-arrival (months)') +
        rp.join('');
      $('recurFoot').textContent = 'Empirical, non-parametric recurrence on the regional series: return period = ' +
        'observation years ÷ number of events reaching the severity quantile. No fitted distribution is assumed; ' +
        'with ' + h.nEvents + ' events these estimates carry wide, unquantified uncertainty and are indicative only.';
    }
  };

  function statCell(v, label) {
    const shown = (v === null || v === undefined || (typeof v === 'number' && !Number.isFinite(v))) ? '—' : v;
    return '<div class="stat-cell"><b>' + shown + '</b><i>' + label + '</i></div>';
  }

  /* ============================================= VIEW 3 · EVENTS ===== */
  const EventsView = {
    ready: false,
    sortKey: 'start', sortDir: -1, page: 0, pageSize: 15,
    cat: null, selected: null,

    init() {
      if (this.ready) return;
      this.ready = true;
      this.refresh();
    },

    refresh() {
      const ds = currentDataset();
      if (!ds) return;
      deferBusy(() => this.refreshNow());
    },

    refreshNow() {
      const ds = currentDataset();
      if (!ds) return;
      const thrSel = $('evtThreshold').value;
      const ind = ds.indicator;
      const defaultThr = A().droughtThreshold(ind);
      // Threshold options are z-score style; for land indicators the select
      // values are interpreted relative to the indicator's own class table.
      let threshold;
      if (thrSel === 'default') threshold = defaultThr;
      else if (ind.family === 'land') {
        // map z-style options to the indicator's own class bounds
        const map = { '-0.5': 'mild_drought', '-1.0': 'moderate_drought', '-1.5': 'severe_drought', '-2.0': 'extreme_drought' };
        const cls = ind.classes.find((c) => c.key === map[thrSel]);
        threshold = cls ? cls.max : defaultThr;
      } else threshold = parseFloat(thrSel);

      const minDur = +$('evtMinDur').value;
      const scenario = thrSel === 'default' && minDur === 3 ? 'default' : 'scenario';
      this.cat = A().eventCatalogue(ds, ids(), DIE.state.period, { threshold, minDuration: minDur, season: DIE.state.period.season });
      this.threshold = threshold;
      this.minDuration = minDur;
      this.scenario = scenario;

      // year filter options
      const years = Array.from(new Set(this.cat.rows.map((r) => r.start.slice(0, 4)))).sort();
      const cur = $('evtYear').value;
      $('evtYear').innerHTML = '<option value="">All years</option>' +
        years.map((y) => '<option value="' + y + '"' + (y === cur ? ' selected' : '') + '>' + y + '</option>').join('');

      this.renderTable();
      this.renderTimeline();
      this.renderDist();
      this.renderSensitivity();
      if (this.selected) this.renderDetail(this.selected.districtId, this.selected.startIdx, true);
    },

    renderTable() {
      const ds = currentDataset();
      if (!ds || !this.cat) return;
      const q = ($('evtSearch').value || '').toLowerCase();
      const yr = $('evtYear').value;
      let rows = this.cat.rows;
      if (q) rows = rows.filter((r) => r.district.toLowerCase().includes(q) || r.state.toLowerCase().includes(q));
      if (yr) rows = rows.filter((r) => r.start.slice(0, 4) === yr);

      const sortable = (a, b) => {
        const k = this.sortKey, d = this.sortDir;
        if (['district', 'state', 'start', 'end'].includes(k)) return (String(a[k]).localeCompare(String(b[k]))) * d;
        const av = a[k] === null ? -Infinity : a[k], bv = b[k] === null ? -Infinity : b[k];
        return ((Number.isFinite(av) ? av : -Infinity) - (Number.isFinite(bv) ? bv : -Infinity)) * d;
      };
      rows = [...rows].sort(sortable);

      const totalPages = Math.max(1, Math.ceil(rows.length / this.pageSize));
      this.page = Math.min(this.page, totalPages - 1);
      const pageRows = rows.slice(this.page * this.pageSize, (this.page + 1) * this.pageSize);

      $('evtTableBody').innerHTML = pageRows.map((r) => {
        const censored = r.censoring ? '<span class="sparse-tag" title="Event touches the ' +
          (r.censoring === 'left' ? 'start' : 'end') + ' of the available record — true onset/termination may lie outside it">censored</span>' : '';
        const rec = r.recoveryMonths === null ? '—' : r.recoveryMonths + ' mo';
        return '<tr data-district="' + r.districtId + '" data-start="' + r.startIdx + '" class="evt-row' +
          (this.selected && this.selected.districtId === r.districtId && this.selected.startIdx === r.startIdx ? ' is-selected-row' : '') + '">' +
          '<td>' + r.district + censored + '</td>' +
          '<td>' + r.state + '</td>' +
          '<td class="mono">' + DIE.dates.label(r.start) + '</td>' +
          '<td class="mono">' + DIE.dates.label(r.end) + '</td>' +
          '<td class="num">' + r.duration + '</td>' +
          '<td class="num">' + (Number.isFinite(r.maxIntensity) ? DIE.fmt.val(r.maxIntensity, ds.indicator) : '—') + '</td>' +
          '<td class="num">' + r.severity.toFixed(2) + '</td>' +
          '<td class="num">' + rec + '</td></tr>';
      }).join('') || '<tr><td colspan="8" class="side-note" style="padding:14px">No events match the filters.</td></tr>';

      document.querySelectorAll('#evtTable th.sortable').forEach((th) => {
        th.classList.toggle('sorted-asc', th.dataset.key === this.sortKey && this.sortDir === 1);
        th.classList.toggle('sorted-desc', th.dataset.key === this.sortKey && this.sortDir === -1);
      });

      $('evtPagerInfo').textContent = rows.length
        ? 'Showing ' + (this.page * this.pageSize + 1) + '–' + Math.min(rows.length, (this.page + 1) * this.pageSize) +
          ' of ' + rows.length + ' events · click a row for the event detail view'
        : 'No events';
      $('evtMeta').textContent = ds.indicator.label + ' · ' + DIE.Filters.regionLabel() + ' · ' + periodLabel() +
        ' · ' + this.cat.rows.length + ' events (' + this.cat.rows.filter((r) => r.censoring).length + ' censored)';

      // pager
      const pager = $('evtPager');
      pager.innerHTML = '';
      const btn = (label, page, cur, disabled) => {
        const b = document.createElement('button');
        b.textContent = label; b.disabled = disabled;
        if (cur) b.className = 'cur';
        b.addEventListener('click', () => { this.page = page; this.renderTable(); });
        pager.appendChild(b);
      };
      btn('‹', this.page - 1, false, this.page === 0);
      const start = Math.max(0, this.page - 2);
      const end = Math.min(totalPages - 1, start + 4);
      for (let p = start; p <= end; p++) btn(String(p + 1), p, p === this.page, false);
      btn('›', this.page + 1, false, this.page >= totalPages - 1);

      // row clicks -> detail
      $('evtTableBody').querySelectorAll('tr.evt-row').forEach((tr) => {
        tr.addEventListener('click', () => {
          this.renderDetail(tr.dataset.district, +tr.dataset.start);
        });
      });
    },

    renderTimeline() {
      const ds = currentDataset();
      if (!ds || !this.cat) return;
      const complete = this.cat.rows.filter((r) => !r.censoring);
      DIE.Charts.eventTimeline($('evtTimelineChart'), { events: complete, minDuration: this.minDuration });
      $('evtTimelineMeta').textContent = DIE.Filters.regionLabel() + ' · ' + periodLabel() +
        ' · ' + complete.length + ' complete events';
      $('evtTimelineFoot').textContent = 'Number of districts entering a drought event in each month (event onsets). ' +
        'Censored events (touching the record edge) are excluded from onset counting.';
    },

    renderDist() {
      const ds = currentDataset();
      if (!ds || !this.cat) return;
      const complete = this.cat.rows.filter((r) => !r.censoring);
      DIE.Charts.eventDistribution($('evtDistChart'), { events: complete });
      $('evtDistMeta').textContent = DIE.Filters.regionLabel() + ' · ' + periodLabel();
      $('evtDistFoot').textContent = 'Distribution of event durations across districts (complete events only). ' +
        'Mean duration and severity summaries per district are available in the district-statistics download.';
    },

    renderDetail(districtId, startIdx, keepPanel) {
      const ds = currentDataset();
      if (!ds || !this.cat) return;
      const row = this.cat.rows.find((r) => r.districtId === districtId && r.startIdx === startIdx);
      if (!row) return;
      this.selected = { districtId, startIdx };
      const series = A().districtSeries(ds, districtId);
      // find the event within the full series (startIdx is relative to period slice)
      const ev = this.findEvent(districtId, startIdx);
      if (!ev) return;

      $('evtDetailPanel').hidden = false;
      $('evtDetailTitle').textContent = 'Event · ' + row.district + ', ' + row.state;
      $('evtDetailMeta').textContent = DIE.dates.label(ev.startDate) + ' – ' + DIE.dates.label(ev.endDate) +
        (row.censoring ? ' · censored (' + row.censoring + ')' : '');

      DIE.Charts.eventDetailSeries($('evtDetailChart'), {
        series, event: { ...ev, startIdx: ev.gStartIdx, endIdx: ev.gEndIdx },
        indicator: ds.indicator, threshold: this.threshold
      });

      $('evtDetailStats').innerHTML =
        statCell(ev.duration + ' mo', 'event duration') +
        statCell(DIE.fmt.val(ev.minValue, ds.indicator), 'maximum intensity (' + ds.indicator.label + ')') +
        statCell(ev.severity.toFixed(2), 'cumulative severity (Σ deficit)') +
        statCell(ev.meanIntensity.toFixed(2), 'mean intensity (severity ÷ duration)') +
        statCell(row.recoveryMonths === null ? '—' : row.recoveryMonths + ' mo', 'recovery (to first value ≥ 0)') +
        statCell(DIE.fmt.area(row.area), 'district area');

      // geographic extent: highlight the district on a dedicated map
      if (!DIE.MapView.evtDetailMap) {
        DIE.MapView.evtDetailMap = DIE.MapView.createChoropleth('evtDetailMap', {});
      }
      const dm = DIE.MapView.evtDetailMap;
      dm.applyData(ds, DIE.state.dateIdx, 'classes', districtId);
      const d = DIE.registry.districts.get(districtId);
      if (d) dm.map.setView([d.lat, d.lon], 6);
      $('evtDetailFoot').textContent = 'Event window shaded on the district series; dotted line = truncation level (' +
        this.threshold.toString().replace('-', '−') + '); recovery = months from event end to the first value ≥ 0' +
        (row.recoveryMonths === null ? ' (not reached within the record)' : '') +
        '. ' + (this.scenario === 'default'
          ? 'Default methodology (runs analysis).'
          : 'Non-default scenario: truncation ' + this.threshold + ' · minimum duration ' + this.minDuration + ' months — clearly separated from the default definition.');
      this.renderTable();
    },

    /** Locate the event object (with global indices) for the detail view. */
    findEvent(districtId, startIdx) {
      const ds = currentDataset();
      const period = DIE.state.period;
      const periodIdx = [];
      for (let j = 0; j < ds.dates.length; j++) {
        const y = +ds.dates[j].slice(0, 4);
        if (y >= period.from && y <= period.to) periodIdx.push(j);
      }
      const i = ds.districtIndex.get(districtId);
      const vals = periodIdx.map((j) => ds.values[i][j]);
      const dates = periodIdx.map((j) => ds.dates[j]);
      const evts = A().findEvents(vals, dates, this.threshold, this.minDuration);
      const ev = evts.find((e) => e.startIdx === startIdx);
      if (!ev) return null;
      return { ...ev, gStartIdx: periodIdx[ev.startIdx], gEndIdx: periodIdx[ev.endIdx] };
    },

    renderSensitivity() {
      const ds = currentDataset();
      if (!ds || !this.cat) return;
      const mode = (document.querySelector('input[name="sensMode"]:checked') || {}).value || 'dur';
      deferBusy(() => this.renderSensitivityNow(mode));
    },

    renderSensitivityNow(mode) {
      const ds = currentDataset();
      if (!ds || !this.cat) return;
      const ind = ds.indicator;
      const defaultThr = A().droughtThreshold(ind);
      const points = [];

      if (mode === 'dur') {
        [2, 3, 4, 5, 6, 9, 12].forEach((dur) => {
          const cat = dur === 3 && this.threshold === defaultThr ? this.cat
            : A().eventCatalogue(ds, ids(), DIE.state.period, { threshold: this.threshold, minDuration: dur, season: DIE.state.period.season });
          points.push({ x: dur, nEvents: cat.rows.length, note: dur + ' months minimum' });
        });
        DIE.Charts.sensitivityChart($('sensChart'), {
          points, xLabel: 'minimum event duration (months)',
          defaultX: 3,
          defaultY: points.find((p) => p.x === 3) ? points.find((p) => p.x === 3).nEvents : undefined
        });
        $('sensFoot').textContent = 'Event count sensitivity to the minimum-duration parameter at truncation ' +
          this.threshold + '. The default methodology (3 months) is annotated; every other point is an alternative scenario. ' +
          'Counts include censored events.';
      } else {
        // threshold sweep across the indicator's drought-class bounds
        const opts = ind.family === 'land'
          ? ind.classes.filter((c) => /drought/.test(c.key)).map((c) => ({ label: c.label, v: c.max }))
          : [-0.5, -1.0, -1.5, -2.0].map((v) => ({ label: String(v), v }));
        opts.forEach((o) => {
          const cat = o.v === defaultThr ? this.cat
            : A().eventCatalogue(ds, ids(), DIE.state.period, { threshold: o.v, minDuration: this.minDuration, season: DIE.state.period.season });
          points.push({ x: o.v, nEvents: cat.rows.length, note: o.label + ' (' + o.v + ')' });
        });
        points.sort((a, b) => b.x - a.x);
        DIE.Charts.sensitivityChart($('sensChart'), {
          points, xLabel: 'truncation level (' + ind.units + ')',
          defaultX: defaultThr,
          defaultY: points.find((p) => p.x === defaultThr) ? points.find((p) => p.x === defaultThr).nEvents : undefined
        });
        $('sensFoot').textContent = 'Event count sensitivity to the truncation level at minimum duration ' +
          this.minDuration + ' months. Default (' + defaultThr + ', upper bound of the moderate-drought class) is annotated. ' +
          'Drier (more negative) truncations identify fewer, more intense events.';
      }
    },

    exportCSV() {
      const ds = currentDataset();
      if (!ds || !this.cat) return;
      const n = A().eventCatalogueCSVMeta(ds, ids(), DIE.state.period, DIE.state.period.season);
      toast('Event catalogue exported', n + ' events saved with metadata header.');
    }
  };

  /* ======================================= VIEW 4 · PROPAGATION ===== */
  const Propagation = {
    ready: false, mapsReady: false,

    init() {
      if (this.ready) return;
      this.ready = true;
      const opts = DIE.meta.indicators.map((i) => [i.id, i.label + ' (' + i.units + ')']);
      const fill = (sel, def) => {
        sel.innerHTML = opts.map(([v, l]) => '<option value="' + v + '"' + (v === def ? ' selected' : '') + '>' + l + '</option>').join('');
      };
      fill($('propIndA'), 'spi_3');
      fill($('propIndB'), 'spei_3');

      // single-date comparison module (migrated Module A)
      fill($('cmpIndA'), 'spi_3');
      fill($('cmpIndB'), 'spei_3');
      const ds = currentDataset();
      $('cmpDate').innerHTML = ds.dates.map((ym, j) =>
        '<option value="' + j + '"' + (j === DIE.state.dateIdx ? ' selected' : '') + '>' + DIE.dates.label(ym) + '</option>').join('');

      this.initModuleA();
      this.renderMain();
      this.renderHeatmap();
      this.renderDistrictLagMap();
      setTimeout(() => {
        this.mapA && this.mapA.invalidateSize();
        this.mapB && this.mapB.invalidateSize();
        DIE.MapView.propMap && DIE.MapView.propMap.invalidateSize();
      }, 60);
    },

    refresh() {
      if (!this.ready) return;
      this.renderMain();
      this.renderHeatmap();
      this.renderDistrictLagMap();
      this.renderA();
    },

    /* ------------- temporal cross-correlation with bootstrap CI --------- */
    async renderMain() {
      const idA = $('propIndA').value, idB = $('propIndB').value;
      const st = DIE.state;
      busy(true);
      try {
        const dsA = await DIE.loader.indicator(idA);
        const dsB = await DIE.loader.indicator(idB);
        const isDistrict = !!st.districtId;
        const seriesA = isDistrict ? A().districtSeries(dsA, st.districtId) : A().regionSeries(dsA, ids());
        const seriesB = isDistrict ? A().districtSeries(dsB, st.districtId) : A().regionSeries(dsB, ids());
        // restrict to analysis period
        const inPeriod = (p) => {
          const y = +p.ym.slice(0, 4);
          return y >= st.period.from && y <= st.period.to;
        };
        const ptsA = seriesA.pts.filter(inPeriod);
        const ptsB = seriesB.pts.filter(inPeriod);

        const lags = S().laggedCrossCorrelation(ptsA, ptsB, 12);
        const opt = S().optimalLag(lags, 30);

        // bootstrap CI at the optimal lag (and lag 0 for reference)
        let ci = null;
        if (opt) {
          const mapB = new Map();
          ptsB.forEach((p) => { if (p.v !== null && p.v !== undefined) mapB.set(p.ym, p.v); });
          const xs = [], ys = [];
          ptsA.forEach((p) => {
            if (p.v === null || p.v === undefined) return;
            const bv = mapB.get(S().shiftYm(p.ym, opt.lag));
            if (bv !== undefined) { xs.push(p.v); ys.push(bv); }
          });
          const bs = S().blockBootstrapCI(xs, ys, (a, b) => S().pearson(a, b));
          ci = { ...bs, lag: opt.lag, r: opt.r };
        }

        DIE.Charts.lagCorrelationChart($('propLagChart'), { lags, optimal: opt, ci });
        DIE.Charts.dualSeriesChart($('propTsChart'), { seriesA: { pts: ptsA }, seriesB: { pts: ptsB }, indA: dsA.indicator, indB: dsB.indicator });

        const stBox = $('propStats');
        if (!opt) {
          stBox.innerHTML = '<p class="side-note">Fewer than 30 matched months across all lags — no correlation is reported for this pair and period.</p>';
        } else {
          const ciText = ci && Number.isFinite(ci.ci[0])
            ? 'r = ' + ci.r.toFixed(3) + ' · 95% CI [' + ci.ci[0].toFixed(3) + ', ' + ci.ci[1].toFixed(3) + ']'
            : 'insufficient pairs for a bootstrap interval';
          const pText = Number.isFinite(opt.p) ? (opt.p < 0.001 ? 'p < 0.001' : 'p = ' + opt.p.toFixed(3)) : '—';
          stBox.innerHTML =
            '<div class="stat-grid">' +
            statCell(opt.lag + ' mo', 'optimal lag (B after A)') +
            statCell(opt.r.toFixed(3), 'Pearson r at optimal lag') +
            statCell(ciText, 'moving-block bootstrap 95% CI') +
            statCell(String(opt.n), 'matched months (n)') +
            statCell(pText, 'nominal two-sided p (t)') +
            '</div>' +
            '<p class="rail-note">' + this.interpret(opt, ci, dsA, dsB) + '</p>';
        }
        $('propFoot').textContent = 'Positive lag: ' + dsB.indicator.label + ' responds after ' + dsA.indicator.label +
          '. Matched months only (pairwise deletion' + (idA === 'vci' || idB === 'vci' ? '; VCI contributes from 2000-02' : '') +
          '). Nominal p-values treat months as independent; the bootstrap CI preserves serial dependence (block length n^1/3, 1 000 resamples, fixed seed). ' +
          'Correlation is not causation.';
      } catch (err) {
        console.error(err);
        toast('Propagation analysis failed', String(err.message || err), 'error');
      } finally {
        busy(false);
      }
    },

    interpret(opt, ci, dsA, dsB) {
      if (!opt) return '';
      const strong = Math.abs(opt.r) >= 0.7, moderate = Math.abs(opt.r) >= 0.4;
      const strength = strong ? 'strong' : moderate ? 'moderate' : 'weak';
      const dir = opt.r > 0 ? 'same-direction (both dry or both wet)' : 'opposite-direction';
      const lagTxt = opt.lag === 0
        ? 'synchronously (no systematic lag)'
        : Math.abs(opt.lag) + ' month' + (Math.abs(opt.lag) === 1 ? '' : 's') +
          ' later (positive: B after A)';
      const ciNote = ci && Number.isFinite(ci.ci[0])
        ? (ci.ci[0] > 0 || ci.ci[1] < 0 ? 'The 95% block-bootstrap interval excludes zero. ' : 'The 95% block-bootstrap interval includes zero — treat the association as statistically uncertain. ')
        : '';
      return 'Interpretation: ' + dsA.indicator.label + ' and ' + dsB.indicator.label + ' vary ' + dir + ' and ' +
        strength + 'ly (|r| = ' + Math.abs(opt.r).toFixed(2) + '), with ' + dsB.indicator.label +
        ' responding ' + lagTxt + ' over ' + opt.n + ' matched months. ' + ciNote +
        'Association only — no causal claim is made.';
    },

    /* ------------------------- correlation heatmap ---------------------- */
    async renderHeatmap() {
      const st = DIE.state;
      const scopeKey = [st.extent, st.stateId || '', st.districtId || '',
        DIE.Filters.regionIds().length, st.period.from, st.period.to, st.period.season].join('|');
      this._heatCache = this._heatCache || new Map();
      if (this._heatCache.has(scopeKey)) {
        this._paintHeatmap(this._heatCache.get(scopeKey));
        return;
      }
      if (this._heatPending === scopeKey) return;
      this._heatPending = scopeKey;
      const token = (this._heatToken = (this._heatToken || 0) + 1);
      const idsAll = DIE.meta.indicators.map((i) => i.id);
      // Show a clear placeholder while the matrices download/parse.
      DIE.Charts.loading($('propHeatChart'),
        'Loading all ' + idsAll.length + ' indicators and computing pairwise correlations…');
      $('propHeatScope').textContent = DIE.Filters.regionLabel() + ' · ' + periodLabel();
      busy(true);
      let datasets = [];
      try {
      // Parallel loading: the CSVs are independent and the text cache dedupes.
      const loaded = await Promise.all(idsAll.map((id) =>
        DIE.loader.indicator(id).catch((e) => { console.warn('[DIE] heatmap: ' + id, e); return null; })));
      datasets = loaded.filter(Boolean);
      if (token !== this._heatToken) return;
      const labels = datasets.map((d) => d.indicator.label);
      const n = datasets.length;
      const z = Array.from({ length: n }, () => new Array(n).fill(null));
      const seriesArr = datasets.map((ds) => {
        const s = st.districtId ? A().districtSeries(ds, st.districtId) : A().regionSeries(ds, ids());
        return s.pts.filter((p) => {
          const y = +p.ym.slice(0, 4);
          return y >= st.period.from && y <= st.period.to;
        });
      });
      for (let i = 0; i < n; i++) z[i][i] = 1;
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          const lags = S().laggedCrossCorrelation(seriesArr[i], seriesArr[j], 12);
          const opt = S().optimalLag(lags, 30);
          const v = opt ? opt.r : NaN;
          z[i][j] = Number.isFinite(v) ? v : null;
          z[j][i] = z[i][j];
        }
      }
      const payload = {
        labels, z,
        scope: DIE.Filters.regionLabel() + ' · ' + periodLabel()
      };
      this._heatCache.set(scopeKey, payload);
      if (this._heatCache.size > 8) this._heatCache.delete(this._heatCache.keys().next().value);
      this._paintHeatmap(payload);
      } catch (err) {
        console.error(err);
        DIE.Charts.state($('propHeatChart'), 'HEATMAP UNAVAILABLE',
          'One or more indicator matrices could not be loaded. Use Validate all indicators on the Data & Methods tab, then retry.');
      } finally {
        if (this._heatPending === scopeKey) this._heatPending = null;
        busy(false);
      }
    },

    _paintHeatmap(payload) {
      DIE.Charts.correlationHeatmap($('propHeatChart'), { labels: payload.labels, z: payload.z });
      $('propHeatScope').textContent = payload.scope;
      $('propHeatFoot').textContent = 'Pearson r between indicator pairs at their optimal lag (|r| maximised over −12…+12 months, ≥ 30 matched months required; blank = insufficient overlap). ' +
        'SPI/SPEI at different accumulation scales are strongly correlated by construction — compare across families for propagation insight. ' +
        'Computed on matched months within the analysis period only.';
    },

    /* ---------------------- district-wise optimal lag map --------------- */
    async renderDistrictLagMap() {
      const idA = $('propIndA').value, idB = $('propIndB').value;
      const st = DIE.state;
      const regionIds = st.districtId ? [st.districtId] : ids();
      const lagKey = [idA, idB, st.extent, st.stateId || '', st.districtId || '',
        st.period.from, st.period.to, st.period.season, regionIds.length].join('|');
      this._lagCache = this._lagCache || new Map();
      if (this._lagCache.has(lagKey)) {
        this._paintLagMap(this._lagCache.get(lagKey));
        return;
      }
      if (this._lagPending === lagKey) return;
      this._lagPending = lagKey;
      const token = (this._lagToken = (this._lagToken || 0) + 1);
      $('propMapFoot').textContent = 'Computing district-wise optimal lags for ' + regionIds.length +
        ' districts… results appear when the calculation finishes.';
      busy(true);
      try {
        const dsA = await DIE.loader.indicator(idA);
        const dsB = await DIE.loader.indicator(idB);
        if (token !== this._lagToken) return;

        // per-district optimal lag + r (districtSeries is memoised)
        const results = new Map();
        regionIds.forEach((id) => {
          const a = A().districtSeries(dsA, id).pts.filter((p) => {
            const y = +p.ym.slice(0, 4);
            return y >= st.period.from && y <= st.period.to;
          });
          const b = A().districtSeries(dsB, id).pts.filter((p) => {
            const y = +p.ym.slice(0, 4);
            return y >= st.period.from && y <= st.period.to;
          });
          const lags = S().laggedCrossCorrelation(a, b, 12);
          const opt = S().optimalLag(lags, 60);
          if (opt && Math.abs(opt.r) >= 0.4) results.set(id, opt);
        });

        if (!DIE.MapView.propMap) {
          DIE.MapView.propMap = DIE.MapView.createChoropleth('propMap', {});
        }
        const vals = Array.from(results.values());
        const payload = {
          results, regionIds, lo: vals.length ? Math.min(...vals.map((v) => v.lag)) : -12,
          hi: vals.length ? Math.max(...vals.map((v) => v.lag)) : 12,
          labelA: dsA.indicator.label, labelB: dsB.indicator.label
        };
        this._lagCache.set(lagKey, payload);
        if (this._lagCache.size > 8) this._lagCache.delete(this._lagCache.keys().next().value);
        this._paintLagMap(payload);
      } catch (err) {
        console.error(err);
        toast('District lag map failed', String(err.message || err), 'error');
      } finally {
        if (this._lagPending === lagKey) this._lagPending = null;
        busy(false);
      }
    },

    _paintLagMap(p) {
      const pm = DIE.MapView.propMap;
      if (!pm) return;
      const st = DIE.state;
      const { results, regionIds, lo, hi } = p;
      // diverging ramp for lags: blue (A leads, negative) - white 0 - red (B lags, positive)
      pm.applyData(null, 0, 'classes', st.districtId, (id) => {
        const r = results.get(id);
        return r ? r.lag : NaN;
      }, (id) => {
        const r = results.get(id);
        if (!r) return '#D7DEE7';
        const t = hi === lo ? 0 : (r.lag - lo) / (hi - lo);
        const blue = [42, 95, 133], white = [255, 255, 255], red = [185, 71, 71];
        const c = t < 0.5
          ? blue.map((x, i) => Math.round(x + (white[i] - x) * (t * 2)))
          : white.map((x, i) => Math.round(x + (red[i] - x) * ((t - 0.5) * 2)));
        return 'rgb(' + c.join(',') + ')';
      });
      $('propMapMeta').textContent = p.labelA + ' → ' + p.labelB + ' · ' + DIE.Filters.regionLabel() +
        ' · ' + periodLabel();
      $('propMapFoot').innerHTML = 'Optimal lag per district (only districts with |r| ≥ 0.40 and ≥ 60 matched months are coloured). ' +
        '<span class="legend-swatch" style="background:rgb(42,95,133)"></span> A leads by ' + Math.abs(lo) + ' mo &nbsp; ' +
        '<span class="legend-swatch" style="background:#FFFFFF"></span> synchronous &nbsp; ' +
        '<span class="legend-swatch" style="background:rgb(185,71,71)"></span> B lags by ' + hi + ' mo' +
        ' · <span class="legend-swatch" style="background:#D7DEE7"></span> no robust relationship (' +
        (regionIds.length - results.size) + ' districts)';
    },

    /* --------------------- migrated Module A (spatial cmp) -------------- */
    initModuleA() {
      const viewA = { ds: null, idx: null };
      const viewB = { ds: null, idx: null, mode: 'b' };

      this.mapA = DIE.MapView.createChoropleth('mapA', {
        getContext: () => ({ dataset: viewA.ds, dateIdx: viewA.idx })
      });
      this.mapB = DIE.MapView.createChoropleth('mapB', {
        getContext: () => ({ dataset: viewB.mode === 'b' ? viewB.ds : null, dateIdx: viewB.idx })
      });
      let syncing = false;
      const sync = (src, dst) => () => {
        if (syncing) return;
        syncing = true;
        dst.setView(src.getCenter(), src.getZoom(), { animate: false });
        syncing = false;
      };
      this.mapA.map.on('moveend', sync(this.mapA.map, this.mapB.map));
      this.mapB.map.on('moveend', sync(this.mapB.map, this.mapA.map));

      const diffRamp = (v) => {
        if (!Number.isFinite(v)) return '#D7DEE7';
        const t = Math.max(-1, Math.min(1, v / 3));
        const lerp = (a, b, u) => a + (b - a) * u;
        const dry = [143, 37, 47], mid = [255, 255, 255], wet = [42, 95, 133];
        const c = t < 0 ? dry.map((x, i) => lerp(x, mid[i], 1 + t)) : mid.map((x, i) => lerp(x, wet[i], t));
        return 'rgb(' + c.map(Math.round).join(',') + ')';
      };

      this.renderA = async () => {
        const idA = $('cmpIndA').value, idB = $('cmpIndB').value;
        const idx = +$('cmpDate').value;
        viewB.mode = document.querySelector('input[name="cmpView"]:checked').value;
        try {
          const dsA = await DIE.loader.indicator(idA);
          const dsB = await DIE.loader.indicator(idB);
          viewA.ds = dsA; viewA.idx = idx;
          viewB.ds = dsB; viewB.idx = idx;

          this.mapA.applyData(dsA, idx, 'classes', null);
          if (viewB.mode === 'b') {
            $('cmpMapBTitle').textContent = dsB.indicator.label + ' · ' + DIE.dates.label(dsA.dates[idx]);
            this.mapB.applyData(dsB, idx, 'classes', null);
          } else {
            $('cmpMapBTitle').textContent = 'Difference ' + dsB.indicator.label + ' − ' + dsA.indicator.label +
              ' · ' + DIE.dates.label(dsA.dates[idx]);
            this.mapB.applyData(null, idx, 'classes', null, (id) => {
              const iA = dsA.districtIndex.get(id), iB = dsB.districtIndex.get(id);
              if (iA === undefined || iB === undefined) return NaN;
              const a = dsA.values[iA][idx], b = dsB.values[iB][idx];
              return (Number.isFinite(a) && Number.isFinite(b)) ? b - a : NaN;
            }, (id) => diffRamp((() => {
              const iA = dsA.districtIndex.get(id), iB = dsB.districtIndex.get(id);
              if (iA === undefined || iB === undefined) return NaN;
              const a = dsA.values[iA][idx], b = dsB.values[iB][idx];
              return (Number.isFinite(a) && Number.isFinite(b)) ? b - a : NaN;
            })()));
          }
          $('cmpMapATitle').textContent = dsA.indicator.label + ' · ' + DIE.dates.label(dsA.dates[idx]);

          const st = A().comparisonStats(dsA, dsB, idx);
          const cells = [
            ['r (Pearson)', Number.isFinite(st.r) ? st.r.toFixed(3) : '—'],
            ['r²', Number.isFinite(st.r) ? (st.r * st.r).toFixed(3) : '—'],
            ['RMSE', Number.isFinite(st.rmse) ? st.rmse.toFixed(2) : '—'],
            ['Bias (B−A)', Number.isFinite(st.bias) ? st.bias.toFixed(2) : '—'],
            ['n (matched)', st.n],
            ['Excluded (missing)', st.missing]
          ];
          $('cmpStats').innerHTML = '<div class="cs-grid">' + cells.map((c) =>
            '<div class="cs-cell"><b>' + c[1] + '</b><i>' + c[0] + '</i></div>').join('') + '</div>' +
            '<p class="rail-note">Pairwise-complete districts at the matched date only. Bias = mean(B−A); ' +
            'positive RMSE contributions are never hidden by imputation.</p>';

          DIE.Charts.scatterCompare($('cmpScatter'), {
            pairs: st.pairs, indA: dsA.indicator, indB: dsB.indicator,
            labelA: dsA.indicator.label, labelB: dsB.indicator.label,
            fit: st.line,
            statsAnnotation: {
              x: 0.02, xref: 'paper', y: 0.97, yref: 'paper', showarrow: false,
              text: 'r = ' + (Number.isFinite(st.r) ? st.r.toFixed(2) : '—') + ' · n = ' + st.n,
              font: { family: 'IBM Plex Mono, monospace', size: 11, color: '#687588' }
            }
          });
          $('cmpFoot').textContent = 'Matched date: ' + DIE.dates.label(dsA.dates[idx]) +
            ' · matched spatial units: ' + st.n + ' districts (pairwise deletion; ' + st.missing +
            ' excluded) · units: ' + dsA.indicator.units + ' (A) vs ' + dsB.indicator.units +
            ' (B). ' + (isDemo() ? 'Demonstration data.' : 'GEE-derived historical data.');
        } catch (err) {
          toast('Comparison failed', String(err.message || err), 'error');
        }
      };

      ['cmpIndA', 'cmpIndB', 'cmpDate'].forEach((id) => $(id).addEventListener('change', () => this.renderA && this.renderA()));
      document.querySelectorAll('input[name="cmpView"]').forEach((r) => r.addEventListener('change', () => this.renderA && this.renderA()));
      this.renderA();
    }
  };

  /* ===================================== VIEW 5 · DATA & METHODS ===== */
  const DataView = {
    ready: false,

    init() {
      if (this.ready) return;
      this.ready = true;
      this.renderQuality(); // also refreshes the metadata/indicator tables
      renderDownloads($('downloadsTab'));
    },

    renderMeta() {
      const m = DIE.meta;
      const rows = [
        ['Application', m.application],
        ['Data mode', m.data_mode + (m.random_seed !== null && m.random_seed !== undefined ? ' (random seed ' + m.random_seed + ')' : '')],
        ['Region', m.region],
        ['Spatial units', m.spatial_units],
        ['Spatial resolution', m.spatial_resolution],
        ['Temporal resolution', m.temporal_resolution],
        ['Observation period (declared)', m.period.start + ' – ' + m.period.end + ' (' + m.period.n_months + ' months)'],
        ['Reference climatological period', m.reference_period],
        ['Methodology version', m.methodology_version],
        ['Last updated', m.last_updated],
        ['CRS', m.crs],
        ['Area method', m.area_method],
        ['Data provenance', m.data_provenance]
      ];
      $('metaTableBody').innerHTML = rows.map((r) =>
        '<tr><td style="width:220px">' + r[0] + '</td><td>' + r[1] + '</td></tr>').join('');

      // per-indicator availability (from metadata; load datasets lazily for latest obs)
      const fmtInd = (i) => {
        const ds = DIE.datasets.get(i.id);
        const valid = i.completeness_pct !== undefined ? i.completeness_pct : null;
        const missing = valid === null ? '—' : (100 - valid).toFixed(1) + '%';
        const latest = ds ? ds.availableTo : i.available_to;
        return '<tr><td>' + i.label + '</td><td>' + (i.family === 'spi' ? 'Meteorological (SPI)'
          : i.family === 'spei' ? 'Water balance (SPEI)' : 'Land surface') + '</td>' +
          '<td class="num">' + i.units + '</td>' +
          '<td class="num">' + (i.accumulation_months || '—') + '</td>' +
          '<td class="num">' + (valid === null ? '—' : valid.toFixed(1) + '%') + '</td>' +
          '<td class="num">' + missing + '</td>' +
          '<td class="mono">' + (i.available_from || '—') + ' – ' + (i.available_to || '—') + '</td>' +
          '<td class="mono">' + (latest ? DIE.dates.label(latest) : '—') + '</td></tr>';
      };
      $('indTableBody').innerHTML = m.indicators.map(fmtInd).join('');
    },

    renderQuality() {
      const box = $('qualityReport');
      const lines = [];
      let loaded = 0;
      DIE.datasets.forEach((ds) => {
        loaded++;
        const r = ds.report;
        const bad = r.duplicates + r.invalidValues + r.invalidDates + r.unknownDistricts + r.missingIds;
        lines.push('<b>' + ds.indicator.label + '</b> — ' + ds.districtIds.length + ' districts × ' +
          ds.dates.length + ' months · ' + r.validObservations.toLocaleString() + ' valid observations (' +
          (r.completeness * 100).toFixed(1) + '%) · ' +
          (bad === 0 ? '<span class="vr-ok">no structural issues detected</span>'
            : '<span class="vr-warn">' + bad + ' issues</span>'));
        const detail = [];
        if (r.duplicates) detail.push(r.duplicates + ' duplicate district rows (merged, last kept)');
        if (r.invalidDates) detail.push(r.invalidDates + ' invalid date columns (skipped)');
        if (r.invalidValues) detail.push(r.invalidValues + ' non-numeric values (treated as missing)');
        if (r.missingCells) detail.push(r.missingCells.toLocaleString() + ' missing cells (explicit no-data)');
        if (r.unknownDistricts) detail.push(r.unknownDistricts + ' district ids not present in boundaries (dropped)');
        if (r.unrepresentedDistricts) detail.push(r.unrepresentedDistricts + ' boundary districts absent from this dataset (no-data)');
        if (detail.length) lines.push('<ul>' + detail.map((d) => '<li>' + d + '</li>').join('') + '</ul>');
      });
      box.innerHTML = lines.join('<br>') ||
        '<p class="side-note">No indicator has been loaded in this session yet. Use <b>Validate all indicators</b> for a full audit, or switch indicators to validate them individually.</p>';
      const status = $('validateAllStatus');
      if (status) {
        status.textContent = loaded + ' of ' + DIE.meta.indicators.length +
          ' indicators validated in this session.' + (loaded < DIE.meta.indicators.length
            ? ' The full audit downloads the remaining CSV matrices only when you ask for it.' : '');
      }
      // Refresh the latest-observation column without rebuilding everything.
      this.renderMeta();
    },

    /** Load + validate every indicator in small parallel batches. */
    async validateAll() {
      const btn = $('validateAllBtn'), status = $('validateAllStatus');
      const pending = DIE.meta.indicators.filter((i) => !DIE.datasets.has(i.id));
      if (!pending.length) {
        if (status) status.textContent = 'All ' + DIE.meta.indicators.length + ' indicators are already validated.';
        return;
      }
      if (btn) { btn.disabled = true; btn.textContent = 'Validating…'; }
      let done = 0;
      const total = pending.length;
      const progress = () => {
        if (status) status.textContent = 'Validating ' + done + ' of ' + total +
          ' remaining indicators… reports appear as each finishes.';
      };
      progress();
      for (let k = 0; k < pending.length; k += 3) {
        await Promise.all(pending.slice(k, k + 3).map((ind) =>
          DIE.loader.indicator(ind.id)
            .catch((err) => console.warn('[DIE] validation failed for ' + ind.id, err))
            .then(() => { done++; progress(); if (DataView.ready) DataView.renderQuality(); })
        ));
      }
      if (btn) { btn.disabled = false; btn.textContent = 'Validate all indicators'; }
      if (status) status.textContent = 'All ' + DIE.meta.indicators.length + ' indicators validated.';
      toast('Validation complete', 'All indicator reports are up to date.');
    }
  };

  /* ================================================ COMPARISON TABLE == */
  const Table = { sortKey: 'affected', sortDir: -1, page: 0, pageSize: 12, rows: [] };

  function renderTable() {
    const ds = currentDataset();
    if (!ds) return;
    const level = $('tableLevel').value;
    const scopeIds = level === 'district' && DIE.state.stateId
      ? (DIE.registry.byState.get(DIE.state.stateId) || []).map((d) => d.id)
      : null;
    Table.rows = A().comparisonRows(ds, level, DIE.state.period, DIE.state.period.season, scopeIds);

    const q = ($('tableSearch').value || '').toLowerCase();
    let rows = Table.rows;
    if (q) rows = rows.filter((r) => r.label.toLowerCase().includes(q));

    const sortable = (a, b) => {
      const k = Table.sortKey, d = Table.sortDir;
      if (k === 'name') return a.label.localeCompare(b.label) * d;
      const av = a[k], bv = b[k];
      const an = Number.isFinite(av) ? av : -Infinity;
      const bn = Number.isFinite(bv) ? bv : -Infinity;
      return (an - bn) * d || a.label.localeCompare(b.label);
    };
    rows = [...rows].sort(sortable);

    const ranked = Table.rows.filter((r) => r.completeness >= 50 && Number.isFinite(r.affected));
    const top5 = new Set([...ranked].sort((a, b) => b.affected - a.affected).slice(0, 5).map((r) => r.id));

    const totalPages = Math.max(1, Math.ceil(rows.length / Table.pageSize));
    Table.page = Math.min(Table.page, totalPages - 1);
    const pageRows = rows.slice(Table.page * Table.pageSize, (Table.page + 1) * Table.pageSize);

    const tb = $('compTableBody');
    tb.innerHTML = pageRows.map((r) => {
      const sparse = r.completeness < 50;
      const cls = (top5.has(r.id) ? ' hit' : '') + (sparse ? ' is-sparse' : '') +
        ((level === 'state' && r.id === DIE.state.stateId) || (level === 'district' && r.id === DIE.state.districtId) ? ' is-selected-row' : '');
      const num = (v, fmt) => Number.isFinite(v) ? fmt(v) : '<span class="na">N/A</span>';
      return '<tr class="' + cls.trim() + '"><td>' + r.label +
        (sparse ? '<span class="sparse-tag">sparse data</span>' : '') + '</td>' +
        '<td class="num">' + num(r.mean, (v) => v.toFixed(2)) + '</td>' +
        '<td class="num">' + num(r.affected, (v) => v.toFixed(1)) + '</td>' +
        '<td class="num">' + num(r.severe, (v) => v.toFixed(1)) + '</td>' +
        '<td class="num">' + r.months + '</td>' +
        '<td class="num">' + r.completeness.toFixed(1) + '</td></tr>';
    }).join('') || '<tr><td colspan="6" class="side-note" style="padding:14px">No regions match the search.</td></tr>';

    document.querySelectorAll('#compTable th.sortable').forEach((th) => {
      th.classList.toggle('sorted-asc', th.dataset.key === Table.sortKey && Table.sortDir === 1);
      th.classList.toggle('sorted-desc', th.dataset.key === Table.sortKey && Table.sortDir === -1);
    });

    $('tablePagerInfo').textContent = 'Showing ' + (rows.length ? Table.page * Table.pageSize + 1 : 0) + '–' +
      Math.min(rows.length, (Table.page + 1) * Table.pageSize) + ' of ' + rows.length +
      ' rows · top-5 most affected highlighted';
    $('tableMeta').textContent = ds.indicator.label + ' · ' + periodLabel();

    const pager = $('tablePager');
    pager.innerHTML = '';
    const btn = (label, page, cur, disabled) => {
      const b = document.createElement('button');
      b.textContent = label; b.disabled = disabled;
      if (cur) b.className = 'cur';
      b.addEventListener('click', () => { Table.page = page; renderTable(); });
      pager.appendChild(b);
    };
    btn('‹', Table.page - 1, false, Table.page === 0);
    const start = Math.max(0, Table.page - 2);
    const end = Math.min(totalPages - 1, start + 4);
    for (let p = start; p <= end; p++) btn(String(p + 1), p, p === Table.page, false);
    btn('›', Table.page + 1, false, Table.page >= totalPages - 1);
  }

  function exportTableCSV() {
    const ds = currentDataset();
    if (!ds) return;
    const level = $('tableLevel').value;
    const head = A().exportMetaLines(['table: regional comparison (' + level + ' level)']);
    const rows = [[
      'level', 'region_id', 'region', 'indicator', 'period', 'season',
      'mean_indicator', 'drought_affected_area_pct', 'severe_drought_area_pct',
      'drought_months', 'months_considered', 'data_completeness_pct'
    ]];
    Table.rows.forEach((r) => rows.push([
      level, r.id, r.label, ds.indicator.id,
      DIE.state.period.from + '-' + DIE.state.period.to, DIE.state.period.season,
      Number.isFinite(r.mean) ? r.mean.toFixed(3) : '',
      Number.isFinite(r.affected) ? r.affected.toFixed(2) : '',
      Number.isFinite(r.severe) ? r.severe.toFixed(2) : '',
      r.months, r.monthsConsidered, r.completeness.toFixed(1)
    ]));
    const text = head.concat(rows.map((r) => r.map(A().csvEscape).join(','))).join('\n');
    A().downloadBlob('die-comparison-' + level + '-' + ds.indicator.id + '-' +
      DIE.state.period.from + '-' + DIE.state.period.to + '.csv',
      new Blob([text], { type: 'text/csv;charset=utf-8' }));
    toast('Table exported', rows.length - 1 + ' regions saved as CSV (with metadata header).');
  }

  /* ======================================================= DOWNLOADS UI == */
  function datasetCitation() {
    if (DIE.meta.random_seed !== null && DIE.meta.random_seed !== undefined) {
      return 'Dataset: synthetic demonstration build (seed ' + DIE.meta.random_seed +
        '), methodology version ' + DIE.meta.methodology_version + '. Not observed measurements.';
    }
    return 'Dataset: ' + (DIE.meta.data_provenance || 'GEE-derived historical research dataset') +
      ' Methodology version ' + DIE.meta.methodology_version + '.';
  }

  function renderDownloads(container) {
    if (!container || container.dataset.ready) return;
    container.dataset.ready = '1';
    container.innerHTML =
      '<div class="dl-group-title">Time-series data (CSV · generated client-side)</div>' +
      '<div class="dl-card"><div class="dl-title">Region extract — long format</div>' +
      '<div class="dl-desc">All districts of the current region, full monthly record, with classification and equal-area district statistics. Includes a reproducibility metadata header (indicator, geography, periods, export date, methodology).</div>' +
      '<div class="dl-meta" data-meta="region">—</div>' +
      '<div class="dl-actions"><button class="btn btn-solid" data-dl="region">Download CSV</button></div></div>' +

      '<div class="dl-card"><div class="dl-title">Selected indicator dataset</div>' +
      '<div class="dl-desc">The distributed wide-format matrix (districts × months) for the current indicator, exactly as loaded.</div>' +
      '<div class="dl-meta">CSV · ~0.9 MB</div>' +
      '<div class="dl-actions"><button class="btn" data-dl="indicator">Download file</button></div></div>' +

      '<div class="dl-group-title">Statistical summaries (CSV · analysis period)</div>' +
      '<div class="dl-card"><div class="dl-title">District drought statistics</div>' +
      '<div class="dl-desc">Per-district statistics over the selected analysis period: mean, extremes, drought months and frequency, event count (complete and censored), durations, cumulative severity, worst event, completeness. Metadata header included.</div>' +
      '<div class="dl-meta" data-meta="summary">—</div>' +
      '<div class="dl-actions"><button class="btn" data-dl="summary">Download CSV</button></div></div>' +

      '<div class="dl-card"><div class="dl-title">Drought event catalogue</div>' +
      '<div class="dl-desc">Every identified event (runs analysis, default methodology) in the current region and period: district, onset, termination, duration, maximum intensity, cumulative severity, censoring flag, recovery months. Metadata header included.</div>' +
      '<div class="dl-meta" data-meta="events">—</div>' +
      '<div class="dl-actions"><button class="btn" data-dl="events">Download CSV</button></div></div>' +

      '<div class="dl-card"><div class="dl-title">Precomputed summaries (shipped)</div>' +
      '<div class="dl-desc">Reproducibility cross-checks shipped with the build: drought events (SPI-6, runs analysis) and state statistics.</div>' +
      '<div class="dl-meta">static artifacts</div>' +
      '<div class="dl-actions">' +
      '<a class="btn" href="' + DIE.base + 'data/summaries/drought_events_spi_06.csv" download>drought_events_spi_06.csv</a>' +
      '<a class="btn" href="' + DIE.base + 'data/summaries/state_statistics_spi_06.csv" download>state_statistics_spi_06.csv</a>' +
      '</div></div>' +

      '<div class="dl-group-title">Analysis metadata</div>' +
      '<div class="dl-card"><div class="dl-title">Reproducibility metadata (JSON)</div>' +
      '<div class="dl-desc">Complete record of the current analysis state: indicator, geography, observation and analysis periods, reference period, methodology settings, dataset provenance, export timestamp.</div>' +
      '<div class="dl-actions"><button class="btn" data-dl="metaJson">Download JSON</button></div></div>' +

      '<div class="dl-group-title">Spatial exports</div>' +
      '<div class="dl-card"><div class="dl-title">District boundaries (GeoJSON)</div>' +
      '<div class="dl-desc">The simplified district boundary layer exactly as served (724 districts), including district identifiers used by every export.</div>' +
      '<div class="dl-actions"><a class="btn" href="' + DIE.base + 'data/boundaries/india_districts.geojson" download>india_districts.geojson</a>' +
      '<a class="btn" href="' + DIE.base + 'data/boundaries/india_states.geojson" download>india_states.geojson</a></div></div>' +

      '<div class="dl-card"><div class="dl-title">Current map (PNG)</div>' +
      '<div class="dl-desc">Renders the current map view, legend colours and selection. Vector layers are captured directly; use the Plain basemap if tile capture fails.</div>' +
      '<div class="dl-meta">rasterises the live DOM</div>' +
      '<div class="dl-actions"><button class="btn" data-dl="map">Export map PNG</button></div></div>' +

      '<div class="dl-group-title">Documentation</div>' +
      '<div class="dl-card"><div class="dl-title">User guide (Markdown)</div>' +
      '<div class="dl-desc">Quick start, a map of the five workspaces, a plain-language explanation of every table and chart, uncertainty caveats and keyboard navigation — the same content as the in-app guide.</div>' +
      '<div class="dl-actions"><button class="btn" data-dl="userguide">Download docs/user-guide.md</button></div></div>' +
      '<div class="dl-card"><div class="dl-title">Methodology &amp; data sources (Markdown)</div>' +
      '<div class="dl-desc">Full indicator definitions, classification thresholds, standardization, aggregation, event identification, missing-data policy and limitations; data-source register.</div>' +
      '<div class="dl-actions"><button class="btn" data-dl="methodology">Download docs/methodology.md</button>' +
      '<button class="btn" data-dl="datasources">Download docs/data-sources.md</button></div></div>' +

      '<div class="dl-group-title">Citation</div>' +
      '<div class="cite-box">' + DIE.meta.citation + '\n' + datasetCitation() + '</div>' +
      '<div class="dl-actions"><button class="btn" data-dl="cite">Copy citation</button></div>';

    container.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-dl]');
      if (!btn || btn.disabled) return;
      const kind = btn.dataset.dl;
      try {
        if (kind === 'region') {
          const ds = currentDataset();
          const n = A().longExportCSVMeta(ds, ids());
          toast('Export complete', n + ' district-month records written (long format, with metadata header).');
        } else if (kind === 'indicator') {
          const ind = DIE.indicatorById.get(DIE.state.indicator);
          const text = await DIE.loader.fetchText(ind.file);
          A().toText('die-' + ind.id + '-wide.csv', text, 'text/csv;charset=utf-8');
          toast('Export complete', 'Wide-format matrix saved.');
        } else if (kind === 'summary') {
          const ds = currentDataset();
          const n = A().districtStatsCSVMeta(ds, ids(), DIE.state.period, DIE.state.period.season);
          toast('Export complete', n + ' district summaries written (with metadata header).');
        } else if (kind === 'events') {
          const ds = currentDataset();
          const n = A().eventCatalogueCSVMeta(ds, ids(), DIE.state.period, DIE.state.period.season);
          toast('Export complete', n + ' events written (with metadata header).');
        } else if (kind === 'metaJson') {
          A().toText('die-analysis-metadata.json', A().analysisMetadataJSON(), 'application/json');
          toast('Export complete', 'Analysis metadata saved as JSON.');
        } else if (kind === 'map') {
          await DIE.MapView.exportPNG();
        } else if (kind === 'methodology' || kind === 'datasources' || kind === 'userguide') {
          const file = kind === 'methodology' ? 'docs/methodology.md'
            : kind === 'datasources' ? 'docs/data-sources.md' : 'docs/user-guide.md';
          const text = await DIE.loader.fetchText(file);
          A().toText(file.split('/').pop(), text, 'text/markdown;charset=utf-8');
          toast('Documentation saved', file);
        } else if (kind === 'cite') {
          const text = DIE.meta.citation + '\n' + datasetCitation();
          try {
            await navigator.clipboard.writeText(text);
            toast('Citation copied', 'Pasted-ready citation is on your clipboard.');
          } catch (err) {
            A().toText('CITATION.txt', text);
            toast('Citation saved', 'Clipboard unavailable — downloaded as CITATION.txt instead.');
          }
        }
      } catch (err) {
        toast('Export failed', String(err.message || err), 'error');
      }
    });
  }

  /* ============================================================== RENDER == */
  const Views = {
    overview() {
      renderTopbar(); renderKPIs(); DIE.MapView.refresh();
      renderSelectedInfo(); renderRegionSummary();
      renderTimeSeries(); renderDistChart(); renderRanking();
      Evo.ready ? Evo.render(true) : Evo.init();
      setTimeout(() => { DIE.MapView.evoMap && DIE.MapView.evoMap.invalidateSize(); }, 60);
    },
    historical() { Historical.ready ? Historical.renderAll() : Historical.init(); },
    events() { EventsView.ready ? EventsView.refresh() : EventsView.init(); },
    propagation() { Propagation.ready ? Propagation.refresh() : Propagation.init(); },
    data() { DataView.init(); }
  };

  function renderAll() {
    DIE.Filters.resync();
    Views[currentTab] && Views[currentTab]();
  }

  /* ------------------------------------------------------------- public -- */
  DIE.App = { init, toast, renderAll, switchTab, Views };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
