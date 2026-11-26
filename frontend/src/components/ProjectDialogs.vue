<script setup>
import { inject, ref, reactive, computed } from 'vue';
import { workspaceKey } from '../workspace';
import { api, request } from '../api';
import { t } from '../i18n';
import { humanSize, extOf } from '../format';
import Modal from './Modal.vue';
import { isAdmin } from '../auth';
import { reportError } from '../feedback';
const w = inject(workspaceKey), { state, guard } = w;
const name = ref(''), target = ref(null), busy = ref(false), message = ref('');
const browse = reactive({ here: '', entries: [], selected: new Set(), dragging: false });
const archived = ref([]), confirm = ref(null), filesInput = ref(null), folderInput = ref(null);
const crumbs = computed(() => [{ name: t('workspace'), path: '' }, ...browse.here.split('/').filter(Boolean).map((part, i, parts) => ({ name: part, path: parts.slice(0, i + 1).join('/') }))]);
function close() { if (!busy.value) state.modal = ''; }
async function open(action, context) {
  await guard(async () => {
    target.value = context || { project: state.project };
    message.value = '';
    if (action === 'new') { name.value = ''; state.modal = 'new'; }
    if (action === 'rename') { name.value = context.project.name; state.modal = 'rename'; }
    if (action === 'adddata') {
      if (context?.project && state.project?.id !== context.project.id) await w.selectProject(context.project.id);
      if (!state.project) return;
      target.value = { project: state.project };
      browse.selected.clear(); browse.entries = []; state.modal = 'browse'; if (isAdmin.value) await loadBrowse('');
    }
    if (action === 'archived') { state.modal = 'archived'; archived.value = await api('/api/archived'); }
    if (action === 'archive') { await api(w.projectUrl('/archive', context.project.id), {}); if (state.project?.id === context.project.id) w.clearProject(); await w.refreshProjects(); }
    if (action === 'delete-project') confirm.value = { title: t('Delete project'), text: `${context.project.name}: ${t('This cannot be undone.')}`, action: async () => { await api(w.projectUrl(`?confirm=${encodeURIComponent(context.project.id)}`, context.project.id), undefined, 'DELETE'); if (state.project?.id === context.project.id) w.clearProject(); await w.refreshProjects(); } };
    if (action === 'delete-file') confirm.value = { title: t('Delete file'), text: `${context.where}/${context.file}: ${t('This cannot be undone.')}${extOf(context.file) === 'shp' ? ' (.shx / .dbf / .prj included)' : ''}`, action: async () => {
      const res = await api(w.projectUrl(`/file?where=${context.where}&path=${encodeURIComponent(context.file)}`, context.project.id), undefined, 'DELETE');
      w.map.value?.remove(`${context.where}/${context.file}`);
      if (state.image?.name === context.file) state.image = null;
      if (state.data?.name === context.file) state.data = null;
      if (!state.image && state.tab === 'image' || !state.data && state.tab === 'data') state.tab = 'map';
      w.addMessage('system', t('Deleted {list} from {w}/.', { list: res.removed.join(', '), w: context.where })); await w.refreshTree();
    } };
  });
}
async function saveName() {
  if (!name.value.trim() || busy.value) return;
  busy.value = true;
  await guard(async () => {
    const rename = state.modal === 'rename';
    const result = await api(rename ? w.projectUrl('/rename', target.value.project.id) : '/api/projects', { name: name.value.trim() });
    if (rename && state.project?.id === target.value.project.id) w.clearProject();
    state.modal = ''; await w.refreshProjects(); await w.selectProject(result.id);
  });
  busy.value = false;
}
async function loadBrowse(path) { const result = await api('/api/browse?path=' + encodeURIComponent(path)); browse.here = result.here || ''; browse.entries = result.entries || []; }
function pick(path) { browse.selected.has(path) ? browse.selected.delete(path) : browse.selected.add(path); }
async function attach() {
  if (!browse.selected.size || busy.value) return;
  busy.value = true;
  await guard(async () => { const result = await api(w.projectUrl('/attach', target.value.project.id), { paths: [...browse.selected] }); state.modal = ''; await w.refreshTree(); w.addMessage('system', t('Added {n} file(s) to {p}.', { n: result.attached?.length || 0, p: target.value.project.name })); for (const notice of result.notices || []) w.addMessage('system', notice); });
  busy.value = false;
}
async function upload(fileList) {
  const files = Array.from(fileList || []); if (!files.length || busy.value) return;
  const project = target.value.project;
  busy.value = true; let ok = 0, failed = 0;
  for (const file of files) {
    message.value = t('uploading {i}/{n} — {name}', { i: ok + failed + 1, n: files.length, name: file.name });
    try { await request(w.projectUrl(`/upload?name=${encodeURIComponent(file.name)}&rel=${encodeURIComponent(file.webkitRelativePath || file.name)}`, project.id), { method: 'POST', body: file }); ok++; }
    catch (error) {
      failed++;
      reportError(new Error(`${file.name}: ${error.message}`));
      if (['storage_quota_exceeded', 'storage_unavailable'].includes(error.code) || error.status === 401) {
        failed = files.length - ok;
        break;
      }
    }
  }
  busy.value = false; state.modal = '';
  await guard(async () => { await w.refreshTree(); w.addMessage(failed ? 'error' : 'system', t('Uploaded {n} file(s) to {p}.', { n: ok, p: project.name }) + (failed ? t(' {n} failed.', { n: failed }) : '')); const check = await api(w.projectUrl('/data_check', project.id)); for (const notice of check.notices || []) w.addMessage('system', notice); });
}
function uploadChange(event) { const files = Array.from(event.target.files); event.target.value = ''; upload(files); }
async function restore(project) { await api(`/api/archived/${encodeURIComponent(project.id)}/restore`, {}); await w.refreshProjects(); archived.value = await api('/api/archived'); }
function deleteArchived(project) { confirm.value = { title: t('Delete archived project'), text: `${project.name}: ${t('This cannot be undone.')}`, action: async () => { await api(`/api/archived/${encodeURIComponent(project.id)}?confirm=${encodeURIComponent(project.id)}`, undefined, 'DELETE'); archived.value = await api('/api/archived'); } }; }
async function confirmAction() { if (busy.value) return; busy.value = true; await guard(confirm.value.action); busy.value = false; confirm.value = null; }
defineExpose({ open });
</script>
<template>
  <Modal id="newModal" close-id="newClose" :open="state.modal === 'new'" :title="t('New project')" small @close="close"><div class="modal-sub">{{ t('A project is a working folder holding your data, outputs, and run history.') }}</div><input id="newName" v-model="name" class="text-input" :placeholder="t('Project name')" @keydown.enter="saveName" /><div class="modal-foot"><span class="ca-spacer"></span><button id="newCancel" class="reset-btn" :disabled="busy" @click="close">{{ t('Cancel') }}</button><button id="newCreate" class="primary-btn" :disabled="busy || !name.trim()" @click="saveName">{{ t('Create') }}</button></div></Modal>
  <Modal id="renameModal" close-id="renameClose" :open="state.modal === 'rename'" :title="t('Rename project')" small @close="close"><input id="renameName" v-model="name" class="text-input" @keydown.enter="saveName" /><div class="modal-foot"><span class="ca-spacer"></span><button id="renameCancel" class="reset-btn" :disabled="busy" @click="close">{{ t('Cancel') }}</button><button id="renameSave" class="primary-btn" :disabled="busy || !name.trim()" @click="saveName">{{ t('Rename') }}</button></div></Modal>
  <Modal id="browseModal" close-id="browseClose" :open="state.modal === 'browse'" :title="t('Add data')" @close="close"><div @dragover.prevent="browse.dragging = true" @dragleave.prevent="browse.dragging = false" @drop.prevent="browse.dragging = false; upload($event.dataTransfer.files)" :class="{ dragging: browse.dragging }">
    <div class="browse-upload"><button id="btnUploadFiles" class="reset-btn" :disabled="busy" @click="filesInput.click()">{{ t('Upload files…') }}</button><button id="btnUploadFolder" class="reset-btn" :disabled="busy" @click="folderInput.click()">{{ t('Upload a folder…') }}</button></div>
    <input id="uploadFiles" ref="filesInput" type="file" multiple hidden @change="uploadChange" /><input id="uploadFolder" ref="folderInput" type="file" webkitdirectory multiple hidden @change="uploadChange" />
    <div v-if="isAdmin" id="browsePath" class="browse-path"><template v-for="(crumb, i) in crumbs" :key="crumb.path"><span v-if="i"> / </span><a href="#" @click.prevent="guard(() => loadBrowse(crumb.path))">{{ crumb.name }}</a></template></div>
    <div id="browseList" class="browse-list"><div v-if="browse.here" class="browse-row browse-up" @click="guard(() => loadBrowse(browse.here.split('/').slice(0, -1).join('/')))">⬑ ..</div><div v-for="entry in browse.entries" :key="entry.rel" class="browse-row" :class="{ 'is-dir': entry.is_dir, picked: browse.selected.has(entry.rel) }" @click="entry.is_dir ? guard(() => loadBrowse(entry.rel)) : pick(entry.rel)"><input type="checkbox" class="browse-cb" :checked="browse.selected.has(entry.rel)" @click.stop="pick(entry.rel)" /><span class="browse-ic">{{ entry.is_dir ? '▱' : '▧' }}</span><span class="browse-name">{{ entry.name }}</span><span class="browse-size">{{ entry.is_dir ? '' : humanSize(entry.size) }}</span></div></div>
    <div class="modal-foot"><span id="browseCount">{{ busy ? message : t('{n} selected', { n: browse.selected.size }) }}</span><span class="ca-spacer"></span><button id="browseCancel" class="reset-btn" :disabled="busy" @click="close">{{ t('Cancel') }}</button><button id="browseAttach" class="primary-btn" :disabled="busy || !browse.selected.size" @click="attach">{{ t('Attach selected') }}</button></div>
  </div></Modal>
  <Modal id="archivedModal" close-id="archivedClose" :open="state.modal === 'archived'" :title="t('Archived projects')" @close="close"><div id="archivedList" class="browse-list"><div v-if="!archived.length">{{ t('Nothing archived yet.') }}</div><div v-for="project in archived" :key="project.id" class="browse-row"><span class="browse-name">{{ project.name }}</span><span class="browse-size">{{ project.data_count }} files · {{ project.run_count }} runs</span><button class="mini-btn" @click="guard(() => restore(project))">{{ t('Restore') }}</button><button class="mini-btn danger" @click="deleteArchived(project)">{{ t('Delete') }}</button></div></div><div class="modal-foot"><button id="archivedDone" class="reset-btn" @click="close">{{ t('Close') }}</button></div></Modal>
  <Modal id="confirmModal" close-id="confirmClose" :open="!!confirm" :title="confirm?.title" small @close="!busy && (confirm = null)"><div id="confirmBody" class="modal-sub">{{ confirm?.text }}</div><div class="modal-foot"><span class="ca-spacer"></span><button id="confirmCancel" class="reset-btn" :disabled="busy" @click="confirm = null">{{ t('Cancel') }}</button><button id="confirmOk" class="primary-btn danger-btn" :disabled="busy" @click="confirmAction">{{ t('Delete') }}</button></div></Modal>
</template>
