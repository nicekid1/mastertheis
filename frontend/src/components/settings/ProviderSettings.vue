<script setup>
import { inject, reactive, watch } from 'vue';
import { workspaceKey } from '../../workspace';
import { api } from '../../api';
import { t } from '../../i18n';
defineProps({ active: Boolean });
const { state } = inject(workspaceKey);
const { settings, perform, refresh } = inject('settings');
const forms = reactive({});
watch(() => settings.providers, providers => { for (const p of providers) forms[p.id] = { key: '', url: p.base_url || '', note: '', busy: false }; }, { immediate: true });
async function save(p, clear = false) {
  const form = forms[p.id], body = clear ? { clear: true } : {};
  if (!clear) { if (form.key.trim()) body.api_key = form.key.trim(); if (p.needs_base_url) body.base_url = form.url.trim(); }
  if (!Object.keys(body).length) { form.note = t('Nothing to save — paste a key first.'); return; }
  form.busy = true;
  await perform(async () => { await refresh(await api(`/api/settings/providers/${encodeURIComponent(p.id)}`, body)); forms[p.id].note = t('Saved.'); });
  forms[p.id].busy = false;
}
async function test(p) { const form = forms[p.id]; form.busy = true; form.note = t('Calling the API…'); await perform(async () => { const result = await api(`/api/settings/providers/${encodeURIComponent(p.id)}/test`, {}); form.note = t('Works — {model} replied "{reply}".', { model: result.model_name, reply: result.reply }); }); form.busy = false; }
</script>
<template>
  <div id="paneKeys" class="set-pane" :class="{ hidden: !active }"><div class="modal-sub">{{ t('API keys') }} · <code id="setPath">{{ settings.settings_path }}</code></div><div id="provList" class="prov-list"><div v-for="p in settings.providers" :key="p.id" class="prov"><div class="prov-head"><span class="prov-name">{{ t(p.display) }}</span><span class="prov-badge" :class="{ ok: p.configured }">{{ t(p.key_optional && !p.masked_key ? 'no key needed' : p.configured ? 'key saved' : 'no key') }}</span><button v-if="p.key_optional" class="prov-docs pv-setup" @click="state.settingsPane = 'local'">{{ t('set up →') }}</button><a v-else-if="p.docs" class="prov-docs" :href="p.docs" target="_blank" rel="noopener">{{ t('get a key ↗') }}</a></div><div class="prov-row"><input v-model="forms[p.id].key" type="password" class="pv-key" autocomplete="off" :placeholder="p.masked_key ? t('{mask}  (stored — type to replace)', { mask: p.masked_key }) : p.key_hint || t('paste your API key')" /><button class="mini-btn primary pv-save" :disabled="forms[p.id].busy" @click="save(p)">{{ t('Save') }}</button><button class="mini-btn pv-test" :disabled="forms[p.id].busy" @click="test(p)">{{ t('Test') }}</button><button v-if="p.masked_key && !p.from_env" class="mini-btn danger pv-clear" :disabled="forms[p.id].busy" @click="save(p, true)">{{ t('Remove') }}</button></div><div v-if="p.needs_base_url" class="prov-row"><input v-model="forms[p.id].url" class="pv-url" placeholder="https://your-endpoint/v1" /></div><div class="prov-hint">{{ t(p.hint || '') }}</div><div class="prov-note">{{ forms[p.id].note }}</div></div></div></div>
</template>
