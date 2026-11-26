<script setup>
import { inject, ref, onMounted, onBeforeUnmount } from 'vue';
import { workspaceKey } from '../workspace';
import { t } from '../i18n';
import { extOf } from '../format';
const emit = defineEmits(['action', 'journal']);
const w = inject(workspaceKey);
const { state, collapsed, selection, guard } = w;
const context = ref(null);
function openMenu(event, project, file, where) { context.value = { project, file, where, x: Math.min(event.clientX, window.innerWidth - 220), y: Math.min(event.clientY, window.innerHeight - 310) }; }
function action(name) { const target = context.value; context.value = null; emit('action', name, target); }
const close = () => { context.value = null; };
onMounted(() => document.addEventListener('click', close));
onBeforeUnmount(() => document.removeEventListener('click', close));
</script>
<template>
  <aside class="panel panel-left">
    <div class="panel-head"><div class="panel-title">{{ t('Projects') }}</div><button id="btnNewProject" class="mini-btn" @click="$emit('action', 'new')">＋</button></div>
    <div id="catalog" class="tree">
      <div v-if="!state.projects.length" class="tree-empty">{{ t('No projects yet.') }}</div>
      <div v-for="p in state.projects" :key="p.id" class="tree-section" :data-project="p.id">
        <div class="tree-group task-folder" :class="{ expanded: state.project?.id === p.id && !collapsed.has(p.id), 'active-folder': state.project?.id === p.id }" role="button" tabindex="0" @click="guard(() => w.selectProject(p.id))" @keydown.enter="guard(() => w.selectProject(p.id))" @contextmenu.prevent.stop="openMenu($event, p)">
          <span class="tree-caret"></span><span>▱</span><span class="tree-label">{{ p.name }}</span><span class="tree-meta">{{ p.data_count || 0 }}</span>
        </div>
        <div v-if="state.project?.id === p.id && !collapsed.has(p.id)" class="tree-children">
          <template v-for="where in ['data', 'records', 'outputs']" :key="where">
            <div v-if="where === 'data' || state.tree[where]?.length" class="tree-subhead">{{ t(where) }}</div>
            <div v-if="where === 'data' && !state.tree.data.length" class="tree-hint-item">{{ t('(empty — add data)') }}</div>
            <div v-for="file in state.tree[where] || []" :key="file" class="tree-item" :class="{ active: selection === `${where}/${file}` }" role="button" tabindex="0" @click="guard(() => w.openFile(file, where))" @keydown.enter="guard(() => w.openFile(file, where))" @contextmenu.prevent.stop="openMenu($event, p, file, where)">
              <span>▧</span><span class="tree-label">{{ file }}</span><span class="tree-meta">{{ extOf(file) }}</span>
            </div>
          </template>
        </div>
      </div>
    </div>
    <div class="side-foot"><button id="btnAddData" class="foot-btn" :disabled="!state.project" @click="$emit('action', 'adddata')">{{ t('＋ Add data…') }}</button><div id="footHint" class="foot-line">{{ t(state.project ? 'Describe an analysis and press Run.' : 'Create a project to begin.') }}</div></div>
  </aside>
  <Teleport to="body">
    <div v-if="context" id="ctxMenu" class="ctx-menu" :style="{ left: context.x + 'px', top: context.y + 'px' }" @click.stop>
      <template v-if="context.file"><button class="ctx-item" @click="guard(() => w.openFile(context.file, context.where)); close()">{{ t('Open') }}</button><button v-if="context.where !== 'records'" class="ctx-item danger" :disabled="state.running" @click="action('delete-file')">{{ t('Delete file…') }}</button></template>
      <template v-else>
        <button class="ctx-item" @click="action('adddata')">{{ t('Add data') }}</button>
        <button class="ctx-item" :disabled="state.running && context.project.id === state.project?.id" @click="action('rename')">{{ t('Rename…') }}</button>
        <a class="ctx-item" :href="`/api/projects/${encodeURIComponent(context.project.id)}/export`" download>{{ t('Export as zip') }}</a>
        <button class="ctx-item" :disabled="state.running && context.project.id === state.project?.id" @click="action('archive')">{{ t('Archive…') }}</button>
        <button class="ctx-item" @click="guard(async () => { if (state.project?.id !== context.project.id) await w.selectProject(context.project.id); close(); emit('journal'); })">{{ t('Journal…') }}</button>
        <button class="ctx-item danger" :disabled="state.running && context.project.id === state.project?.id" @click="action('delete-project')">{{ t('Delete project…') }}</button>
      </template>
    </div>
  </Teleport>
</template>
<style>.ctx-menu button.ctx-item { border: 0; background: transparent; width: 100%; text-align: left; }.ctx-menu button.ctx-item:hover { background: var(--accent-soft); }</style>
