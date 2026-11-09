/* ===========================================================================
 * map.js — Leaflet cartography
 * ---------------------------------------------------------------------------
 *  - Choropleth of district drought values with discrete classes or a
 *    continuous colour ramp (both driven by metadata thresholds).
 *  - State boundary lines, national outline, optional place labels.
 *  - Hover tooltips, click-to-select (drives the whole dashboard), popups
 *    with full provenance per district.
 *  - A generic choropleth factory reused by Module A (comparison maps) and
 *    Module B (evolution map).
 *  - A shared legend builder used by every map view.
 *  - Default basemap is a plain offline canvas; reference tile layers are
 *    optional (no mandatory external geospatial service).
 * =========================================================================== */
(function () {
  "use strict";

  const DIE = (window.DIE = window.DIE || {});
  const $ = (id) => document.getElementById(id);

  const NO_DATA_COLOR = "#D7DEE7";
  // const BASEMAPS = {
  //   light: {
  //     url: "https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png",
  //     attr: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
  //     maxZoom: 19,
  //   },
  //   streets: {
  //     url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  //     attr: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  //     maxZoom: 19,
  //   },
  // };

  const BASEMAPS = {
    light: {
      url: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
      attr: "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ",
      maxZoom: 19,
    },
    streets: {
      // leave your existing OSM streets entry exactly as it is
      url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      attr: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
    },
  };

  /* ------------------------------------------------------------- helpers -- */
  function valueAt(dataset, districtId, dateIdx) {
    const i = dataset.districtIndex.get(districtId);
    if (i === undefined) return NaN;
    return dataset.values[i][dateIdx];
  }

  function fmtRange(lo, hi, indicator) {
    const dec = indicator.family === "land" ? 0 : 2;
    const f = (v) =>
      v === null || v === undefined ? "" : v.toFixed(dec).replace("-", "−");
    if ((lo === null || lo === undefined) && (hi === null || hi === undefined))
      return "";
    if (lo === null || lo === undefined) return "≤ " + f(hi);
    if (hi === null || hi === undefined) return "≥ " + f(lo);
    return f(lo) + " … " + f(hi);
  }

  function districtCompleteness(dataset, districtId) {
    const i = dataset.districtIndex.get(districtId);
    if (i === undefined) return 0;
    const row = dataset.values[i];
    const start = dataset.availableStartIndex || 0;
    const end =
      dataset.availableEndIndex === undefined
        ? row.length - 1
        : dataset.availableEndIndex;
    if (end < start) return 0;
    let n = 0;
    for (let j = start; j <= end; j++) if (Number.isFinite(row[j])) n++;
    return n / (end - start + 1);
  }

  function classChip(c) {
    if (!c)
      return '<span class="mini-chip" style="background:#9AA7B5">no data</span>';
    return (
      '<span class="mini-chip" style="background:' +
      c.color +
      '">' +
      c.label +
      "</span>"
    );
  }

  /* ------------------------------------------------------ legend builder -- */
  function renderLegend(container, indicator, mode, opts) {
    opts = opts || {};
    container.innerHTML = "";
    if (mode === "continuous") {
      const [lo, hi] = indicator.scale;
      const ramp = DIE.ramp(indicator);
      const stops = [];
      for (let k = 0; k <= 10; k++)
        stops.push(ramp(lo + ((hi - lo) * k) / 10) + " " + k * 10 + "%");
      const head = document.createElement("div");
      head.className = "legend-head";
      head.textContent = "Continuous " + indicator.units;
      const grad = document.createElement("div");
      grad.className = "legend-grad";
      grad.style.background = "linear-gradient(90deg," + stops.join(",") + ")";
      const labels = document.createElement("div");
      labels.className = "legend-grad-labels";
      const dl = (v) =>
        (indicator.family === "land" ? Math.round(v) : v.toFixed(1))
          .toString()
          .replace("-", "−");
      labels.innerHTML =
        "<span>" +
        dl(lo) +
        "</span><span>" +
        dl((lo + hi) / 2) +
        "</span><span>" +
        dl(hi) +
        "</span>";
      container.append(head, grad, labels);
    } else {
      const head = document.createElement("div");
      head.className = "legend-head";
      head.textContent = "Severity classes";
      container.appendChild(head);
      indicator.classes.forEach((c) => {
        const row = document.createElement("div");
        row.className = "legend-row";
        row.innerHTML =
          '<span class="legend-swatch" style="background:' +
          c.color +
          '"></span>' +
          "<span>" +
          c.label +
          "</span>" +
          '<span class="legend-range">' +
          fmtRange(c.min, c.max, indicator) +
          "</span>";
        container.appendChild(row);
      });
    }
    const nd = document.createElement("div");
    nd.className = "legend-row";
    nd.style.marginTop = "4px";
    nd.innerHTML =
      '<span class="legend-swatch" style="background:' +
      NO_DATA_COLOR +
      ';background-image:repeating-linear-gradient(45deg,transparent,transparent 3px,rgba(0,0,0,.08) 3px,rgba(0,0,0,.08) 6px)"></span>' +
      '<span>No data</span><span class="legend-range">missing obs.</span>';
    container.appendChild(nd);
    if (opts.note) {
      const n = document.createElement("p");
      n.className = "rail-note";
      n.innerHTML = opts.note;
      container.appendChild(n);
    }
  }

  /* ---------------------------------------------- choropleth map factory -- */
  function createChoropleth(container, opts) {
    opts = opts || {};
    const map = L.map(container, {
      preferCanvas: true,
      renderer: L.canvas({ padding: 0.35 }),
      zoomControl: true,
      attributionControl: true,
      minZoom: 3,
      maxZoom: 10,
      scrollWheelZoom: !opts.noScroll,
      attributionControl: true,
    }).setView([22.8, 80.5], 4);

    let tileLayer = null;
    let currentBasemap = null;
    function setBasemap(kind) {
      kind = kind || "plain";
      // Re-adding identical tiles on every state change caused flicker and
      // unnecessary network requests; only switch when the setting changed.
      if (kind === currentBasemap) return;
      currentBasemap = kind;
      if (tileLayer) {
        map.removeLayer(tileLayer);
        tileLayer = null;
      }
      if (BASEMAPS[kind]) {
        tileLayer = L.tileLayer(BASEMAPS[kind].url, {
          attribution: BASEMAPS[kind].attr,
          maxZoom: BASEMAPS[kind].maxZoom,
          subdomains: "abcd",
        }).addTo(map);
      }
    }
    setBasemap(opts.basemap || "plain");

    const districtsLayer = L.geoJSON(DIE.boundaries.districts, {
      style: () => ({
        color: "#FFFFFF",
        weight: 0.6,
        fillColor: NO_DATA_COLOR,
        fillOpacity: 0.92,
      }),
      onEachFeature: (feature, layer) => {
        const id = feature.properties.id;
        layer.on("mouseover", () =>
          layer.setStyle({ weight: 1.4, color: "#14263D" }),
        );
        layer.on("mouseout", () =>
          layer.setStyle({ weight: 0.6, color: "#FFFFFF" }),
        );
        if (opts.onDistrictClick) {
          layer.on("click", () => opts.onDistrictClick(id));
        }
        if (opts.tooltip !== false) {
          layer.bindTooltip(
            () =>
              buildTooltipHtml(
                id,
                opts.getContext ? opts.getContext() : context,
              ),
            {
              sticky: true,
              className: "die-tooltip",
              direction: "top",
              opacity: 1,
            },
          );
        }
      },
    }).addTo(map);

    const statesLayer = L.geoJSON(DIE.boundaries.states, {
      style: () => ({
        color: "#8C9BAD",
        weight: 1.1,
        fill: false,
        opacity: 0.9,
      }),
      interactive: false,
    }).addTo(map);

    const outlineLayer = L.geoJSON(DIE.boundaries.outline, {
      style: () => ({
        color: "#14263D",
        weight: 2,
        fill: false,
        opacity: 0.95,
      }),
      interactive: false,
    }).addTo(map);

    const layerById = new Map();
    const layerBySid = new Map();
    districtsLayer.eachLayer((l) => layerById.set(l.feature.properties.id, l));
    statesLayer.eachLayer((l) => layerBySid.set(l.feature.properties.sid, l));

    const labelGroup = L.layerGroup();
    function buildLabels() {
      labelGroup.clearLayers();
      DIE.registry.states.forEach((s) => {
        if (Number.isFinite(s.lon) && Number.isFinite(s.lat)) {
          labelGroup.addLayer(
            L.marker([s.lat, s.lon], {
              icon: L.divIcon({
                className: "map-label",
                html: s.name,
                iconSize: null,
              }),
              interactive: false,
            }),
          );
        }
      });
    }
    function buildDistrictLabels() {
      const g = L.layerGroup();
      DIE.registry.districts.forEach((d) => {
        if (Number.isFinite(d.lon) && Number.isFinite(d.lat)) {
          g.addLayer(
            L.marker([d.lat, d.lon], {
              icon: L.divIcon({
                className: "map-label district",
                html: d.name,
                iconSize: null,
              }),
              interactive: false,
            }),
          );
        }
      });
      return g;
    }
    let districtLabels = null;

    function applyData(
      dataset,
      dateIdx,
      colourMode,
      selectedId,
      valueFn,
      colorFn,
    ) {
      districtsLayer.eachLayer((layer) => {
        const id = layer.feature.properties.id;
        const v = valueFn ? valueFn(id) : valueAt(dataset, id, dateIdx);
        const color = colorFn
          ? colorFn(id)
          : Number.isFinite(v)
            ? colourMode === "continuous"
              ? DIE.ramp(dataset.indicator)(v)
              : (DIE.classify(v, dataset.indicator) || { color: NO_DATA_COLOR })
                  .color
            : NO_DATA_COLOR;
        const isSelected = selectedId && id === selectedId;
        layer.setStyle({
          fillColor: color,
          fillOpacity: Number.isFinite(v) ? 0.92 : 0.75,
          color: isSelected ? "#14263D" : "#FFFFFF",
          weight: isSelected ? 2.4 : 0.6,
        });
        if (isSelected) layer.bringToFront();
      });
    }

    function setLayersVisible(o) {
      const has = (layer, on) =>
        map.hasLayer(layer) === on
          ? null
          : on
            ? layer.addTo(map)
            : map.removeLayer(layer);
      if (o.districts !== undefined) has(districtsLayer, o.districts);
      if (o.states !== undefined) has(statesLayer, o.states);
      if (o.outline !== undefined) has(outlineLayer, o.outline);
    }

    function fitRegion(type, id) {
      let bounds = null;
      if (type === "district" && id && layerById.get(id))
        bounds = layerById.get(id).getBounds();
      else if (type === "state" && id && layerBySid.get(id))
        bounds = layerBySid.get(id).getBounds();
      if (!bounds) bounds = outlineLayer.getBounds();
      map.fitBounds(bounds, {
        padding: [18, 18],
        maxZoom: type === "district" ? 8 : 7,
      });
    }

    let labelsOn = false;
    function setLabels(on) {
      on = !!on;
      if (on === labelsOn) return; // avoid remove/add churn on every refresh
      labelsOn = on;
      if (on && !labelGroup.getLayers().length) buildLabels();
      if (on) labelGroup.addTo(map);
      else map.removeLayer(labelGroup);
      updateZoomLabels();
    }
    function updateZoomLabels() {
      const wantDistrict = map.hasLayer(labelGroup) && map.getZoom() >= 6;
      if (wantDistrict && !districtLabels) {
        districtLabels = buildDistrictLabels();
        districtLabels.addTo(map);
      }
      if (!wantDistrict && districtLabels) {
        map.removeLayer(districtLabels);
        districtLabels = null;
      }
    }
    map.on("zoomend", updateZoomLabels);

    return {
      map,
      applyData,
      setBasemap,
      setLayersVisible,
      fitRegion,
      setLabels,
      layerById,
      layerBySid,
      invalidateSize: () => map.invalidateSize(),
    };
  }

  /* --------------------------------------------------- tooltip / popup --- */
  let context = null; // {dataset, dateIdx} set by app before each refresh
  function setTooltipContext(ctx) {
    context = ctx;
  }

  function buildTooltipHtml(districtId, ctx) {
    ctx = ctx || context;
    const d = DIE.registry.districts.get(districtId);
    if (!d || !ctx || !ctx.dataset)
      return '<span class="tt-name">' + (d ? d.name : "—") + "</span>";
    const v = valueAt(ctx.dataset, districtId, ctx.dateIdx);
    const c = DIE.classify(v, ctx.dataset.indicator);
    return (
      '<div class="tt-name">' +
      d.name +
      "</div>" +
      '<div class="tt-state">' +
      d.state +
      "</div>" +
      '<div class="tt-row"><span class="tt-k">' +
      ctx.dataset.indicator.label +
      "</span>" +
      '<span class="tt-v">' +
      DIE.fmt.val(v, ctx.dataset.indicator) +
      "</span></div>" +
      '<div class="tt-row"><span class="tt-k">Class</span><span>' +
      (c ? c.label : "No data") +
      "</span></div>"
    );
  }

  function buildPopupHtml(layer) {
    const id = layer.feature.properties.id;
    const d = DIE.registry.districts.get(id);
    if (!d || !context || !context.dataset)
      return '<div class="die-popup">No data</div>';
    const ind = context.dataset.indicator;
    const v = valueAt(context.dataset, id, context.dateIdx);
    const c = DIE.classify(v, ind);
    const comp = districtCompleteness(context.dataset, id);
    return (
      '<div class="die-popup">' +
      '<div class="p-name">' +
      d.name +
      "</div>" +
      '<div class="p-state">' +
      d.state +
      " · " +
      ind.name +
      "</div>" +
      "<table>" +
      '<tr><td class="p-k">Indicator</td><td>' +
      ind.label +
      " (" +
      ind.units +
      ")</td></tr>" +
      '<tr><td class="p-k">Observation date</td><td>' +
      (context.dataset.dates[context.dateIdx] || "—") +
      "</td></tr>" +
      '<tr><td class="p-k">Value</td><td>' +
      DIE.fmt.val(v, ind) +
      "</td></tr>" +
      '<tr><td class="p-k">Drought category</td><td>' +
      (c ? c.label : "No data") +
      "</td></tr>" +
      '<tr><td class="p-k">District area</td><td>' +
      DIE.fmt.area(d.area) +
      "</td></tr>" +
      '<tr><td class="p-k">Data availability</td><td>' +
      (comp * 100).toFixed(0) +
      "% of months</td></tr>" +
      "</table>" +
      '<p class="p-note">' +
      (/synthetic|demonstration/i.test(
        String((DIE.meta && DIE.meta.data_mode) || ""),
      )
        ? "Demonstration dataset (synthetic)."
        : "GEE-derived historical research dataset.") +
      " Area: equal-area projection.</p>" +
      "</div>"
    );
  }

  /* ----------------------------------------------------------- main map -- */
  let main = null;

  function init() {
    if (!window.L) throw new Error("Leaflet unavailable");
    main = createChoropleth("map", {
      basemap: DIE.state.basemap,
      onDistrictClick: (id) => {
        const d = DIE.registry.districts.get(id);
        if (!d) return;
        try {
          if (DIE.Telemetry)
            DIE.Telemetry.track("district_focus", {
              district: d.name,
              state: d.state,
              source: "map_click",
            });
        } catch (e) {}
        DIE.Filters.set({ extent: "district", stateId: d.sid, districtId: id });
      },
    });
    main.layerById.forEach((layer) => {
      layer.bindPopup(() => buildPopupHtml(layer), { maxWidth: 340 });
    });
    refresh();
  }

  function refresh() {
    if (!main) return;
    const ds = DIE.datasets.get(DIE.state.indicator);
    setTooltipContext({ dataset: ds, dateIdx: DIE.state.dateIdx });
    if (ds)
      main.applyData(
        ds,
        DIE.state.dateIdx,
        DIE.state.colourMode,
        DIE.state.districtId,
      );
    main.setBasemap(DIE.state.basemap);
    main.setLayersVisible(DIE.state.map);
    main.setLabels(DIE.state.map.labels);

    const legendEl = $("legend");
    if (ds && legendEl) {
      const note =
        ds.indicator.family === "land"
          ? "Indicator-specific thresholds (" +
            ds.indicator.label +
            "); see methodology."
          : "Thresholds: McKee et al. (1993) / Vicente-Serrano et al. (2010) convention.";
      const key = ds.indicator.id + "|" + DIE.state.colourMode + "|" + note;
      if (key !== lastLegendKey) {
        lastLegendKey = key;
        renderLegend(legendEl, ds.indicator, DIE.state.colourMode, { note });
      }
      $("legendIndicator").textContent =
        ds.indicator.label + " · " + ds.indicator.units;
    }
  }
  let lastLegendKey = "";

  function fitRegion() {
    if (main)
      main.fitRegion(
        DIE.Filters.regionType(),
        DIE.state.districtId || DIE.state.stateId,
      );
  }

  /* -------------------------------------------------------- PNG export --- */
  async function exportPNG() {
    // html2canvas is intentionally not loaded at boot (it is ~200 KB and only
    // used for this action). Fetch it on first export.
    if (!window.html2canvas && window.DIE_LIBS && window.DIE_LIBS.ensure) {
      DIE.App.toast("Preparing map export", "Loading the image renderer…");
      await window.DIE_LIBS.ensure("html2canvas");
    }
    if (!window.html2canvas) {
      DIE.App.toast(
        "Map export unavailable",
        "The html2canvas library could not be loaded. Charts still export via their toolbar.",
        "warn",
      );
      return;
    }
    const el = document.getElementById("map");
    try {
      const canvas = await html2canvas(el, {
        useCORS: true,
        logging: false,
        backgroundColor: "#EDF1F5",
        scale: 2,
      });
      const a = document.createElement("a");
      a.download =
        "drought-map-" +
        (DIE.Filters.dateYm() || "date") +
        "-" +
        DIE.state.indicator +
        ".png";
      a.href = canvas.toDataURL("image/png");
      a.click();
      try {
        if (DIE.Telemetry)
          DIE.Telemetry.track("export_data", {
            file_type: "png",
            file_name: a.download,
          });
      } catch (e) {}
      DIE.App.toast("Map exported", "Current map view saved as PNG.");
    } catch (e) {
      DIE.App.toast(
        "Map export failed",
        "Try the Plain basemap (offline tiles cannot always be captured).",
        "error",
      );
    }
  }

  /* -------------------------------------------------------------- public -- */
  DIE.MapView = {
    init,
    refresh,
    fitRegion,
    exportPNG,
    createChoropleth,
    renderLegend,
    setTooltipContext,
    valueAt,
    districtCompleteness,
    classChip,
    get main() {
      return main;
    },
  };
})();
