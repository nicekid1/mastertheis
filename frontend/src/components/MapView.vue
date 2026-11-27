<script setup>
import { inject, ref, reactive, computed, markRaw, onMounted, onBeforeUnmount, watch, nextTick } from 'vue';
import L from 'leaflet';
import { workspaceKey } from '../workspace';
import { api } from '../api';
import { t } from '../i18n';
import { reportError } from '../feedback';
import { esc } from '../format';
import Modal from './Modal.vue';
const w = inject(workspaceKey);
const { state, guard } = w;
const host = ref(null), layers = reactive([]), context = ref(null), symbology = ref(null), attributes = ref(null), filter = ref('');
let map, basemap, resizeObserver, revision = 0, colorIndex = 0;
const pending = new Map();
const loadingLayers = reactive(new Map());
const loading = computed(() => [...loadingLayers.values()].at(-1) || '');
const colors = ['#2f6f9f', '#B14B26', '#3f7d58', '#8a5fb0', '#b0892f', '#4a7a8c'];
const baseName = computed(() => state.basemap?.tiles && state.basemap?.ready ? state.basemap.display : 'offline reference');
const attrColumns = computed(() => [...new Set((attributes.value?.gj.features || []).slice(0, 200).flatMap(f => Object.keys(f.properties || {})))]);
const attrRows = computed(() => (attributes.value?.gj.features || []).slice(0, 2000).map(f => f.properties || {}).filter(r => Object.values(r).some(v => String(v ?? '').toLowerCase().includes(filter.value.toLowerCase())) || !filter.value));
function fit(layer) { const bounds = layer?.getBounds(); if (bounds?.isValid()) map.fitBounds(bounds, { padding: [24, 24] }); }
function openAttributes(item) {
  if (item?.kind !== 'vector') return;
  attributes.value = item;
  filter.value = '';
  context.value = null;
}
const selected = new Map();
function publishSelection() {
  const groups = new Map();
  for (const { item, id } of selected.values()) {
    if (!groups.has(item.key)) groups.set(item.key, { ...item.source, version: item.version, ids: [] });
    groups.get(item.key).ids.push(id);
  }
  state.mapSelection = [...groups.values()];
  state.selectionCount = selected.size;
}
function restoreFeature(entry) {
  entry.path.setStyle({ color: entry.item.color, fillColor: entry.item.color,
    weight: 1.5, fillOpacity: Number(entry.item.fillOpacity) });
}
function clearSelection(key) {
  for (const [id, entry] of selected) {
    if (!key || entry.item.key === key) { restoreFeature(entry); selected.delete(id); }
  }
  publishSelection();
}
function highlight(path) { path.setStyle({ color: '#b45309', fillColor: '#fbbf24', weight: 4, fillOpacity: .65 }); }
function selectFeature(item, path) {
  if (state.running) return;
  const id = Number(path.feature?.id);
  if (!item.version || !Number.isSafeInteger(id) || id < 0) {
    reportError(t('Reload this layer to enable feature selection.')); return;
  }
  const key = `${item.key}:${id}`;
  if (selected.has(key)) { restoreFeature(selected.get(key)); selected.delete(key); }
  else {
    if (selected.size >= 5000) { reportError(t('Select at most 5000 features per analysis')); return; }
    selected.set(key, { item, path, id }); highlight(path);
  }
  map.closePopup(); publishSelection();
}
function remove(item) { clearSelection(item.key); map.removeLayer(item.layer); layers.splice(layers.indexOf(item), 1); if (symbology.value === item) symbology.value = null; }
function clear() { state.selectingFeatures = false; revision++; pending.clear(); loadingLayers.clear(); [...layers].forEach(remove); colorIndex = 0; attributes.value = null; context.value = null; }
async function addVector(name, where, url, toggle = true) {
  const key = `${where}/${name}`;
  const previous = layers.find(l => l.key === key);
  if (previous) { if (toggle) { remove(previous); return; } remove(previous); }
  const current = revision, token = Symbol(); pending.set(key, token);
  loadingLayers.set(token, name);
  try {
    await nextTick();
    await new Promise(resolve => requestAnimationFrame(resolve));
    const gj = await api(url);
    if (current !== revision || pending.get(key) !== token) return;
    pending.delete(key);
    if (!['Feature', 'FeatureCollection'].includes(gj.type)) return { text: JSON.stringify(gj, null, 2) };
    if (gj._notice) w.addMessage('system', gj._notice);
    const color = colors[colorIndex++ % colors.length];
    const features = gj.type === 'Feature' ? [gj] : gj.features || [];
    const interactive = features.length <= 50_000;
    const renderer = L.canvas({ padding: .35 });
    const layer = L.geoJSON(gj, {
      renderer,
      interactive,
      style: { color, weight: 1.3, fillColor: color, fillOpacity: .22 },
      pointToLayer: (feature, latlng) => L.circleMarker(latlng, { renderer, interactive, radius: 5, color, fillColor: color, fillOpacity: .8, weight: 1.5 }),
    }).addTo(map);
    const sourceUrl = new URL(url, window.location.origin);
    const source = { path: sourceUrl.searchParams.get('path') || name,
      where: sourceUrl.pathname.endsWith('/runfile') ? 'runs' : (sourceUrl.searchParams.get('where') || where),
      run: sourceUrl.searchParams.get('run') || undefined };
    const item = { key, name, kind: 'vector', layer: markRaw(layer), source,
      version: gj.selectionVersion, gj: markRaw(gj.type === 'Feature' ? { features: [gj] } : gj),
      color, fillOpacity: .22, visible: true };
    if (interactive) layer.on('click', event => {
      if (state.selectingFeatures && event.layer?.feature) { selectFeature(item, event.layer); return; }
      const feature = event.layer?.feature;
      const rows = Object.entries(feature?.properties || {})
        .map(([key, value]) => `<div><b>${esc(key)}</b>: ${esc(value && typeof value === 'object' ? JSON.stringify(value) : value)}</div>`).join('');
      if (rows) L.popup({ maxWidth: 260 }).setLatLng(event.latlng)
        .setContent(`<div class="gp-popup">${rows}</div>`).openOn(map);
    });
    layers.push(item);
    fit(layer);
    const columns = [...new Set(features.slice(0, 200).flatMap(feature => Object.keys(feature.properties || {})))];
    return { table: { columns, rows: features.slice(0, 2000).map(feature => columns.map(column => feature.properties?.[column] ?? null)), total: gj.totalFeatures || features.length, truncated: (gj.totalFeatures || features.length) > 2000 } };
  } finally {
    if (pending.get(key) === token) pending.delete(key);
    loadingLayers.delete(token);
  }
}
async function addRaster(name, where, url) {
  const key = `${where}/${name}`, current = revision, token = Symbol(); pending.set(key, token);
  loadingLayers.set(token, name);
  try {
    const payload = await api(url);
    if (current !== revision || pending.get(key) !== token) return;
    pending.delete(key);
    if (!payload.bounds || !payload.image) throw new Error(t('overlay failed'));
    const old = layers.find(l => l.key === key); if (old) remove(old);
    const b = payload.bounds;
    const layer = L.imageOverlay(payload.image, [[b.south, b.west], [b.north, b.east]], { opacity: .85 }).addTo(map);
    layers.push({ key, name, kind: 'raster', layer: markRaw(layer), color: '#3f7d58', opacity: .85, visible: true }); fit(layer);
  } finally {
    if (pending.get(key) === token) pending.delete(key);
    loadingLayers.delete(token);
  }
}
function toggle(item) { item.visible = !item.visible; item.visible ? item.layer.addTo(map) : map.removeLayer(item.layer); }
function style(item) { if (item.kind === 'raster') item.layer.setOpacity(Number(item.opacity)); else item.layer.setStyle({ color: item.color, fillColor: item.color, fillOpacity: Number(item.fillOpacity) }); for (const entry of selected.values()) if (entry.item.key === item.key) highlight(entry.path); }
function fitAll() { if (layers.length) fit(L.featureGroup(layers.map(l => l.layer))); }
function applyBasemap(cfg) {
  if (!map) return;
  if (basemap) { map.removeLayer(basemap); basemap = null; }
  if (cfg?.tiles && cfg.ready) basemap = L.tileLayer(`/api/basemap/tile/{z}/{x}/{y}?r={r}&v=${cfg.version}`, { attribution: esc(cfg.attribution || ''), maxZoom: 22, maxNativeZoom: cfg.max_zoom || 19, errorTileUrl: 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7' }).addTo(map);
}
function menu(event, item) { context.value = { item, x: Math.max(6, Math.min(event.clientX, window.innerWidth - 230)), y: Math.max(6, Math.min(event.clientY, window.innerHeight - 260)) }; }
const close = () => { context.value = null; symbology.value = null; };
watch(() => state.basemap, applyBasemap);
onMounted(() => {
  map = L.map(host.value, { zoomControl: false }).setView([20, 0], 2);
  map.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
  map.createPane('offline').style.zIndex = 150;
  const styles = {
    ne_110m_land: { color: '#cfd4d8', weight: .6, fillColor: '#eeece6', fillOpacity: 1 },
    ne_110m_lakes: { color: '#cfd9e2', weight: .5, fillColor: '#dde7ee', fillOpacity: 1 },
    ne_110m_admin_0_boundary_lines_land: { color: '#b9bfc6', weight: .6, dashArray: '2 3' },
  };
  Object.entries(styles).forEach(([name, style]) => api(`/vendor/naturalearth/${name}.geojson`).then(gj => { if (map) L.geoJSON(gj, { pane: 'offline', style, interactive: false }).addTo(map); }).catch(reportError));
  applyBasemap(state.basemap);
  w.map.value = { addVector, addRaster, clear, clearSelection, resize: () => map?.invalidateSize(), zoomIn: () => map.zoomIn(), zoomOut: () => map.zoomOut(), fitAll, remove: key => { const item = layers.find(l => l.key === key); if (item) remove(item); } };
  resizeObserver = new ResizeObserver(() => map?.invalidateSize()); resizeObserver.observe(host.value);
  document.addEventListener('click', close);
});
onBeforeUnmount(() => { revision++; resizeObserver?.disconnect(); document.removeEventListener('click', close); map?.remove(); map = null; w.map.value = null; });
</script>
<template>
  <div id="mapView" class="viewer-body" :class="{ hidden: state.tab !== 'map' }">
    <div id="mapWrap" class="map-canvas-wrap"><div id="mapLeaflet" ref="host" :class="{ 'feature-selecting': state.selectingFeatures }"></div>
      <div v-if="loading" class="map-load-indicator" role="status" aria-live="polite"><span class="loading-spinner" aria-hidden="true"></span><span>{{ t('Loading layer {name}…', { name: loading }) }}</span></div>
      <div class="feature-selection-toolbar">
        <button class="secondary-btn" :class="{ 'selection-active': state.selectingFeatures }" :aria-pressed="state.selectingFeatures" :disabled="state.running" @click="state.selectingFeatures = !state.selectingFeatures">{{ t(state.selectingFeatures ? 'Finish selecting' : 'Select features') }}</button>
        <template v-if="state.selectionCount"><span>{{ t('{n} features selected', { n: state.selectionCount }) }}</span><button class="reset-btn" :disabled="state.running" @click="clearSelection()">{{ t('Clear selection') }}</button></template>
        <div v-if="state.selectingFeatures" class="selection-help">{{ t('Click features to add or remove them, then write your analysis request.') }}</div>
      </div><div class="map-compass">N</div></div>
    <aside id="legend" class="legend"><div class="legend-title">{{ t('Map layers') }}</div><div id="legendLayers" class="legend-layers">
      <div class="legend-layer"><div class="legend-layer-head"><span class="legend-layer-name">{{ t('Basemap') }}</span><span class="legend-layer-meta">{{ t(baseName) }}</span></div></div>
      <div v-for="item in layers" :key="item.key" class="legend-layer interactive" :class="{ 'hidden-layer': !item.visible }" :title="item.key" @contextmenu.prevent.stop="menu($event, item)"><div class="legend-layer-head"><button class="lyr-vis" :aria-label="t('Toggle visibility')" @click.stop="toggle(item)">◉</button><span class="legend-layer-name">{{ item.name }}</span><span class="legend-layer-meta">{{ t(item.kind) }}</span><button v-if="item.kind === 'vector'" class="mini-btn layer-table-btn" :aria-label="t('Attribute table')" :title="t('Attribute table')" @click.stop="openAttributes(item)">▤</button></div><div class="legend-chips"><span class="chip"><i :style="{ background: item.color }"></i>{{ t(item.kind) }}</span></div></div>
    </div><div class="legend-hint">{{ loading ? t('Loading {name}…', { name: loading }) : t(layers.length ? 'Right-click a layer for symbology, attribute table…' : 'Click a dataset on the left to show it here.') }}</div></aside>
  </div>
  <Teleport to="body">
    <div v-if="context" id="layerMenu" class="ctx-menu" :style="{ left: context.x + 'px', top: context.y + 'px' }" @click.stop>
      <button class="ctx-item" @click="toggle(context.item); context = null">{{ t(context.item.visible ? 'Hide layer' : 'Show layer') }}</button><button class="ctx-item" @click="fit(context.item.layer); context = null">{{ t('Zoom to layer') }}</button><button class="ctx-item" @click="fitAll(); context = null">{{ t('Fit to all layers') }}</button><button class="ctx-item" @click="symbology = context.item; context = null">{{ t('Symbology…') }}</button><button class="ctx-item" :disabled="context.item.kind !== 'vector'" @click="openAttributes(context.item)">{{ t('Attribute table') }}</button><button class="ctx-item danger" @click="remove(context.item); context = null">{{ t('Remove layer') }}</button>
    </div>
    <div v-if="symbology" id="symbPop" class="symb-pop" style="right: 410px; top: 140px" @click.stop><div class="symb-h">{{ symbology.name }} <button @click="symbology = null">✕</button></div><label v-if="symbology.kind === 'vector'" class="symb-row">{{ t('Color') }}<input id="symbColor" v-model="symbology.color" type="color" @input="style(symbology)" /></label><label class="symb-row">{{ t('Opacity') }}<input v-if="symbology.kind === 'raster'" id="symbOpacity" v-model.number="symbology.opacity" type="range" min="0" max="1" step=".01" @input="style(symbology)" /><input v-else id="symbFill" v-model.number="symbology.fillOpacity" type="range" min="0" max="1" step=".01" @input="style(symbology)" /></label></div>
  </Teleport>
  <Modal id="attrModal" close-id="attrClose" :open="!!attributes" :title="attributes ? t('{name} — {n} features', { name: attributes.name, n: attributes.gj.totalFeatures || attributes.gj.features.length }) : t('Attribute table')" @close="attributes = null"><div class="attr-toolbar"><input id="attrFilter" v-model="filter" class="text-input" :placeholder="t('Query — filter rows by any field…')" /><span id="attrCount">{{ t('{n} rows', { n: attrRows.length }) }}</span></div><div v-if="attributes?.gj.features.length > 2000">{{ t('(showing first {n})', { n: 2000 }) }}</div><div class="attr-table-wrap"><table id="attrTable" class="attr-table"><thead><tr><th>#</th><th v-for="column in attrColumns" :key="column">{{ column }}</th></tr></thead><tbody><tr v-for="(row, i) in attrRows" :key="i"><td>{{ i + 1 }}</td><td v-for="column in attrColumns" :key="column">{{ row[column] }}</td></tr></tbody></table></div></Modal>
</template>
