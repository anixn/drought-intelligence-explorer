/* ===========================================================================
 * app.js — application orchestration
 * ---------------------------------------------------------------------------
 *  - Boot sequence (metadata -> boundaries -> registry -> indicator) with
 *    explicit loading and error states.
 *  - Subscribes to state changes and recomputes exactly the affected views.
 *  - Renders: KPI cards (snapshot or period-mean by analysis mode), selected
 *    district and regional summary, charts, historical analytics, comparison
 *    table (sort/search/pagination/export), topbar status chips, footer.
 *  - Analysis tab: Module A (synchronized multi-indicator comparison with
 *    agreement statistics), Module B (animated drought evolution), Module C
 *    (download centre, also available as a modal).
 *  - Modals, fullscreen, mobile drawer, toasts, keyboard accessibility.
 * =========================================================================== */
(function () {
  'use strict';

  const DIE = (window.DIE = window.DIE || {});
  const $ = (id) => document.getElementById(id);
  const A = () => DIE.Analytics;

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

      setBoot('Loading boundaries and registries…', 34);
      await Promise.all([DIE.loader.boundaries(), DIE.loader.registry()]);

      setBoot('Loading indicator ' + DIE.indicatorById.get(DIE.state.indicator).label + '…', 62);
      await DIE.loader.indicator(DIE.state.indicator);

      const ds0 = currentDataset();
      DIE.state.dateIdx = ds0.availableEndIndex >= 0
        ? ds0.availableEndIndex : ds0.dates.length - 1;
      DIE.state.period.from = +(ds0.availableFrom || DIE.meta.period.start).slice(0, 4);
      DIE.state.period.to = +(ds0.availableTo || DIE.meta.period.end).slice(0, 4);

      if (!window.turf) {
        $('tgLabels').disabled = true;
        toast('Turf.js unavailable', 'Map place labels are disabled; all other features unaffected.', 'warn');
      }
      if (!window.Plotly) {
        toast('Plotly unavailable', 'Charts cannot render, but maps, statistics and tables remain functional.', 'warn');
      }

      setBoot('Building interface…', 84);
      DIE.Filters.renderIndicators();
      DIE.Filters.wire();
      DIE.Filters.render();
      DIE.MapView.init();
      DIE.MapView.fitRegion();

      wireShell();
      renderStaticText();
      renderAll();

      setBoot('Ready', 100);
      setTimeout(() => $('bootOverlay').classList.add('is-hidden'), 250);
      console.info('[DIE] ready · base path: ' + DIE.base, DIE_DIAG);
    } catch (err) {
      console.error(err);
      fatal('Failed to initialise',
        String(err && err.message || err) +
        '\n\nTroubleshooting: serve the folder over HTTP and confirm data/metadata.json is reachable at ' + DIE.base + 'data/metadata.json');
    }
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
    });

    // tabs
    $('tabDash').addEventListener('click', () => switchTab('dash'));
    $('tabAnalysis').addEventListener('click', () => switchTab('analysis'));

    // fullscreen
    $('fullscreenBtn').addEventListener('click', () => {
      if (!document.fullscreenElement) {
        (document.documentElement.requestFullscreen || document.documentElement.webkitRequestFullscreen || function () {}).call(document.documentElement);
      } else {
        (document.exitFullscreen || document.webkitExitFullscreen || function () {}).call(document);
      }
    });

    // mobile drawer (the sidebar is always visible above the drawer breakpoint)
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

    // trend toggle
    $('tsTrendChk').addEventListener('change', () => renderTimeSeries());

    // map PNG
    $('mapPngBtn').addEventListener('click', () => DIE.MapView.exportPNG());

    // table controls
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

    // state changes
    DIE.bus.on('state', ({ changed }) => {
      const needsData = changed.some((k) => ['indicator'].includes(k));
      const needsGeo = changed.some((k) => ['extent', 'stateId', 'districtId'].includes(k));
      const needsDate = changed.includes('dateIdx');
      const needsPeriod = changed.some((k) => k === 'period' || k === 'mode');
      const needsMapCfg = changed.some((k) => ['map', 'colourMode', 'basemap'].includes(k));

      const run = (fn) => { try { fn(); } catch (e) { console.error(e); } };

      if (needsData) {
        setBoot('Loading indicator ' + DIE.indicatorById.get(DIE.state.indicator).label + '…', 60);
        DIE.loader.indicator(DIE.state.indicator)
          .then(() => {
            if (DIE.state.dateIdx < 0) DIE.state.dateIdx = currentDataset().dates.length - 1;
            $('bootOverlay').classList.remove('is-hidden');
            setBoot('Ready', 100);
            renderAll();
            setTimeout(() => $('bootOverlay').classList.add('is-hidden'), 200);
          })
          .catch((err) => {
            $('bootOverlay').classList.add('is-hidden');
            toast('Could not load indicator', String(err.message || err), 'error');
          });
        return;
      }
      if (needsMapCfg) run(() => DIE.MapView.refresh());
      if (needsGeo) run(() => { DIE.MapView.fitRegion(); DIE.MapView.refresh(); });
      else if (needsDate) run(() => DIE.MapView.refresh());

      if (needsGeo || needsDate || needsPeriod) run(renderKPIs);
      if (needsGeo || needsDate) run(renderDistChart);
      if (needsGeo || needsPeriod || changed.includes('dateIdx')) run(renderTimeSeries);
      if (needsGeo || needsPeriod) run(renderHistorical);
      if (needsGeo || needsPeriod) run(renderTable);
      if (needsGeo || needsDate) run(renderSelectedInfo);
      if (needsGeo || needsDate) run(renderRegionSummary);
      run(renderTopbar);
      if (Analysis.ready) Analysis.update(changed);
      if (window.innerWidth <= 1024) closeDrawer();
    });

    DIE.bus.on('dataset:loaded', () => run0(renderTopbar));
    function run0(fn) { try { fn(); } catch (e) { console.error(e); } }

    window.addEventListener('resize', debounce(() => {
      if (!drawerMq.matches) closeDrawer();
      if (DIE.MapView.main) DIE.MapView.main.invalidateSize();
      if (Analysis.mapA) Analysis.mapA.invalidateSize();
      if (Analysis.mapB) Analysis.mapB.invalidateSize();
      if (Analysis.evoMap) Analysis.evoMap.invalidateSize();
    }, 250));
  }

  function debounce(fn, ms) {
    let t;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
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

  function switchTab(which) {
    const dash = which === 'dash';
    $('viewDashboard').hidden = !dash;
    $('viewAnalysis').hidden = dash;
    $('tabDash').setAttribute('aria-selected', String(dash));
    $('tabAnalysis').setAttribute('aria-selected', String(!dash));
    $('tabDash').tabIndex = dash ? 0 : -1;
    $('tabAnalysis').tabIndex = dash ? -1 : 0;
    if (!dash) Analysis.init();
    else {
      setTimeout(() => { DIE.MapView.main && DIE.MapView.main.invalidateSize(); }, 60);
    }
  }

  /* ===================================================== STATIC TEXTS === */
  function renderStaticText() {
    $('chipUpdated').textContent = 'Updated · ' + DIE.meta.last_updated;
    const bpEl = $('bannerPeriod');
    if (bpEl) {
      const shortRecords = DIE.meta.indicators
        .filter((i) => i.available_from &&
          +i.available_from.slice(0, 4) > +DIE.meta.period.start.slice(0, 4) + 1)
        .map((i) => i.label + ' from ' + i.available_from.slice(0, 4));
      bpEl.textContent = 'research build · ' + DIE.meta.period.start.slice(0, 4) +
        '–' + DIE.meta.period.end.slice(0, 4) +
        (shortRecords.length ? ' · ' + shortRecords.join(' · ') : '');
    }
    $('aboutCitation').textContent = DIE.meta.citation;
    $('methCitation').textContent = DIE.meta.citation;
    $('methReferencePeriod').textContent = DIE.meta.reference_period;
    const synthetic = /synthetic|demonstration/i.test(String(DIE.meta.data_mode || ''));
    if ($('chipDataMode')) {
      $('chipDataMode').textContent = 'Data mode · ' +
        (DIE.meta.data_mode === 'static-research' ? 'Static research data' : DIE.meta.data_mode);
    }
    if ($('chipDemo')) {
      $('chipDemo').textContent = synthetic ? 'Demonstration · synthetic' : 'Historical · GEE-derived';
      $('chipDemo').title = synthetic
        ? 'All values in this build are synthetic (see Methodology)'
        : 'Indicator values are derived from historical Earth-observation and reanalysis data (see Methodology)';
    }
    let versionText = 'Methodology version ' + DIE.meta.methodology_version +
      ' · data mode: ' + DIE.meta.data_mode + ' · generated ' + DIE.meta.last_updated;
    if (DIE.meta.random_seed !== null && DIE.meta.random_seed !== undefined) {
      versionText += ' (numpy default_rng, seed ' + DIE.meta.random_seed + ')';
    }
    $('methVersion').textContent = versionText;
    $('footerProvenance').textContent = DIE.meta.data_provenance;
    $('footerVersion').textContent = 'v' + DIE.meta.version + ' · methodology ' + DIE.meta.methodology_version +
      ' · ' + (synthetic ? 'demonstration build (synthetic data)' : 'historical research build (GEE-derived data)');

    // methodology classification tables
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

    // sources modal: metadata may use "current"/"recommended" role prefixes, or
    // plain descriptive roles. When no prefix is present every source is current.
    const cur = DIE.meta.sources.filter((s) => /^current\b/i.test(s.role || ''));
    const rec = DIE.meta.sources.filter((s) => /^recommended\b/i.test(s.role || ''));
    const currentSources = cur.length ? cur : DIE.meta.sources;
    const srcRow = (s) => '<tr><td>' + s.name + '</td><td>' + s.description +
      '<br><a href="' + s.url + '" target="_blank" rel="noopener">' + s.url + '</a>' +
      '<br><span class="small">Role: ' + s.role + ' · accessed ' + s.access_date + '</span></td></tr>';
    $('sourcesCurrent').innerHTML = '<table class="src-table">' + currentSources.map(srcRow).join('') + '</table>';
    $('sourcesRecommended').innerHTML = rec.length
      ? '<table class="src-table">' + rec.map(srcRow).join('') + '</table>'
      : '<p class="small">No additional sources are listed for this build.</p>';

    renderDownloads($('downloadsTab'));
    renderDownloads($('downloadsModal'));
    $('sidebarFootMeta').textContent = DIE.meta.period.start + ' … ' + DIE.meta.period.end +
      ' · ' + DIE.meta.temporal_resolution + ' · ' + DIE.meta.spatial_units;
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

    // Per-indicator availability: every source except MODIS NDVI starts in
    // 1981, so surface the exact window instead of implying full coverage.
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

  /* =============================================================== KPIs == */
  function renderKPIs() {
    const ds = currentDataset();
    if (!ds) return;
    const regionIds = ids();
    const isHist = DIE.state.mode !== 'current';
    let s;

    if (!isHist) {
      s = A().regionStats(ds, DIE.state.dateIdx, regionIds);
    } else {
      // period means over the historical scope
      const months = DIE.Filters.seasonMonths();
      const { from, to } = DIE.state.period;
      let aff = 0, sev = 0, meanSum = 0, nMean = 0, nD = 0, nS = 0, nValid = 0, monthsCount = 0;
      const series = A().regionSeries(ds, regionIds);
      // area stats need per-date class computation
      for (let j = 0; j < ds.dates.length; j++) {
        const [y, m] = ds.dates[j].split('-').map(Number);
        if (y < from || y > to || !months.includes(m)) continue;
        const snap = A().regionStats(ds, j, regionIds);
        monthsCount++;
        aff += snap.affectedPct || 0;
        sev += snap.severePct || 0;
        nD += snap.nDrought; nS += snap.nSevere; nValid += snap.n;
        if (Number.isFinite(snap.mean)) { meanSum += snap.mean; nMean++; }
      }
      s = {
        affectedPct: monthsCount ? aff / monthsCount : NaN,
        severePct: monthsCount ? sev / monthsCount : NaN,
        affectedArea: NaN, severeArea: NaN,
        mean: nMean ? meanSum / nMean : NaN,
        nDrought: monthsCount ? nD / monthsCount : NaN,
        nSevere: monthsCount ? nS / monthsCount : NaN,
        n: monthsCount ? nValid / monthsCount : 0,
        districtsTotal: regionIds.length,
        totalArea: regionIds.reduce((t, id) => t + (DIE.registry.districts.get(id)?.area || 0), 0),
        prev: null
      };
      if (Number.isFinite(s.affectedPct)) s.affectedArea = s.affectedPct / 100 * s.totalArea;
      if (Number.isFinite(s.severePct)) s.severeArea = s.severePct / 100 * s.totalArea;
      s.meanClass = DIE.classify(s.mean, ds.indicator);
    }

    const ind = ds.indicator;
    const periodLabel = DIE.state.period.from + '–' + DIE.state.period.to +
      (DIE.state.period.season === 'all' ? '' : ' · ' + $('seasonSelect').selectedOptions[0].textContent);

    // card 1 — drought-affected area
    setKpi('kpiArea', {
      value: Number.isFinite(s.affectedArea) ? DIE.fmt.area(s.affectedArea) : 'N/A',
      share: 'of ' + DIE.fmt.area(s.totalArea) + ' · ' + DIE.fmt.pct(s.affectedPct),
      delta: deltaHtml(s),
      foot: isHist ? 'Mild drought or worse · period-mean ' + periodLabel : 'Mild drought or worse · equal-area km²'
    });

    // card 2 — severe area
    setKpi('kpiSevere', {
      value: Number.isFinite(s.severeArea) ? DIE.fmt.area(s.severeArea) : 'N/A',
      share: 'of ' + DIE.fmt.area(s.totalArea) + ' · ' + DIE.fmt.pct(s.severePct),
      foot: 'Severe + extreme classes · ' + (isHist ? 'period-mean ' + periodLabel : 'equal-area km²')
    });

    // card 3 — intensity
    const c = s.meanClass;
    $('kpiIntensity').querySelector('[data-value]').textContent = DIE.fmt.val(s.mean, ind);
    $('kpiIntensity').querySelector('[data-value]').classList.toggle('is-na', !Number.isFinite(s.mean));
    $('kpiIntensity').querySelector('[data-class]').innerHTML =
      (c ? '<span class="cat-chip" style="background:' + c.color + '">' + c.label + '</span>' : '—') +
      ' <span class="small">(' + ind.label + ', ' + ind.units + ')</span>';
    $('kpiIntensity').querySelector('[data-agg]').textContent =
      'Area-weighted mean · ' + (Number.isFinite(s.n) ? Math.round(s.n) : 0) + '/' + s.districtsTotal +
      ' districts with data' + (isHist ? ' · period-mean ' + periodLabel : ' · ' + DIE.dates.label(DIE.Filters.dateYm() || ''));

    // card 4 — distribution
    const dVal = $('kpiDistricts');
    dVal.querySelector('[data-value]').textContent =
      (Number.isFinite(s.nDrought) ? Math.round(s.nDrought) : 'N/A') + ' / ' + s.districtsTotal;
    dVal.querySelector('[data-severe]').innerHTML =
      '<b style="color:#8F252F">' + (Number.isFinite(s.nSevere) ? Math.round(s.nSevere) : 'N/A') +
      '</b> under severe or extreme drought';
    dVal.querySelector('[data-coverage]').textContent =
      'districts in drought · ' + (isHist ? 'period-mean · ' + periodLabel : DIE.dates.label(DIE.Filters.dateYm() || ''));
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
    if (!s.prev || DIE.state.mode !== 'current') {
      return '<span class="flat">— period-mean mode: no single-period comparison</span>';
    }
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

  /* ==================================================== SELECTED / REGION == */
  function renderSelectedInfo() {
    const ds = currentDataset();
    const box = $('selectedInfo');
    const btn = $('clearSelectionBtn');
    const id = DIE.state.districtId;
    if (!id || !ds) {
      box.innerHTML = '<p class="side-note">Click a district on the map, or choose one in the sidebar.</p>';
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
      '<p class="rail-note">Time-series and KPI cards below now reflect this district.</p>';
    btn.hidden = false;
  }

  function renderRegionSummary() {
    const ds = currentDataset();
    if (!ds) return;
    const regionIds = ids();
    const s = A().regionStats(ds, DIE.state.dateIdx, regionIds);
    const label = DIE.Filters.regionLabel();
    const c = s.meanClass;

    // top affected districts at this date
    const rows = regionIds.map((id) => {
      const i = ds.districtIndex.get(id);
      const v = (i === undefined) ? NaN : ds.values[i][DIE.state.dateIdx];
      return { id, v, d: DIE.registry.districts.get(id) };
    }).filter((r) => r.d && Number.isFinite(r.v))
      .sort((a, b) => a.v - b.v).slice(0, 5);

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
      '<div class="top-list"><div class="top-list-title">Most affected districts · ' +
      DIE.dates.label(DIE.Filters.dateYm() || '') + '</div>' +
      (rows.length ? rows.map((r) => {
        const cc = DIE.classify(r.v, ds.indicator);
        return '<div class="top-list-row"><span class="top-list-name">' + r.d.name + '</span>' +
          DIE.MapView.classChip(cc) +
          '<span class="top-list-val">' + DIE.fmt.val(r.v, ds.indicator) + '</span></div>';
      }).join('') : '<p class="side-note">No valid observations at this date.</p>') +
      '</div>';
  }

  /* ========================================================= CHART ROW == */
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
        ' valid months (see methodology). ' : '') +
      'Spatial unit: district' + (isDistrict ? '' : 's, area-weighted') + '. Source: ' +
      (/synthetic|demonstration/i.test(String(DIE.meta.data_mode || ''))
        ? 'demonstration dataset (synthetic)'
        : 'GEE-derived historical dataset') + '.';
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
      ' total). Wet conditions aggregate all wet classes. Exports: use the camera icon on the chart toolbar. ' +
      (/synthetic|demonstration/i.test(String(DIE.meta.data_mode || ''))
        ? 'Demonstration data.'
        : 'GEE-derived historical data.');
  }

  /* ================================================== HISTORICAL ROW 4 == */
  function renderHistorical() {
    const ds = currentDataset();
    if (!ds) return;
    const regionIds = ids();
    const h = A().historicalSummary(ds, regionIds, DIE.state.period, DIE.state.period.season);
    const label = DIE.Filters.regionLabel();
    const periodLabel = DIE.state.period.from + '–' + DIE.state.period.to +
      (DIE.state.period.season === 'all' ? '' : ' · ' + $('seasonSelect').selectedOptions[0].textContent);

    $('freqMeta').textContent = label + ' · ' + periodLabel;
    $('freqStats').innerHTML =
      '<span class="stat"><b>' + h.droughtMonths + '</b><i>months in drought (of ' + h.validScopeMonths + ' valid)</i></span>' +
      '<span class="stat"><b>' + h.nEvents + '</b><i>drought events (runs ≥ 3 months)</i></span>' +
      '<span class="stat"><b>' + DIE.fmt.pct(h.droughtMonths / Math.max(1, h.validScopeMonths) * 100) + '</b><i>of valid months</i></span>';
    DIE.Charts.frequencyByYear($('freqChart'), { years: h.years, counts: h.counts });

    $('durMeta').textContent = label + ' · ' + periodLabel;
    $('durStats').innerHTML =
      statCell(h.duration.mean, 'mean duration (months)') +
      statCell(h.duration.median, 'median duration (months)') +
      statCell(h.duration.max, 'max duration (months)');
    $('durNote').textContent = 'Event definition: runs analysis — ≥3 consecutive months with ' +
      ds.indicator.label + ' ≤ ' + h.threshold.toString().replace('-', '−') +
      ' (upper bound of the moderate-drought class). ' + h.nEvents + ' events identified.';

    $('sevMeta').textContent = label + ' · ' + periodLabel;
    $('sevStats').innerHTML =
      statCell(h.severity.total, 'cumulative severity (Σ deficit)') +
      statCell(h.severity.meanIntensity, 'mean event intensity') +
      statCell(h.severity.worst ? h.severity.worst.severity : NaN,
        'worst event' + (h.severity.worst ? ' (' + h.severity.worst.startDate + ' → ' + h.severity.worst.endDate + ')' : ''));
    $('sevNote').textContent = 'Severity = cumulative deficit below the ' +
      h.threshold.toString().replace('-', '−') + ' truncation level over event months; intensity = severity ÷ duration. Continuous monthly series (season filter applies to frequency only).';
  }

  function statCell(v, label) {
    const shown = Number.isFinite(v) ? (Math.round(v * 100) / 100) : '—';
    return '<div class="stat-cell"><b>' + shown + '</b><i>' + label + '</i></div>';
  }

  /* ==================================================== COMPARISON TABLE == */
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

    // highlight the five most affected regions with adequate completeness
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
    $('tableMeta').textContent = ds.indicator.label + ' · ' + DIE.state.period.from + '–' + DIE.state.period.to +
      ' · ' + ($('seasonSelect').selectedOptions[0].textContent);

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
    A().toCSV('die-comparison-' + level + '-' + ds.indicator.id + '-' +
      DIE.state.period.from + '-' + DIE.state.period.to + '.csv', rows);
    toast('Table exported', rows.length - 1 + ' regions saved as CSV.');
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
    const ind = () => DIE.indicatorById.get(DIE.state.indicator);
    container.innerHTML =
      '<div class="dl-group-title">Datasets (CSV, generated client-side)</div>' +
      '<div class="dl-card"><div class="dl-title">Region extract — long format</div>' +
      '<div class="dl-desc">All districts of the current region, full monthly record, with classification and equal-area district statistics.</div>' +
      '<div class="dl-meta" data-meta="region">—</div>' +
      '<div class="dl-actions"><button class="btn btn-solid" data-dl="region">Download CSV</button></div></div>' +

      '<div class="dl-card"><div class="dl-title">Selected indicator dataset</div>' +
      '<div class="dl-desc">The distributed wide-format matrix (districts × months) for the current indicator, exactly as loaded.</div>' +
      '<div class="dl-meta">' + 'CSV · ~0.9 MB' + '</div>' +
      '<div class="dl-actions"><button class="btn" data-dl="indicator">Download file</button></div></div>' +

      '<div class="dl-card"><div class="dl-title">District drought summary</div>' +
      '<div class="dl-desc">Per-district statistics over the selected historical period: mean, extremes, drought months, event count, durations, cumulative severity, completeness.</div>' +
      '<div class="dl-meta" data-meta="summary">—</div>' +
      '<div class="dl-actions"><button class="btn" data-dl="summary">Download CSV</button></div></div>' +

      '<div class="dl-card"><div class="dl-title">Precomputed summaries</div>' +
      '<div class="dl-desc">Reproducibility cross-checks shipped with the build: drought events (SPI-6, runs analysis) and state statistics.</div>' +
      '<div class="dl-meta">static artifacts</div>' +
      '<div class="dl-actions">' +
      '<a class="btn" href="' + DIE.base + 'data/summaries/drought_events_spi_06.csv" download>drought_events_spi_06.csv</a>' +
      '<a class="btn" href="' + DIE.base + 'data/summaries/state_statistics_spi_06.csv" download>state_statistics_spi_06.csv</a>' +
      '</div></div>' +

      '<div class="dl-group-title">Figures</div>' +
      '<div class="dl-card"><div class="dl-title">Current map (PNG)</div>' +
      '<div class="dl-desc">Renders the current map view, legend colours and selection. Vector layers are captured directly; use the Plain basemap if tile capture fails.</div>' +
      '<div class="dl-meta">rasterises the live DOM</div>' +
      '<div class="dl-actions"><button class="btn" data-dl="map">Export map PNG</button></div></div>' +

      '<div class="dl-card"><div class="dl-title">Charts (PNG)</div>' +
      '<div class="dl-desc">Every Plotly chart (time series, distribution, comparison scatter, timeline) exports via the camera icon in its own toolbar — the export always reflects the current selection.</div>' +
      '<div class="dl-meta">built into each chart</div>' +
      '<div class="dl-actions"><button class="btn" data-dl="charts" disabled>See chart toolbars</button></div></div>' +

      '<div class="dl-group-title">Documentation</div>' +
      '<div class="dl-card"><div class="dl-title">Methodology (Markdown)</div>' +
      '<div class="dl-desc">Full indicator definitions, classification thresholds, standardization, aggregation, event identification, missing-data policy and limitations.</div>' +
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
          const n = A().longExportCSV(ds, ids());
          toast('Export complete', n + ' district-month records written (long format).');
        } else if (kind === 'indicator') {
          const text = await DIE.loader.fetchText(ind().file);
          A().toText('die-' + ind().id + '-wide.csv', text, 'text/csv;charset=utf-8');
          toast('Export complete', 'Wide-format matrix saved.');
        } else if (kind === 'summary') {
          const ds = currentDataset();
          const n = A().districtSummaryCSV(ds, ids(), DIE.state.period);
          toast('Export complete', n + ' district summaries written.');
        } else if (kind === 'map') {
          await DIE.MapView.exportPNG();
        } else if (kind === 'methodology' || kind === 'datasources') {
          const file = kind === 'methodology' ? 'docs/methodology.md' : 'docs/data-sources.md';
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

  /* ================================================ ANALYSIS MODULES ==== */
  const Analysis = {
    ready: false, evoIdx: 0, playing: null, timer: null,
    init() {
      if (this.ready || !window.L) return;
      this.ready = true;
      this.initModuleA();
      this.initModuleB();
      setTimeout(() => {
        this.mapA && this.mapA.invalidateSize();
        this.mapB && this.mapB.invalidateSize();
        this.evoMap && this.evoMap.invalidateSize();
      }, 60);
      this.update(['indicator']);
    },

    /* ---------------- Module A: multi-indicator comparison --------------- */
    initModuleA() {
      const opts = DIE.meta.indicators.map((i) => [i.id, i.label + ' (' + i.units + ')']);
      const fill = (sel, def) => {
        sel.innerHTML = opts.map(([v, l]) => '<option value="' + v + '"' + (v === def ? ' selected' : '') + '>' + l + '</option>').join('');
      };
      fill($('cmpIndA'), 'spi_3');
      fill($('cmpIndB'), 'spei_3');
      const ds = currentDataset();
      $('cmpDate').innerHTML = ds.dates.map((ym, j) =>
        '<option value="' + j + '"' + (j === DIE.state.dateIdx ? ' selected' : '') + '>' + DIE.dates.label(ym) + '</option>').join('');

      const viewA = { ds: null, idx: null };
      const viewB = { ds: null, idx: null, mode: 'b' };

      this.mapA = DIE.MapView.createChoropleth('mapA', {
        getContext: () => ({ dataset: viewA.ds, dateIdx: viewA.idx })
      });
      this.mapB = DIE.MapView.createChoropleth('mapB', {
        getContext: () => ({ dataset: viewB.mode === 'b' ? viewB.ds : null, dateIdx: viewB.idx })
      });
      // synchronise views
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

      const render = async () => {
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

          // statistics
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
            ' (B). ' + (/synthetic|demonstration/i.test(String(DIE.meta.data_mode || ''))
              ? 'Demonstration data.'
              : 'GEE-derived historical data.');
        } catch (err) {
          toast('Comparison failed', String(err.message || err), 'error');
        }
      };

      ['cmpIndA', 'cmpIndB', 'cmpDate'].forEach((id) => $(id).addEventListener('change', render));
      document.querySelectorAll('input[name="cmpView"]').forEach((r) => r.addEventListener('change', render));
      this.renderA = render;
      render();
    },

    /* ---------------- Module B: drought evolution ------------------------ */
    initModuleB() {
      const ds = currentDataset();
      this.evoIdx = DIE.state.dateIdx;
      const slider = $('evoSlider');
      slider.max = String(ds.dates.length - 1);
      slider.value = String(this.evoIdx);

      this.evoMap = DIE.MapView.createChoropleth('evoMap', {
        getContext: () => ({ dataset: currentDataset(), dateIdx: Analysis.evoIdx })
      });
      DIE.MapView.renderLegend($('evoLegend'), ds.indicator, 'classes', {
        note: 'Classes update with the sidebar indicator selection.'
      });

      const renderFrame = () => {
        const d = currentDataset();
        const a = d.availableStartIndex || 0;
        const b = d.availableEndIndex >= 0 ? d.availableEndIndex : d.dates.length - 1;
        if (this.evoIdx < a) this.evoIdx = a;
        if (this.evoIdx > b) this.evoIdx = b;
        slider.min = String(a);
        slider.max = String(b);
        const ym = d.dates[this.evoIdx];
        $('evoDateLabel').textContent = DIE.dates.label(ym);
        slider.value = String(this.evoIdx);
        this.evoMap.applyData(d, this.evoIdx, DIE.state.colourMode, DIE.state.districtId);
        DIE.MapView.renderLegend($('evoLegend'), d.indicator, DIE.state.colourMode, {
          note: 'Missing months render as no-data; values are never interpolated.'
        });
        const series = A().droughtAreaPctSeries(d, ids());
        DIE.Charts.areaTimeline($('evoTimeline'), { dates: series.dates, pct: series.pct, frameIdx: this.evoIdx });
        $('evoFoot').textContent = d.indicator.label + ' · ' + DIE.Filters.regionLabel() +
          ' · % of region area in mild-or-worse drought · frame ' + (this.evoIdx - a + 1) + '/' + (b - a + 1) +
          ' · ' + (/synthetic|demonstration/i.test(String(DIE.meta.data_mode || ''))
            ? 'demonstration data (synthetic)'
            : 'GEE-derived research data') + '.';
      };

      const step = (delta) => {
        const d = currentDataset();
        const a = d.availableStartIndex || 0;
        const b = d.availableEndIndex >= 0 ? d.availableEndIndex : d.dates.length - 1;
        this.evoIdx = Math.max(a, Math.min(b, this.evoIdx + delta));
        renderFrame();
      };
      $('evoPrev').addEventListener('click', () => step(-1));
      $('evoNext').addEventListener('click', () => step(1));
      slider.addEventListener('input', () => { this.evoIdx = +slider.value; renderFrame(); });

      $('evoPlay').addEventListener('click', () => {
        if (this.playing) {
          clearInterval(this.playing);
          this.playing = null;
          $('evoPlay').textContent = 'Play';
        } else {
          $('evoPlay').textContent = 'Pause';
          this.playing = setInterval(() => {
            const d = currentDataset();
            const a = d.availableStartIndex || 0;
            const b = d.availableEndIndex >= 0 ? d.availableEndIndex : d.dates.length - 1;
            this.evoIdx = this.evoIdx >= b ? a : this.evoIdx + 1;
            renderFrame();
          }, 900);
        }
      });

      this.renderB = renderFrame;
      renderFrame();
    },

    update(changed) {
      if (this.renderA && (changed.includes('indicator') || changed.includes('dateIdx'))) this.renderA();
      if (this.renderB && (changed.includes('indicator') || changed.includes('districtId') ||
          changed.includes('stateId') || changed.includes('extent'))) {
        const d = currentDataset();
        if (d) { this.evoIdx = Math.min(this.evoIdx, d.dates.length - 1); this.renderB(); }
      }
    }
  };

  /* ================================================== VALIDATION REPORT == */
  function renderValidationReport() {
    const box = $('validationReport');
    if (!box) return;
    const lines = [];
    DIE.datasets.forEach((ds) => {
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
    box.innerHTML = lines.join('<br>') || '<p class="side-note">Load an indicator to validate.</p>';
  }

  /* ============================================================== RENDER == */
  function renderAll() {
    DIE.Filters.resync();
    renderTopbar();
    renderKPIs();
    DIE.MapView.refresh();
    renderSelectedInfo();
    renderRegionSummary();
    renderTimeSeries();
    renderDistChart();
    renderHistorical();
    renderTable();
    renderValidationReport();
    if (Analysis.ready) Analysis.update(['indicator']);
  }

  /* ------------------------------------------------------------- public -- */
  DIE.App = { init, toast, renderAll, switchTab, renderValidationReport, Analysis };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
