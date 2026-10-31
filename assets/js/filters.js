/* ===========================================================================
 * filters.js — control sidebar and application state
 * ---------------------------------------------------------------------------
 * Owns the single mutable application state object and every sidebar
 * control. All mutations flow through Filters.set(patch), which keeps
 * dependent options consistent (state -> district cascade, year/month ->
 * date index -> slider) and emits a `state` event with the list of changed
 * keys. Other modules never mutate state directly.
 * =========================================================================== */
(function () {
  'use strict';

  const DIE = (window.DIE = window.DIE || {});
  const $ = (id) => document.getElementById(id);

  const DEFAULTS = () => ({
    extent: 'india',
    stateId: null,
    districtId: null,
    indicator: 'spi_3',
    dateIdx: -1,                 // resolved against the loaded dataset
    period: { from: null, to: null, season: 'all' },
    mode: 'current',
    map: { districts: true, states: true, outline: true, labels: false },
    colourMode: 'classes',
    basemap: 'plain'
  });

  DIE.state = DEFAULTS();

  const Filters = (DIE.Filters = {
    /* -------------------------------------------------------------- query -- */
    /** District ids currently in scope for the geographic selection.
     *  A selected district always takes precedence (map click or dropdown). */
    regionIds() {
      const st = DIE.state;
      if (st.districtId) return [st.districtId];
      if (st.stateId) return (DIE.registry.byState.get(st.stateId) || []).map((d) => d.id);
      return Array.from(DIE.registry.districts.keys());
    },
    regionLabel() {
      const st = DIE.state;
      if (st.districtId) {
        const d = DIE.registry.districts.get(st.districtId);
        return d ? d.name + ', ' + d.state : 'District';
      }
      if (st.stateId) {
        const s = DIE.registry.states.get(st.stateId);
        return s ? s.name : 'State';
      }
      return 'All India';
    },
    regionType() {
      return DIE.state.districtId ? 'district' : DIE.state.stateId ? 'state' : 'india';
    },
    dateYm() {
      const ds = DIE.datasets.get(DIE.state.indicator);
      return ds ? ds.dates[DIE.state.dateIdx] : null;
    },
    seasonMonths() {
      return DIE.meta.seasons[DIE.state.period.season] || DIE.meta.seasons.all;
    },

    /* --------------------------------------------------------------- set --- */
    set(patch, opts) {
      const changed = [];
      const before = JSON.stringify({ ...DIE.state, period: { ...DIE.state.period }, map: { ...DIE.state.map } });

      Object.keys(patch).forEach((k) => {
        if (k === 'period' || k === 'map') {
          Object.assign(DIE.state[k], patch[k]);
        } else {
          DIE.state[k] = patch[k];
        }
      });
      normalise();

      const after = JSON.stringify({ ...DIE.state, period: { ...DIE.state.period }, map: { ...DIE.state.map } });
      if (after !== before) {
        // derive changed keys
        const a = JSON.parse(before), b = JSON.parse(after);
        Object.keys(b).forEach((k) => { if (JSON.stringify(a[k]) !== JSON.stringify(b[k])) changed.push(k); });
        DIE.bus.emit('state', { state: DIE.state, changed });
        if (!(opts && opts.silentUI)) renderControls();
      }
      return changed;
    },

    reset() {
      const indicator = DIE.state.indicator;
      DIE.state = DEFAULTS();
      DIE.state.indicator = indicator;
      const ds = DIE.datasets.get(indicator);
      if (ds) DIE.state.dateIdx = ds.dates.length - 1;
      DIE.state.period.from = +DIE.meta.period.start.slice(0, 4);
      DIE.state.period.to = +DIE.meta.period.end.slice(0, 4);
      renderControls();
      DIE.bus.emit('state', { state: DIE.state, changed: ['extent', 'stateId', 'districtId', 'dateIdx', 'period', 'mode', 'map'] });
    }
  });

  /* ------------------------------------------------------------- helpers -- */
  function normalise() {
    const st = DIE.state;
    const ds = DIE.datasets.get(st.indicator);
    const y0 = +DIE.meta.period.start.slice(0, 4), y1 = +DIE.meta.period.end.slice(0, 4);

    if (ds) {
      if (st.dateIdx < 0 || st.dateIdx >= ds.dates.length) st.dateIdx = ds.dates.length - 1;
    }
    if (st.extent === 'india') { st.stateId = null; st.districtId = null; }
    // A district selection is valid in both 'state' and 'district' extents:
    // regionIds() gives it precedence, and the map/dropdown can clear it.
    if (st.extent === 'district' && !st.stateId) {
      if (st.districtId) {
        const d = DIE.registry.districts.get(st.districtId);
        if (d) { st.stateId = d.sid; } else { st.districtId = null; }
      }
    }
    if (st.stateId && !DIE.registry.states.has(st.stateId)) { st.stateId = null; st.districtId = null; }
    if (st.districtId) {
      const d = DIE.registry.districts.get(st.districtId);
      if (!d || (st.stateId && d.sid !== st.stateId)) st.districtId = null;
    }
    if (st.period.from == null) st.period.from = y0;
    if (st.period.to == null) st.period.to = y1;
    st.period.from = Math.min(Math.max(st.period.from, y0), y1);
    st.period.to = Math.min(Math.max(st.period.to, st.period.from), y1);
  }

  function optionList(select, items, selected) {
    select.innerHTML = '';
    items.forEach(([val, label, disabled]) => {
      const o = document.createElement('option');
      o.value = val; o.textContent = label;
      if (disabled) o.disabled = true;
      if (val === selected) o.selected = true;
      select.appendChild(o);
    });
  }

  /* --------------------------------------------------- sidebar rendering -- */
  function renderStates() {
    const st = DIE.state;
    const sel = $('stateSelect');
    const states = Array.from(DIE.registry.states.values())
      .sort((a, b) => a.name.localeCompare(b.name));
    optionList(sel, [['', '— select state —']].concat(states.map((s) => [s.id, s.name])), st.stateId || '');
    sel.disabled = st.extent === 'india';
  }

  function renderDistricts() {
    const st = DIE.state;
    const sel = $('districtSelect');
    if (!st.stateId) {
      optionList(sel, [['', st.extent === 'district' ? '— select state first —' : '— select state —']], '');
      sel.disabled = true;
      return;
    }
    const list = DIE.registry.byState.get(st.stateId) || [];
    optionList(sel, [['', '— all districts —']].concat(list.map((d) => [d.id, d.name])), st.districtId || '');
    sel.disabled = false;
  }

  function renderTemporal() {
    const ds = DIE.datasets.get(DIE.state.indicator);
    const y0 = +DIE.meta.period.start.slice(0, 4), y1 = +DIE.meta.period.end.slice(0, 4);
    const years = [];
    for (let y = y0; y <= y1; y++) years.push([String(y), String(y)]);

    const ym = ds ? ds.dates[DIE.state.dateIdx] : DIE.meta.period.end;
    const [yy, mm] = ym.split('-');

    optionList($('yearSelect'), years, yy);
    optionList($('monthSelect'), DIE.dates.monthsShort.map((m, i) => [
      String(i + 1).padStart(2, '0'), m
    ]), mm);

    const slider = $('dateSlider');
    if (ds) {
      slider.max = String(ds.dates.length - 1);
      slider.value = String(DIE.state.dateIdx);
      slider.disabled = false;
      $('dateSliderLabel').textContent = DIE.dates.label(ym) + ' · obs ' + (DIE.state.dateIdx + 1) + '/' + ds.dates.length;
    } else {
      slider.disabled = true;
      $('dateSliderLabel').textContent = '—';
    }

    optionList($('fromYearSelect'), years, String(DIE.state.period.from));
    optionList($('toYearSelect'), years, String(DIE.state.period.to));
    $('seasonSelect').value = DIE.state.period.season;
  }

  const FAMILY_LABELS = {
    spi: 'Meteorological — Standardized Precipitation Index',
    spei: 'Water balance — SPEI (P − PET)',
    land: 'Land surface'
  };

  function renderIndicators() {
    const box = $('indicatorList');
    box.innerHTML = '';
    const families = ['spi', 'spei', 'land'];
    families.forEach((fam) => {
      const h = document.createElement('div');
      h.className = 'ind-group-label';
      h.textContent = FAMILY_LABELS[fam];
      box.appendChild(h);
      DIE.meta.indicators.filter((i) => i.family === fam).forEach((ind) => {
        const label = document.createElement('label');
        label.className = 'ind-opt';
        const input = document.createElement('input');
        input.type = 'radio'; input.name = 'indicator'; input.value = ind.id;
        input.checked = ind.id === DIE.state.indicator;
        input.setAttribute('aria-label', ind.label);
        const body = document.createElement('span');
        body.className = 'ind-body';
        body.innerHTML = '<span class="ind-name">' + ind.label + '</span>' +
          '<span class="ind-units">' + ind.units + '</span>';
        const tip = document.createElement('span');
        tip.className = 'tip'; tip.tabIndex = 0;
        tip.setAttribute('data-tip', ind.tooltip);
        tip.setAttribute('aria-label', ind.label + ' description');
        tip.textContent = '?';
        body.appendChild(tip);
        label.appendChild(input); label.appendChild(body);
        box.appendChild(label);
      });
    });
  }

  function renderControls() {
    renderStates();
    renderDistricts();
    renderTemporal();
    document.querySelectorAll('input[name="analysisMode"]').forEach((r) => {
      r.checked = r.value === DIE.state.mode;
    });
    $('extentSelect').value = DIE.state.extent;
    $('tgDistricts').checked = DIE.state.map.districts;
    $('tgStates').checked = DIE.state.map.states;
    $('tgOutline').checked = DIE.state.map.outline;
    $('tgLabels').checked = DIE.state.map.labels;
  }

  /* ------------------------------------------------------------ wiring --- */
  function wire() {
    $('extentSelect').addEventListener('change', (e) => {
      const v = e.target.value;
      Filters.set(v === 'india' ? { extent: v, stateId: null, districtId: null }
        : v === 'state' ? { extent: v, districtId: null }
        : { extent: v });
    });
    $('stateSelect').addEventListener('change', (e) => {
      Filters.set({ stateId: e.target.value || null, districtId: null });
    });
    $('districtSelect').addEventListener('change', (e) => {
      Filters.set({ districtId: e.target.value || null });
    });

    $('indicatorList').addEventListener('change', (e) => {
      if (e.target.name === 'indicator') Filters.set({ indicator: e.target.value, dateIdx: -1 });
    });

    const applyYm = () => {
      const ds = DIE.datasets.get(DIE.state.indicator);
      if (!ds) return;
      const y = $('yearSelect').value, m = $('monthSelect').value;
      const ym = y + '-' + m;
      const idx = ds.dateIndex.get(ym);
      if (idx !== undefined) Filters.set({ dateIdx: idx });
    };
    $('yearSelect').addEventListener('change', applyYm);
    $('monthSelect').addEventListener('change', applyYm);
    $('dateSlider').addEventListener('input', (e) => {
      Filters.set({ dateIdx: +e.target.value });
    });

    $('fromYearSelect').addEventListener('change', (e) => {
      const from = +e.target.value;
      const patch = { period: { from } };
      if (DIE.state.period.to < from) patch.period.to = from;
      Filters.set(patch);
    });
    $('toYearSelect').addEventListener('change', (e) => {
      const to = +e.target.value;
      const patch = { period: { to } };
      if (DIE.state.period.from > to) patch.period.from = to;
      Filters.set(patch);
    });
    $('seasonSelect').addEventListener('change', (e) => {
      Filters.set({ period: { season: e.target.value } });
    });

    document.querySelectorAll('input[name="analysisMode"]').forEach((r) => {
      r.addEventListener('change', () => Filters.set({ mode: r.value }));
    });

    $('tgDistricts').addEventListener('change', (e) => Filters.set({ map: { districts: e.target.checked } }));
    $('tgStates').addEventListener('change', (e) => Filters.set({ map: { states: e.target.checked } }));
    $('tgOutline').addEventListener('change', (e) => Filters.set({ map: { outline: e.target.checked } }));
    $('tgLabels').addEventListener('change', (e) => Filters.set({ map: { labels: e.target.checked } }));
    $('resetBtn').addEventListener('click', () => Filters.reset());

    // colour mode + basemap live in the map panel (map.js consumes them)
    $('colourMode').addEventListener('change', (e) => Filters.set({ colourMode: e.target.value }));
    $('basemapSelect').addEventListener('change', (e) => Filters.set({ basemap: e.target.value }));
  }

  /* ------------------------------------------------------------- public -- */
  Filters.renderIndicators = renderIndicators;
  Filters.render = renderControls;
  Filters.wire = wire;
})();
