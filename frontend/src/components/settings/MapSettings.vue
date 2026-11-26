<script setup>
import { inject, ref, reactive, computed, watch } from 'vue';
import { workspaceKey } from '../../workspace';
import { api } from '../../api';
import { t } from '../../i18n';
import { reportError } from '../../feedback';
const props = defineProps({ active: Boolean });
const { state } = inject(workspaceKey), { perform } = inject('settings');
const config = ref({ providers: [] }), status = ref(''), busy = ref(false);
const form = reactive({ provider: '', key: '', url: '', attribution: '', mbtiles: '', cache: true });
const provider = computed(() => config.value.providers.find(p => p.id === form.provider) || {});
watch(() => props.active, active => { if (active) perform(load); }, { immediate: true });
async function load() { config.value = await api('/api/settings/basemap'); for (const key of ['provider', 'url', 'attribution', 'mbtiles']) form[key] = config.value[key] || ''; form.key = ''; form.cache = config.value.cache !== false; status.value = (config.value.ready ? '' : (config.value.problem || '') + ' ') + t('Cache: {mb} MB.', { mb: ((config.value.cache_bytes || 0) / 1048576).toFixed(1) }); if (config.value.ready) await check(); }
async function check() { try { const result = await api('/api/settings/basemap/check'); status.value += ' ' + t('Source reachable ({ms} ms).', { ms: result.ms || 0 }); } catch (e) { reportError(e); } }
async function save() { busy.value = true; await perform(async () => { const body = { ...form }; if (!body.key.trim()) delete body.key; const result = await api('/api/settings/basemap', body); config.value = result; state.basemap = result; form.key = ''; status.value = result.ready ? t('Applied — {name}.', { name: t(result.display) }) : result.problem; if (result.ready) await check(); }); busy.value = false; }
async function clearCache() { await api('/api/settings/basemap/clear_cache', {}); status.value = t('Tile cache cleared.'); }
</script>
<template>
  <div id="paneMap" class="set-pane" :class="{ hidden: !active }"><div class="ma-grid"><label><span>{{ t('Source') }}</span><select id="bmProvider" v-model="form.provider" class="model-select"><option v-for="p in config.providers" :key="p.id" :value="p.id">{{ t(p.display) }}</option></select></label><label v-if="provider.needs_key || form.provider === 'custom'" id="bmKeyRow"><span>{{ t('Key') }}</span><input id="bmKey" v-model="form.key" class="text-input" type="password" autocomplete="off" :placeholder="config.masked_key || t('paste the provider\'s key')" /></label><label v-if="form.provider === 'custom'" id="bmUrlRow"><span>{{ t('Tile template') }}</span><input id="bmUrl" v-model="form.url" class="text-input" placeholder="https://host/{z}/{x}/{y}.png?key={key}" /></label><label v-if="['custom', 'mbtiles'].includes(form.provider)" id="bmAttrRow"><span>{{ t('Attribution') }}</span><input id="bmAttr" v-model="form.attribution" class="text-input" /></label><label v-if="form.provider === 'mbtiles'" id="bmFileRow"><span>{{ t('MBTiles file') }}</span><input id="bmFile" v-model="form.mbtiles" class="text-input" /></label></div><div id="bmHint" class="prov-hint">{{ t(provider.hint || '') }}</div><a v-if="provider.docs" id="bmDocs" class="prov-docs" :href="provider.docs" target="_blank" rel="noopener">{{ t('get a key ↗') }}</a><label class="mem-toggle"><input id="bmCache" v-model="form.cache" type="checkbox" />{{ t('Keep the tiles I have looked at, for offline use') }}</label><div class="ma-actions"><span id="bmStatus" class="tf-status">{{ status }}</span><span class="ca-spacer"></span><button id="bmClear" class="reset-btn" :disabled="busy" @click="perform(clearCache)">{{ t('Clear tile cache') }}</button><button id="bmSave" class="primary-btn" :disabled="busy" @click="save">{{ t('Apply') }}</button></div></div>
</template>
