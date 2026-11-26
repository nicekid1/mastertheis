<script setup>
import { inject, ref } from 'vue';
import { workspaceKey } from '../workspace';
import { api } from '../api';
import { t, language } from '../i18n';
import { aboutBrand, brandName } from '../brand';
import { prose } from '../format';
import Modal from './Modal.vue';
const w = inject(workspaceKey), { state, guard } = w;
const title = ref(''), path = ref(''), content = ref(''), note = ref(''), compose = ref(false), mode = ref('journal');
async function open(kind) {
  mode.value = kind; note.value = ''; compose.value = kind === 'note';
  if (kind === 'about') { title.value = `${language.value === 'fa' ? 'دربارهٔ' : 'About'} ${brandName(language.value)}`; path.value = 'AGPL-3.0-or-later'; content.value = aboutBrand(language.value, state.version); }
  else { const result = await api(w.projectUrl(kind === 'log' ? '/log' : '/journal')); title.value = t(kind === 'log' ? '{p} — running log' : '{p} — journal', { p: state.project.name }); path.value = result.path || ''; content.value = result.markdown || t('Nothing recorded yet — the journal is written when a run finishes.'); }
  state.modal = 'journal';
}
async function save() { if (!note.value.trim()) return; const result = await api(w.projectUrl('/journal/note'), { text: note.value.trim() }); content.value = result.markdown; note.value = ''; compose.value = false; }
defineExpose({ open });
</script>
<template>
  <Modal id="journalModal" close-id="journalClose" :open="state.modal === 'journal'" :title="title" @close="state.modal = ''">
    <div class="modal-sub"><code id="journalPath">{{ path }}</code></div>
    <div id="journalBody" class="journal-body">
      <div class="prose" v-html="prose(content)"></div>
      <p v-if="mode === 'about'"><a href="https://github.com/geumjin99/GISclaw" target="_blank" rel="noopener noreferrer">{{ language === 'fa' ? 'کد منبع پایه و اطلاعات مجوز' : 'Upstream source and licensing' }}</a></p>
      <div v-if="compose" class="note-compose"><textarea v-model="note" class="mem-text" :placeholder="t('A decision, a client requirement, why an approach was dropped…')"></textarea><button class="mini-btn primary" @click="guard(save)">{{ t('Save note') }}</button></div>
    </div>
    <div v-if="mode !== 'about' && state.project" class="modal-foot"><span class="ca-spacer"></span><button id="journalNote" class="reset-btn" @click="compose = true">{{ t('Add a note') }}</button></div>
  </Modal>
</template>
