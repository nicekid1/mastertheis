<script setup>
import { inject, ref, computed, watch } from 'vue';
import { api } from '../../api';
import { t } from '../../i18n';
import { reportError } from '../../feedback';
const props = defineProps({ active: Boolean });
const { perform, refresh } = inject('settings');
const info = ref({ presets: {}, models: [], recommended: [] }), probe = ref(null), kind = ref('ollama'), url = ref(''), status = ref(''), advice = ref(''), busy = ref(false), copied = ref('');
const added = computed(() => new Set(info.value.models.map(m => m.model_name)));
const rows = computed(() => probe.value?.models || info.value.models.map(m => ({ ...m, id: m.model_name })));
const preset = computed(() => info.value.presets[kind.value] || {});
function context(m) { return probe.value?.running?.find(r => r.id === m.id)?.context || m.context_set; }
function contextLabel(m) { const value = context(m); return value ? t('context {n}', { n: value.toLocaleString() }) : m.context_max ? t('context up to {n} · server default applies', { n: m.context_max.toLocaleString() }) : t('context unknown'); }
watch(() => props.active, active => { if (active) perform(load); }, { immediate: true });
async function load() { info.value = await api('/api/settings/local'); const saved = info.value.base_url || ''; kind.value = Object.entries(info.value.presets).find(([, p]) => p.base_url && saved.startsWith(p.base_url.replace(/\/v1\/?$/, '')))?.[0] || (saved ? 'other' : 'ollama'); url.value = saved || preset.value.base_url || ''; }
async function connect() {
  if (!url.value.trim()) { status.value = t('Enter the server address first.'); return; }
  busy.value = true; status.value = t('Connecting…'); advice.value = '';
  try {
    probe.value = await api(`/api/settings/local/probe?base_url=${encodeURIComponent(url.value.trim())}`);
    info.value = await api('/api/settings/local');
    status.value = t('Connected to {kind} — {n} model(s).', { kind: probe.value.kind === 'ollama' ? 'Ollama' + (probe.value.version ? ' ' + probe.value.version : '') : t('an OpenAI-compatible server'), n: probe.value.models.length });
    const low = probe.value.running?.find(r => r.context && r.context < (info.value.min_context || 8192));
    if (low) advice.value = t('{m} is loaded with a {ctx}-token context. Raise it in the Ollama app (Settings → Context length) or start the server with OLLAMA_CONTEXT_LENGTH={rec}.', { m: low.id, ctx: low.context.toLocaleString(), rec: info.value.recommended_context || 16384 });
  } catch (e) { probe.value = null; status.value = ''; reportError(e); } finally { busy.value = false; }
}
async function add(m) { await refresh(await api('/api/settings/models', { id: m.id, display: m.id, provider: 'local', model_name: m.id, max_rounds: 35, max_tokens: 2048, timeout: 600, context_chars: m.context_chars || 0 })); info.value = await api('/api/settings/local'); status.value = t('Added {m} — it is in the run selector. Press Test to load it once.', { m: m.id }); }
async function test(m) { busy.value = true; status.value = t('Calling {m}… (the first call loads the model; this can take a minute)', { m: m.id }); try { const result = await api('/api/settings/providers/local/test', { model_name: m.id }); status.value = t('Works — {m} replied "{reply}".', { m: m.id, reply: result.reply }); advice.value = result.context_advice || ''; if (probe.value && result.context_length) probe.value.running = [{ id: m.id, context: result.context_length }]; } catch (e) { status.value = ''; reportError(e); } finally { busy.value = false; } }
async function copy(name) { await navigator.clipboard.writeText(`ollama pull ${name}`); copied.value = name; }
</script>
<template>
  <div id="paneLocal" class="set-pane" :class="{ hidden: !active }"><div class="modal-sub">{{ t('Local models') }} · {{ t('Context length matters most:') }} <span id="localMinCtx">{{ (info.min_context || 8192).toLocaleString() }}</span> tokens</div><div class="disc-bar"><select id="localKind" v-model="kind" class="model-select" @change="url = preset.base_url || ''"><option v-for="(p, id) in info.presets" :key="id" :value="id">{{ t(p.display) }}</option></select><input id="localUrl" v-model="url" class="text-input" placeholder="http://localhost:11434/v1" @keydown.enter="connect" /><button id="localConnect" class="mini-btn primary" :disabled="busy" @click="connect">{{ t('Connect') }}</button><a v-if="preset.docs" id="localDocs" class="prov-docs" :href="preset.docs" target="_blank" rel="noopener">{{ t('install ↗') }}</a></div><div id="localStatus" class="tf-status">{{ status }}</div><div id="localAdvice" class="local-advice" :class="{ hidden: !advice }">{{ advice }}</div><div id="localModels" class="local-models"><div v-if="!rows.length" class="lm-empty">{{ t('Press Connect to see what the server is serving.') }}</div><div v-for="m in rows" :key="m.id" class="lm-row"><span class="lm-name">{{ m.id }}</span><span class="lm-meta">{{ [m.params, m.quant, m.size_gb ? `${m.size_gb} GB` : ''].filter(Boolean).join(' · ') }}</span><span class="lm-ctx" :class="{ bad: context(m) && context(m) < (info.min_context || 8192) }">{{ contextLabel(m) }}</span><template v-if="added.has(m.id) || m.already_added"><span class="model-flag">{{ t('added') }}</span><button class="mini-btn lm-test" :disabled="busy" @click="test(m)">{{ t('Test') }}</button></template><button v-else class="mini-btn primary lm-add" :disabled="busy" @click="perform(() => add(m))">{{ t('Add this model') }}</button></div></div><div class="ma-title">{{ t('Recommended models') }}</div><div id="localReco" class="local-reco"><div v-for="r in info.recommended" :key="r.name" class="reco-row"><code>ollama pull {{ r.name }}</code><span class="reco-needs">{{ t(r.needs) }}</span><span class="reco-note">{{ t(r.note) }}</span><button class="mini-btn reco-copy" @click="perform(() => copy(r.name))">{{ t(copied === r.name ? 'Copied' : 'Copy') }}</button></div></div></div>
</template>
