<script setup>
import { inject, ref, watch } from 'vue';
import { workspaceKey } from '../../workspace';
import { api } from '../../api';
import { t } from '../../i18n';
const props = defineProps({ active: Boolean });
const { state } = inject(workspaceKey), { settings, perform } = inject('settings');
const text = ref(''), enabled = ref(false), status = ref('');
watch(() => props.active, active => { if (active) perform(async () => { const result = await api('/api/memory'); text.value = result.text || ''; enabled.value = !!result.enabled; }); }, { immediate: true });
async function save() { await api('/api/memory', { text: text.value, enabled: enabled.value }, 'PUT'); status.value = t('Saved — this applies from the next run onwards.'); }
async function follow(value) { state.viewerFollow = value; await api('/api/settings/viewer_follow', { enabled: value }); }
</script>
<template>
  <div id="paneMemory" class="set-pane" :class="{ hidden: !active }"><div class="modal-sub">{{ t('Memory') }} · <code id="memPath">{{ settings.memory_path }}</code></div><label class="mem-toggle"><input id="memEnabled" v-model="enabled" type="checkbox" />{{ t('Apply memory to runs') }}</label><label class="mem-toggle"><input id="viewerFollow" type="checkbox" :checked="state.viewerFollow" @change="perform(() => follow($event.target.checked))" />{{ t('Follow the agent between Map, Code and Result while it works') }}</label><textarea id="memText" v-model="text" class="mem-text" spellcheck="false"></textarea><div class="modal-foot"><span id="memStatus" class="tf-status">{{ status }}</span><span class="ca-spacer"></span><button id="memSave" class="primary-btn" @click="perform(save)">{{ t('Save memory') }}</button></div></div>
</template>
