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
    /**
     * Apply a patch to the shared state.
     * opts.silentUI  — skip sidebar re-render (used while dragging a slider).
     * opts.transient — hint to views that this is an in-progress update; they
     *                  may update cheap layers only and defer heavy charts.
     * opts.force     — emit even when the normalised state did not change
     *                  (the slider's final `change` after a transient drag).
     */
    set(patch, opts) {
      const before = snapshotState(DIE.state);

      Object.keys(patch).forEach((k) => {
        if (k === 'period' || k === 'map') {
          Object.assign(DIE.state[k], patch[k]);
        } else {
          DIE.state[k] = patch[k];
        }
      });
      normalise();

      const changed = diffState(before, DIE.state);
      if (changed.length || (opts && opts.force)) {
        const payloadChanged = changed.length ? changed : Object.keys(patch);
        DIE.bus.emit('state', {
          state: DIE.state,
          changed: payloadChanged,
          transient: !!(opts && opts.transient)
        });
        if (!(opts && opts.silentUI)) renderControls(payloadChanged);
      }
      return changed;
    },

    reset() {
      const indicator = DIE.state.indicator;
      DIE.state = DEFAULTS();
      DIE.state.indicator = indicator;
      const ds = DIE.datasets.get(indicator);
      if (ds) DIE.state.dateIdx = ds.availableEndIndex >= 0 ? ds.availableEndIndex : ds.dates.length - 1;
      DIE.state.period.from = ds && ds.availableFrom
        ? +ds.availableFrom.slice(0, 4) : +DIE.meta.period.start.slice(0, 4);
      DIE.state.period.to = ds && ds.availableTo
        ? +ds.availableTo.slice(0, 4) : +DIE.meta.period.end.slice(0, 4);
      try { if (DIE.Telemetry) DIE.Telemetry.track('reset_filters', {}); } catch (e) {}
      renderControls();
      DIE.bus.emit('state', { state: DIE.state, changed: ['extent', 'stateId', 'districtId', 'dateIdx', 'period', 'map'] });
    }
  });

  /* ------------------------------------------------------------- helpers -- */
  /** Shallow snapshot of the state fields that participate in change events. */
  function snapshotState(st) {
    return {
      extent: st.extent, stateId: st.stateId, districtId: st.districtId,
      indicator: st.indicator, dateIdx: st.dateIdx,
      period: { from: st.period.from, to: st.period.to, season: st.period.season },
      map: { districts: st.map.districts, states: st.map.states, outline: st.map.outline, labels: st.map.labels },
      colourMode: st.colourMode, basemap: st.basemap
    };
  }
  /** Compare two snapshots and return the changed top-level keys. */
  function diffState(a, b) {
    const changed = [];
    Object.keys(b).forEach((k) => {
      const av = a[k], bv = b[k];
      if (av && bv && typeof av === 'object') {
        if (Object.keys(bv).some((kk) => av[kk] !== bv[kk])) changed.push(k);
      } else if (av !== bv) {
        changed.push(k);
      }
    });
    return changed;
  }

  function normalise() {
    const st = DIE.state;
    const ds = DIE.datasets.get(st.indicator);
    const y0 = +DIE.meta.period.start.slice(0, 4), y1 = +DIE.meta.period.end.slice(0, 4);
    // Indicators that depend on a shorter input record (VCI/MODIS starts in
    // 2000) cannot be analysed before their first valid month.  Clamp the
    // lower year so charts and statistics do not show empty decades.
    const yAvailStart = ds && ds.availableFrom
      ? +ds.availableFrom.slice(0, 4) : y0;
    const yMin = Math.max(y0, yAvailStart);

    if (ds) {
      if (st.dateIdx < 0 || st.dateIdx >= ds.dates.length) st.dateIdx = ds.dates.length - 1;
      if (ds.availableEndIndex >= 0 && st.dateIdx > ds.availableEndIndex) {
        st.dateIdx = ds.availableEndIndex;
      }
      if (ds.availableStartIndex <= ds.availableEndIndex &&
          st.dateIdx < ds.availableStartIndex) {
        st.dateIdx = ds.availableStartIndex;
      }
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
    if (st.period.from == null) st.period.from = yMin;
    if (st.period.to == null) st.period.to = y1;
    st.period.from = Math.min(Math.max(st.period.from, yMin), y1);
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
    // Offer only years that this indicator can actually cover.
    const ya = ds && ds.availableFrom ? +ds.availableFrom.slice(0, 4) : y0;
    const yb = ds && ds.availableTo ? +ds.availableTo.slice(0, 4) : y1;
    const years = [];
    for (let y = Math.max(y0, ya); y <= Math.min(y1, yb); y++) {
      years.push([String(y), String(y)]);
    }

    const ym = ds ? ds.dates[DIE.state.dateIdx] : DIE.meta.period.end;
    const [yy, mm] = ym.split('-');

    optionList($('yearSelect'), years, yy);
    optionList($('monthSelect'), DIE.dates.monthsShort.map((m, i) => [
      String(i + 1).padStart(2, '0'), m
    ]), mm);

    const slider = $('dateSlider');
    if (ds) {
      const a = ds.availableStartIndex || 0;
      const b = ds.availableEndIndex >= 0 ? ds.availableEndIndex : ds.dates.length - 1;
      slider.min = String(a);
      slider.max = String(b);
      slider.value = String(DIE.state.dateIdx);
      slider.disabled = false;
      $('dateSliderLabel').textContent = DIE.dates.label(ym) + ' · obs ' +
        (DIE.state.dateIdx - a + 1) + '/' + (b - a + 1);
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

  /**
   * Rebuild only the controls affected by a state change. During slider
   * dragging renderControls is skipped entirely and syncTemporalValue()
   * updates the label/selects in place, which keeps interaction at 60 fps.
   */
  function syncIndicatorChecks() {
    document.querySelectorAll('input[name="indicator"]').forEach((input) => {
      input.checked = input.value === DIE.state.indicator;
    });
  }

  function renderControls(changed) {
    const has = (k) => !changed || changed.indexOf(k) !== -1;
    if (has('extent') || has('stateId')) renderStates();
    if (has('extent') || has('stateId') || has('districtId')) renderDistricts();
    if (has('indicator')) syncIndicatorChecks();
    if (has('indicator') || has('dateIdx') || has('period')) renderTemporal();
    if (has('extent')) $('extentSelect').value = DIE.state.extent;
    if (has('map')) {
      $('tgDistricts').checked = DIE.state.map.districts;
      $('tgStates').checked = DIE.state.map.states;
      $('tgOutline').checked = DIE.state.map.outline;
      $('tgLabels').checked = DIE.state.map.labels;
    }
  }

  /** Cheap in-place sync used on slider `input` (no option rebuilds). */
  function syncTemporalValue() {
    const ds = DIE.datasets.get(DIE.state.indicator);
    if (!ds) return;
    const ym = ds.dates[DIE.state.dateIdx];
    if (ym) {
      const [yy, mm] = ym.split('-');
      if ($('yearSelect').value !== yy) $('yearSelect').value = yy;
      if ($('monthSelect').value !== mm) $('monthSelect').value = mm;
      const a = ds.availableStartIndex || 0;
      const b = ds.availableEndIndex >= 0 ? ds.availableEndIndex : ds.dates.length - 1;
      $('dateSliderLabel').textContent = DIE.dates.label(ym) + ' · obs ' +
        (DIE.state.dateIdx - a + 1) + '/' + (b - a + 1);
    }
    const slider = $('dateSlider');
    if (slider.value !== String(DIE.state.dateIdx)) slider.value = String(DIE.state.dateIdx);
  }

  /* ------------------------------------------------------------ wiring --- */
  function wire() {
    /* Discrete, potentially slow selections (geography, indicator, period)
       show the progress cursor for the recompute: deferBusy paints the
       busy state first, then runs the synchronous update, then restores. */
    const slow = (fn) => { if (DIE.deferBusy) DIE.deferBusy(fn); else fn(); };

    $('extentSelect').addEventListener('change', (e) => {
      const v = e.target.value;
      slow(() => Filters.set(v === 'india' ? { extent: v, stateId: null, districtId: null }
        : v === 'state' ? { extent: v, districtId: null }
        : { extent: v }));
    });
    $('stateSelect').addEventListener('change', (e) => {
      slow(() => Filters.set({ stateId: e.target.value || null, districtId: null }));
    });
    $('districtSelect').addEventListener('change', (e) => {
      slow(() => Filters.set({ districtId: e.target.value || null }));
    });

    $('indicatorList').addEventListener('change', (e) => {
      if (e.target.name === 'indicator') {
        slow(() => Filters.set({
          indicator: e.target.value,
          dateIdx: -1,
          period: { from: null, to: null }
        }));
      }
    });

    // Warm the CSV cache when the user shows intent (hover/focus), so the
    // swap after clicking an indicator is nearly instant.
    const prefetchIndicator = (id) => {
      if (DIE.loader && DIE.loader.prefetchIndicator) DIE.loader.prefetchIndicator(id);
    };
    $('indicatorList').addEventListener('pointerover', (e) => {
      const input = e.target.closest && e.target.closest('input[name="indicator"]');
      if (input) prefetchIndicator(input.value);
    });
    $('indicatorList').addEventListener('focusin', (e) => {
      if (e.target.name === 'indicator') prefetchIndicator(e.target.value);
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
    // Dragging: update state + cheap controls only (transient views react to
    // the `transient` flag; charts wait for the final `change` event).
    $('dateSlider').addEventListener('input', (e) => {
      Filters.set({ dateIdx: +e.target.value }, { silentUI: true, transient: true });
      syncTemporalValue();
    });
    $('dateSlider').addEventListener('change', (e) => {
      Filters.set({ dateIdx: +e.target.value }, { force: true });
    });

    $('fromYearSelect').addEventListener('change', (e) => {
      const from = +e.target.value;
      const patch = { period: { from } };
      if (DIE.state.period.to < from) patch.period.to = from;
      slow(() => Filters.set(patch));
    });
    $('toYearSelect').addEventListener('change', (e) => {
      const to = +e.target.value;
      const patch = { period: { to } };
      if (DIE.state.period.from > to) patch.period.from = to;
      slow(() => Filters.set(patch));
    });
    $('seasonSelect').addEventListener('change', (e) => {
      slow(() => Filters.set({ period: { season: e.target.value } }));
    });

    // "Latest" button jumps to the newest available observation of the
    // current indicator (Overview tab contextual control).
    $('latestBtn').addEventListener('click', () => {
      const ds = DIE.datasets.get(DIE.state.indicator);
      if (!ds) return;
      const idx = ds.availableEndIndex >= 0 ? ds.availableEndIndex : ds.dates.length - 1;
      slow(() => Filters.set({ dateIdx: idx }));
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
  // Re-run availability clamping + control rendering after an indicator's
  // dataset has loaded. Filters.set() runs before the CSV is available, so
  // its first render cannot know a shorter record (e.g. VCI starts 2000-02).
  Filters.resync = function () { normalise(); renderControls(); };
  Filters.wire = wire;
})();
