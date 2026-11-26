<script setup>
import { inject, ref, reactive, watch } from 'vue';
import { workspaceKey } from '../workspace';
import { api } from '../api';
import { t, language } from '../i18n';
import { GEO_EXT, extOf } from '../format';
import Modal from './Modal.vue';
import { reportError } from '../feedback';
const w = inject(workspaceKey), { state, guard } = w;
const catalog = ref([]), operation = ref(null), status = ref(''), busy = ref(false);
const form = reactive({ inputs: {}, params: {}, output: '' });
function title(op) { return language.value === 'fa' ? op.title_fa || op.title || op.op : op.title || op.op; }
function description(op) { return language.value === 'fa' ? op.desc_fa || op.desc : op.desc; }
function label(arg) { return language.value === 'fa' ? arg.label_fa || t(arg.name) : arg.label || arg.name; }
function choices(kind) { return [...state.tree.data, ...state.tree.outputs].filter(f => (kind === 'raster' ? ['tif', 'tiff'] : GEO_EXT).includes(extOf(f))); }
watch(() => state.modal, value => { if (value === 'toolbox') guard(async () => { if (!catalog.value.length) catalog.value = await api('/api/tools'); operation.value = null; }); });
function select(op) { operation.value = op; status.value = ''; form.inputs = Object.fromEntries(op.inputs.map(input => [input.role, choices(input.kind)[0] || ''])); form.params = Object.fromEntries(op.args.map(arg => [arg.name, arg.type === 'json' ? JSON.stringify(arg.default ?? {}, null, 2) : arg.default ?? (arg.type === 'bool' ? false : '')])); form.output = `${op.op}_out`; }
function payload() {
  if (!operation.value) throw new Error(t('Select an operation on the left.'));
  for (const input of operation.value.inputs) if (!form.inputs[input.role]) throw new Error(t('Choose an input layer for {name}.', { name: t(input.role) }));
  const params = {};
  for (const arg of operation.value.args) {
    const value = form.params[arg.name];
    if (arg.required && (value == null || String(value).trim() === '')) throw new Error(t('Enter a value for {name}.', { name: label(arg) }));
    if (arg.type === 'json') {
      try { params[arg.name] = JSON.parse(value); } catch { throw new Error(t('Invalid JSON for {name}.', { name: label(arg) })); }
    } else if (arg.type === 'bool') params[arg.name] = !!value;
    else if (String(value).trim()) params[arg.name] = arg.type === 'number' ? Number(value) : arg.type === 'crs' && /^\d+$/.test(value) ? Number(value) : value;
  }
  for (const arg of operation.value.args) if (arg.type === 'number' && arg.name in params && !Number.isFinite(params[arg.name])) throw new Error(t('Enter a number for {name}.', { name: label(arg) }));
  return { op: operation.value.op, inputs: form.inputs, params, output: form.output.trim() || `${operation.value.op}_out` };
}
async function run() {
  busy.value = true; status.value = t('Running…');
  try {
    const result = await api(w.projectUrl('/geoprocess'), payload());
    await w.refreshTree();
    for (const output of result.outputs || []) if (!output.filename.endsWith('.method.json')) await w.openFile(output.filename, 'outputs', undefined, false);
    w.addMessage('system', `${operation.value.op} → ${(result.outputs || []).map(o => o.filename).join(', ')}`); state.modal = '';
  } catch (e) { status.value = ''; reportError(e); } finally { busy.value = false; }
}
function insert() { const p = payload(); state.prompt += (state.prompt ? '\n' : '') + `Use geoprocess operation ${p.op} with input files ${JSON.stringify(p.inputs)} and parameters ${JSON.stringify(p.params)}. Save the result as ${p.output}.`; state.modal = ''; }

</script>
<template>
  <Modal id="toolModal" close-id="toolClose" :open="state.modal === 'toolbox'" :title="t('Toolbox')" @close="!busy && (state.modal = '')"><div class="modal-sub">{{ t('Run a GIS operation directly (deterministic, no AI cost) — or insert it as a request for the agent.') }}</div><div class="tool-body"><div id="toolList" class="tool-list"><template v-for="group in catalog" :key="group.category"><div class="tool-cat">{{ group.title || group.category }}</div><div v-for="op in group.ops" :key="op.op" class="tool-op" :class="{ active: operation?.op === op.op }" :title="description(op)" @click="!busy && select(op)"><span class="tool-op-name">{{ title(op) }}</span></div></template></div><div id="toolForm" class="tool-form"><div v-if="!operation" class="tool-empty">{{ t('Select an operation on the left.') }}</div><template v-else><div class="tf-title">{{ title(operation) }}</div><div class="tf-desc">{{ description(operation) }}</div><div v-for="input in operation.inputs" :key="input.role" class="tf-row"><label>{{ t(input.role) }} <span class="tf-kind">{{ input.kind }}</span></label><select v-model="form.inputs[input.role]" class="tf-input" :data-role="input.role"><option v-if="!choices(input.kind).length" value="">{{ t('(no {kind} layers — add data)', { kind: input.kind }) }}</option><option v-for="file in choices(input.kind)" :key="file">{{ file }}</option></select></div><div v-for="arg in operation.args" :key="arg.name" class="tf-row"><label>{{ label(arg) }}{{ arg.required ? ' *' : '' }}</label><textarea v-if="arg.type === 'json'" v-model="form.params[arg.name]" class="tf-arg urban-json" rows="4" dir="ltr" spellcheck="false" :aria-label="label(arg)" /><input v-else-if="arg.type === 'bool'" v-model="form.params[arg.name]" class="tf-arg" :data-name="arg.name" type="checkbox" /><select v-else-if="arg.type === 'select'" v-model="form.params[arg.name]" class="tf-arg" :data-name="arg.name"><option v-for="choice in arg.choices" :key="choice">{{ choice }}</option></select><input v-else type="text" v-model="form.params[arg.name]" class="tf-arg" :data-name="arg.name" :placeholder="arg.type" :required="arg.required" /></div><div class="tf-row"><label>{{ t('output name') }}</label><input type="text" v-model="form.output" class="tf-output" /></div><div class="tf-actions"><button id="tfInsert" class="reset-btn" @click="guard(insert)" :disabled="busy">{{ t('Insert into chat') }}</button><span class="ca-spacer"></span><button id="tfRun" class="primary-btn" :disabled="busy || state.running" @click="run">{{ t('Run') }}</button></div><div id="tfStatus" class="tf-status">{{ status }}</div></template></div></div></Modal>
</template>
