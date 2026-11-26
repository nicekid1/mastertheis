<script setup>
import { provide, ref, reactive, onMounted, onBeforeUnmount, nextTick } from 'vue';
import { useWorkspace, workspaceKey } from './workspace';
import { t, language, languages } from './i18n';
import ProjectPanel from './components/ProjectPanel.vue';
import ViewerPanel from './components/ViewerPanel.vue';
import ChatPanel from './components/ChatPanel.vue';
import ProjectDialogs from './components/ProjectDialogs.vue';
import SettingsDialog from './components/SettingsDialog.vue';
import ToolboxDialog from './components/ToolboxDialog.vue';
import HelpDialog from './components/HelpDialog.vue';
import JournalDialog from './components/JournalDialog.vue';
import FeedbackHost from './components/FeedbackHost.vue';
import { reportError } from './feedback';
import { api } from './api';
import { currentUser, isAdmin } from './auth';
import AccountDialog from './components/AccountDialog.vue';
import BrandMark from './components/BrandMark.vue';
import { brandName, brandTagline } from './brand';
const accountOpen = ref(false);
async function logout() { await api('/api/auth/logout', {}); location.reload(); }
const workspace = useWorkspace();
provide(workspaceKey, workspace);
const { state, guard } = workspace;
const menu = ref('');
const theme = ref(document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light');
const projects = ref(null);
const journal = ref(null);
const cols = reactive({ left: 264, right: 390 });
try { Object.assign(cols, JSON.parse(localStorage.getItem('gisclaw.cols') || '{}')); } catch {}
function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = theme.value;
  try { localStorage.setItem('gisclaw.theme', theme.value); } catch {}
}
function nudgeColumn(side, amount) {
  cols[side] = Math.max(side === 'left' ? 170 : 260, Math.min(window.innerWidth * .55, cols[side] + amount));
  try { localStorage.setItem('gisclaw.cols', JSON.stringify(cols)); } catch {}
  nextTick(() => workspace.map.value?.resize());
}
const menus = [
  { id: 'project', label: 'Project', items: [['new', '＋ New project…'], ['adddata', '＋ Add data…'], ['log', 'Log (compacted)…'], ['journal', 'Journal (full record)…'], ['note', 'Add note to journal…'], ['newthread', 'Start a new conversation'], ['archived', 'Archived projects…']] },
  { id: 'tools', label: 'Tools', items: [['toolbox', 'Toolbox…']] },
  { id: 'help', label: 'Help', items: [['guide', 'Usage guide…']] },
  { id: 'settings', label: 'Settings', items: [['set-keys', 'API keys…'], ['set-models', 'Models…'], ['set-local', 'Local models…'], ['set-map', 'Map…'], ['set-skills', 'Skills…'], ['set-memory', 'Memory…']] },
];
function disabled(action) { return ['adddata', 'toolbox', 'journal', 'log', 'note', 'newthread'].includes(action) && !state.project || action === 'newthread' && state.running; }
function act(action) {
  if (disabled(action)) return;
  menu.value = '';
  if (action.startsWith('set-')) { state.settingsPane = action.slice(4); state.modal = 'settings'; }
  else if (['new', 'adddata', 'archived'].includes(action)) projects.value.open(action);
  else if (['journal', 'log', 'note'].includes(action)) guard(() => journal.value.open(action));
  else if (action === 'newthread') guard(workspace.newThread);
  else if (action === 'toolbox') state.modal = 'toolbox';
  else if (action === 'guide') state.modal = 'help';
}
let stopDrag;
function resize(event, side) {
  event.preventDefault(); stopDrag?.();
  const start = event.clientX, width = cols[side];
  const move = e => { const rtl = document.documentElement.dir === 'rtl'; const sign = (side === 'left' ? 1 : -1) * (rtl ? -1 : 1); cols[side] = Math.max(side === 'left' ? 170 : 260, Math.min(window.innerWidth * .55, width + (e.clientX - start) * sign)); workspace.map.value?.resize(); };
  stopDrag = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stopDrag); try { localStorage.setItem('gisclaw.cols', JSON.stringify(cols)); } catch {} };
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', stopDrag, { once: true });
}
const closeMenu = () => { menu.value = ''; };
function onUnhandledRejection(event) { event.preventDefault(); reportError(event.reason); }
function onWindowError(event) { reportError(event.error || event.message); }
onMounted(() => { document.addEventListener('click', closeMenu); window.addEventListener('unhandledrejection', onUnhandledRejection); window.addEventListener('error', onWindowError); guard(workspace.init); });
onBeforeUnmount(() => { stopDrag?.(); document.removeEventListener('click', closeMenu); window.removeEventListener('unhandledrejection', onUnhandledRejection); window.removeEventListener('error', onWindowError); });
</script>
<template>
  <div class="app" :style="{ '--col-left': cols.left + 'px', '--col-right': cols.right + 'px' }">
    <a class="skip-link" href="#workspace">{{ t('Skip to workspace') }}</a>
    <header class="topbar">
      <div class="brand"><BrandMark /><div class="brand-text"><div class="brand-name">{{ brandName(language) }}</div><div class="brand-sub">{{ brandTagline(language) }}</div></div></div>
      <div class="topbar-actions">
        <button class="reset-btn" @click="accountOpen = true">{{ currentUser?.username }} · {{ language === 'fa' ? 'حساب کاربری' : 'Account' }}</button>
        <button class="reset-btn" @click="guard(logout)">{{ language === 'fa' ? 'خروج' : 'Sign out' }}</button>
        <button id="themeToggle" class="theme-toggle" type="button" :title="t(theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme')" :aria-label="t(theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme')" :aria-pressed="theme === 'dark'" @click="toggleTheme">
          <svg v-if="theme === 'dark'" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></svg>
          <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M20.2 15.3A8.5 8.5 0 0 1 8.7 3.8 8.5 8.5 0 1 0 20.2 15.3Z"/></svg>
        </button>
        <div class="status" :class="{ running: state.running, done: state.status === 'Done' }"><span class="status-dot"></span><span id="statusText">{{ t(state.stopping ? 'Stopping…' : state.status) }}</span></div>
      </div>
    </header>
    <nav id="menubar" class="menubar" @click.stop>
      <div v-for="group in menus.filter(g => g.id !== 'settings' || isAdmin)" :key="group.id" class="menu" :class="{ open: menu === group.id }" :data-menu="group.id">
        <button class="menu-btn" :aria-expanded="menu === group.id" @click="menu = menu === group.id ? '' : group.id" @mouseenter="menu && (menu = group.id)">{{ t(group.label) }}</button>
        <div class="menu-drop"><button v-for="[action, label] in group.items" :key="action" class="menu-item" :class="{ disabled: disabled(action) }" :data-act="action" :disabled="disabled(action)" @click="act(action)">{{ t(label) }}</button></div>
      </div>
      <div class="menu menu-lang" :class="{ open: menu === 'lang' }" data-menu="lang"><button class="menu-btn lang-btn" aria-label="Language" @click="menu = menu === 'lang' ? '' : 'lang'"><span id="langCode">{{ languages.find(l => l[0] === language)?.[2] }}</span></button><div class="menu-drop menu-drop-right"><button v-for="[code, name] in languages" :key="code" class="menu-item" :data-lang="code" @click="guard(() => workspace.changeLanguage(code)); menu = ''">{{ name }}</button></div></div>
    </nav>
    <main id="workspace" class="workspace">
      <ProjectPanel @action="(action, target) => projects.open(action, target)" @journal="guard(() => journal.open('journal'))" />
      <div id="splitLeft" class="splitter" role="separator" aria-orientation="vertical" tabindex="0" :aria-valuenow="cols.left" :aria-label="t('Resize project panel')" :title="t('Drag to resize · double-click to reset')" @pointerdown="resize($event, 'left')" @dblclick="nudgeColumn('left', 264 - cols.left)" @keydown.left.prevent="nudgeColumn('left', language === 'fa' ? 20 : -20)" @keydown.right.prevent="nudgeColumn('left', language === 'fa' ? -20 : 20)"></div>
      <ViewerPanel />
      <div id="splitRight" class="splitter" role="separator" aria-orientation="vertical" tabindex="0" :aria-valuenow="cols.right" :aria-label="t('Resize chat panel')" :title="t('Drag to resize · double-click to reset')" @pointerdown="resize($event, 'right')" @dblclick="nudgeColumn('right', 390 - cols.right)" @keydown.left.prevent="nudgeColumn('right', language === 'fa' ? -20 : 20)" @keydown.right.prevent="nudgeColumn('right', language === 'fa' ? 20 : -20)"></div>
      <ChatPanel />
    </main>
  </div>
  <ProjectDialogs ref="projects" />
  <SettingsDialog v-if="isAdmin" />
  <AccountDialog :open="accountOpen" @close="accountOpen = false" />
  <ToolboxDialog />
  <HelpDialog />
  <JournalDialog ref="journal" />
  <FeedbackHost />
</template>
<style>
.menu-drop button.menu-item { display: block; width: 100%; border: 0; background: transparent; text-align: start; }
.menu-drop button.menu-item:hover { background: var(--accent-soft); }
.topbar-actions { display:flex; align-items:center; gap:10px; }
.theme-toggle { width:32px; height:32px; display:inline-flex; align-items:center; justify-content:center; border:1px solid var(--line); border-radius:50%; background:var(--bg); color:var(--ink-soft); cursor:pointer; transition:background .18s, color .18s, border-color .18s, transform .18s; }
.theme-toggle:hover { color:var(--accent); border-color:var(--accent); background:var(--accent-soft); transform:translateY(-1px); }
.theme-toggle svg { width:16px; height:16px; fill:none; stroke:currentColor; stroke-width:1.7; stroke-linecap:round; stroke-linejoin:round; }
</style>
