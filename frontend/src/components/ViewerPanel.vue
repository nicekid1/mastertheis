<script setup>
import { inject, ref, computed, watch } from 'vue';
import { workspaceKey } from '../workspace';
import { t } from '../i18n';
import { prose, extOf } from '../format';
import MapView from './MapView.vue';
const w = inject(workspaceKey), { state, elapsedLabel } = w;
const filter = ref(''), raw = ref(false);
watch(() => state.data, () => { filter.value = ''; raw.value = false; });
const tabs = computed(() => [{ id: 'map', label: 'Map' }, { id: 'code', label: 'Code' }, { id: 'data', label: 'Table', hidden: !state.data }, { id: 'image', label: 'Result', hidden: !state.image }]);
const codeLines = computed(() => state.code ? state.code.replace(/\n$/, '').split('\n') : [
  '# ' + t(state.running ? 'Code will appear here after the isolated request finishes.' : 'No executed code was returned. See the execution report below.'),
]);
// Quoted delimiters, embedded newlines, and doubled quotes are valid CSV.
function csv(text, delimiter) {
  const rows = []; let row = [], cell = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') { if (quoted && text[i + 1] === '"') { cell += '"'; i++; } else quoted = !quoted; }
    else if (!quoted && c === delimiter) { row.push(cell); cell = ''; }
    else if (!quoted && (c === '\n' || c === '\r')) { if (c === '\r' && text[i + 1] === '\n') i++; row.push(cell); rows.push(row); row = []; cell = ''; }
    else cell += c;
  }
  if (row.length || cell) { row.push(cell); rows.push(row); }
  return rows;
}
const table = computed(() => {
  if (!state.data) return null;
  if (state.data.table) return state.data.table;
  const ext = extOf(state.data.name);
  if (ext === 'csv' || ext === 'tsv') { const rows = csv(state.data.text, ext === 'tsv' ? '\t' : ','); return { columns: rows[0] || [], rows: rows.slice(1) }; }
  if (ext === 'json' || ext === 'jsonl') {
    try { const data = ext === 'jsonl' ? state.data.text.trim().split('\n').map(JSON.parse) : JSON.parse(state.data.text); if (Array.isArray(data) && data.length && data.every(r => r && typeof r === 'object' && !Array.isArray(r))) { const columns = [...new Set(data.flatMap(Object.keys))]; return { columns, rows: data.map(r => columns.map(c => typeof r[c] === 'object' ? JSON.stringify(r[c]) : r[c] ?? '')) }; } } catch {}
  }
  return null;
});
const rows = computed(() => (table.value?.rows || []).filter(row => !filter.value || row.some(value => String(value).toLowerCase().includes(filter.value.toLowerCase()))).slice(0, 2000));
</script>
<template>
  <section class="panel panel-center">
    <div class="viewer-tabs"><button v-for="tab in tabs" :id="tab.id === 'data' ? 'dataTab' : tab.id === 'image' ? 'imageTab' : undefined" :key="tab.id" class="tab" :class="{ active: state.tab === tab.id }" :data-tab="tab.id" :hidden="tab.hidden" @click="state.tab = tab.id">{{ t(tab.label) }}</button><span class="tabs-spacer"></span><div class="viewer-meta"><span class="meta-key">{{ t('Project') }}</span><span id="regionVal" class="meta-val">{{ state.project?.name || '—' }}</span></div><div class="viewer-actions"><button id="btnZoomIn" class="ghost-btn" :title="t('Zoom in')" @click="w.map.value?.zoomIn()">＋</button><button id="btnZoomOut" class="ghost-btn" :title="t('Zoom out')" @click="w.map.value?.zoomOut()">−</button><button id="btnFit" class="ghost-btn" :title="t('Fit to data')" @click="w.map.value?.fitAll()">⊡</button></div></div>
    <MapView />
    <div id="codeView" class="viewer-body" :class="{ hidden: state.tab !== 'code' }">
      <div class="code-chrome"><div class="code-file-tabs"><div id="codeFileName" class="code-file-tab active">analysis.py</div></div>
        <span id="codeRunState" class="code-run-state">{{ t(state.running ? 'Running' : state.status === 'Failed' ? 'Error' : state.code ? 'Executed' : 'Ready') }}</span>
      </div>
      <div class="code-area"><pre id="codeGutter" class="code-gutter"><span v-for="(_, i) in codeLines" :key="i">{{ i + 1 }}{{ '\n' }}</span></pre><pre id="codeLines" class="code-lines"><span v-for="(line, i) in codeLines" :key="i" class="code-line">{{ line || ' ' }}{{ '\n' }}</span></pre></div>
      <div class="code-output"><div class="code-output-head">{{ t('Execution output') }}</div><div id="codeOutputBody" class="code-output-body"><span v-if="!state.stdout.length" class="out-muted">{{ t('Output appears here as the agent runs code.') }}</span><pre v-for="(out, i) in state.stdout" :key="i" :class="out.ok ? 'out-ok' : 'out-err'">{{ out.text }}</pre></div></div>
    </div>
    <div id="dataView" class="viewer-body" :class="{ hidden: state.tab !== 'data' }"><div class="data-wrap"><div class="data-chrome"><span id="dataFilename" class="image-filename">{{ state.data?.name }}</span><span v-if="table" id="dataMeta" class="image-meta">{{ rows.length }} / {{ table.total ?? table.rows.length }} {{ t('rows') }}</span><span class="ca-spacer"></span><input id="dataFilter" v-model="filter" class="text-input data-filter" :placeholder="t('Filter rows…')" /><button v-if="state.data?.text" id="dataRaw" class="mini-btn" @click="raw = !raw">{{ t(raw ? 'Table' : 'Raw text') }}</button></div><div id="dataStage" class="data-stage"><table v-if="table && !raw" class="attr-table"><thead><tr><th v-for="(col, i) in table.columns" :key="i">{{ col }}</th></tr></thead><tbody><tr v-for="(row, i) in rows" :key="i"><td v-for="(value, j) in row" :key="j">{{ value }}</td></tr></tbody></table><div v-else-if="extOf(state.data?.name || '') === 'md' && !raw" class="prose" v-html="prose(state.data?.text || '')"></div><pre v-else>{{ state.data?.text }}</pre></div></div></div>
    <div id="imageView" class="viewer-body" :class="{ hidden: state.tab !== 'image' }"><div class="image-wrap"><div class="image-chrome"><span id="imageFilename" class="image-filename">{{ state.image?.name }}</span></div><div class="image-stage"><img v-if="state.image" id="imageEl" :src="state.image.url" :alt="state.image.name" /></div></div></div>
    <div class="center-footer"><span id="stepCount" class="fx">{{ t('Steps · {n}', { n: state.steps }) }}</span><span class="fx-sep"></span><span id="selfCorrCount" class="fx">{{ t('Self-corrections · {n}', { n: state.selfCorr }) }}</span><span class="fx-sep"></span><span id="timerCount" class="fx">{{ t('Elapsed · {t}', { t: elapsedLabel }) }}</span></div>
  </section>
</template>
