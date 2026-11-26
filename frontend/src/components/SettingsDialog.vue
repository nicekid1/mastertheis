<script setup>
import { inject, reactive, ref, watch, provide } from 'vue';
import { workspaceKey } from '../workspace';
import { api } from '../api';
import { t } from '../i18n';
import { runSafely } from '../feedback';
import Modal from './Modal.vue';
import ProviderSettings from './settings/ProviderSettings.vue';
import ModelSettings from './settings/ModelSettings.vue';
import LocalSettings from './settings/LocalSettings.vue';
import MapSettings from './settings/MapSettings.vue';
import SkillsSettings from './settings/SkillsSettings.vue';
import MemorySettings from './settings/MemorySettings.vue';
const w = inject(workspaceKey), { state } = w;
const settings = reactive({ providers: [], models: [], settings_path: '', memory_path: '' });
const ready = ref(false);
async function perform(action) { return runSafely(action); }
async function refresh(result) { Object.assign(settings, result || await api('/api/settings')); await w.refreshModels(); }
provide('settings', { settings, perform, refresh });
watch(() => state.modal, modal => { if (modal === 'settings') { ready.value = false; perform(async () => { await refresh(); ready.value = true; }); } });
const panes = [['keys', 'API keys'], ['models', 'Models'], ['local', 'Local models'], ['map', 'Map'], ['skills', 'Skills'], ['memory', 'Memory']];
</script>
<template>
  <Modal id="setModal" close-id="setClose" :open="state.modal === 'settings'" :title="t('Settings')" @close="state.modal = ''"><div class="set-tabs"><button v-for="[key, label] in panes" :key="key" class="set-tab" :class="{ active: state.settingsPane === key }" :data-pane="key" @click="state.settingsPane = key">{{ t(label) }}</button></div><template v-if="ready"><ProviderSettings :active="state.modal === 'settings' && state.settingsPane === 'keys'" /><ModelSettings :active="state.modal === 'settings' && state.settingsPane === 'models'" /><LocalSettings :active="state.modal === 'settings' && state.settingsPane === 'local'" /><MapSettings :active="state.modal === 'settings' && state.settingsPane === 'map'" /><SkillsSettings :active="state.modal === 'settings' && state.settingsPane === 'skills'" /><MemorySettings :active="state.modal === 'settings' && state.settingsPane === 'memory'" /></template></Modal>
</template>
