import { reactive, ref, shallowRef, computed, onBeforeUnmount } from 'vue';
import { api, request, readEvents } from './api';
import { t, language, setLanguage, detectLanguage } from './i18n';
import { extOf, GEO_EXT, IMG_EXT, cleanFinish } from './format';
import { runSafely, showMessage, toast } from './feedback';
import { currentUser, isAdmin } from './auth';
import { runDisabledReason } from './runEligibility';

export const workspaceKey = Symbol('workspace');

export function useWorkspace() {
  const state = reactive({
    projects: [], project: null, tree: { data: [], outputs: [], documents: [], records: [], runs: [] }, models: [], model: '',
    mapSelection: [], selectionCount: 0, selectingFeatures: false,
    messages: [], prompt: '', status: 'Idle', running: false, stopping: false, serverRun: null,
    chatMode: false,
    steps: 0, selfCorr: 0, elapsed: 0, activeRun: null, viewerFollow: true,
    tab: 'map', code: '', stdout: [], image: null, data: null, version: '',
    modal: '', settingsPane: 'keys', basemap: null,
  });
  const map = shallowRef(null);
  const collapsed = reactive(new Set());
  const selection = ref('');
  const elapsedLabel = computed(() => `${String(Math.floor(state.elapsed / 60)).padStart(2, '0')}:${String(state.elapsed % 60).padStart(2, '0')}`);
  const elsewhere = computed(() => state.activeRun && !state.activeRun.done && state.activeRun.project_id !== state.project?.id);
  const runBlockedReason = computed(() => runDisabledReason(state, currentUser.value));
  const canRun = computed(() => !runBlockedReason.value);
  let messageId = 0, generation = 0, timer, bannerTimer, streamController, trace, gotSummary = false, finishObservation = '';
  let disposed = false;

  function addMessage(kind, text, extra = {}) {
    const { silent, ...entry } = extra;
    state.messages.push({ id: ++messageId, kind, text: text || '', ...entry });
    if (!silent && !extra.history && kind === 'system') showMessage(text, { title: t('Message') });
    if (!extra.history && kind === 'error') toast(text, 'error');
    return state.messages.at(-1);
  }
  async function guard(action) {
    return runSafely(action);
  }
  const projectUrl = (suffix = '', id = state.project?.id) => `/api/projects/${encodeURIComponent(id)}${suffix}`;
  async function refreshModels() {
    state.models = await api('/api/models');
    if (!state.models.some(m => m.id === state.model)) state.model = state.models[0]?.id || '';
  }
  async function refreshProjects() { state.projects = await api('/api/projects'); }
  async function refreshTree() {
    const id = state.project?.id;
    if (!id) return;
    const tree = await api(projectUrl('/tree', id));
    if (state.project?.id === id) state.tree = tree;
    await refreshProjects();
  }
  function detach() {
    generation++;
    streamController?.abort(); streamController = null;
    clearInterval(timer); state.running = false; state.stopping = false; state.serverRun = null; trace = null;
  }
  function resetViewer() { state.tab = 'map'; state.code = ''; state.stdout = []; state.image = null; state.data = null; state.steps = 0; state.selfCorr = 0; state.elapsed = 0; state.status = 'Idle'; }
  async function selectProject(id) {
    const project = state.projects.find(p => p.id === id);
    if (!project) return;
    if (state.project?.id === id) { collapsed.has(id) ? collapsed.delete(id) : collapsed.add(id); return; }
    detach();
    const current = generation;
    state.project = project; state.messages = []; selection.value = ''; collapsed.delete(id);
    state.tree = { data: [], outputs: [], documents: [], records: [], runs: [] };
    resetViewer(); map.value?.clear();
    const tree = await api(projectUrl('/tree', id));
    if (generation !== current) return;
    state.tree = tree;
    await loadHistory();
    if (generation !== current) return;
    guard(attachActiveRun);
    guard(refreshBanner);
  }
  function clearProject() { detach(); state.project = null; state.tree = { data: [], outputs: [], documents: [], records: [], runs: [] }; state.messages = []; resetViewer(); map.value?.clear(); }
  async function loadHistory() {
    const id = state.project?.id;
    if (!id) return;
    const result = await api(projectUrl('/chat', id));
    if (id !== state.project?.id) return;
    state.messages = [];
    const entries = result.entries || [];
    if (!entries.length) { addMessage('system', t('Project {p} is open. Describe an analysis and press Run.', { p: state.project.name }), { silent: true }); return; }
    addMessage('divider', t('earlier · {n} runs', { n: entries.filter(e => e.role === 'agent').length }));
    entries.forEach(e => {
      if (e.role === 'user' || e.role === 'note') addMessage(e.role === 'user' ? 'user' : 'system', e.text, { history: true });
      else addMessage(e.success ? 'finish' : 'error', e.final_summary || e.error || '', { history: true, markdown: true, entry: e, outputs: e.outputs || [] });
    });
    addMessage('divider', t('now'));
  }
  async function refreshBanner() {
    clearTimeout(bannerTimer);
    const result = await api('/api/run/active');
    if (disposed) return;
    state.activeRun = result.active;
    if (result.active && !result.active.done) bannerTimer = setTimeout(() => guard(refreshBanner), 3000);
  }
  async function openFile(name, where = 'outputs', explicitUrl, toggle = true) {
    if (!state.project) return;
    const id = state.project.id;
    const url = explicitUrl || projectUrl(`/file?where=${where}&path=${encodeURIComponent(name)}`);
    selection.value = `${where}/${name}`;
    const ext = extOf(name);
    if (ext === 'dbf') {
      const table = await api(projectUrl(`/table?where=${where}&path=${encodeURIComponent(name)}`, id));
      if (id !== state.project?.id) return;
      state.data = { name, table }; state.tab = 'data';
    } else if (IMG_EXT.includes(ext)) { state.image = { name, url }; state.tab = 'image'; }
    else if (['tif', 'tiff'].includes(ext)) {
      await map.value?.addRaster(name, where, projectUrl(`/overlay?where=${where}&path=${encodeURIComponent(name)}`));
      if (id === state.project?.id) state.tab = 'map';
    } else if (GEO_EXT.includes(ext) && where !== 'records') {
      const result = await map.value?.addVector(name, where, url, toggle);
      if (id !== state.project?.id) return;
      if (result?.text) { state.data = { name, text: result.text }; state.tab = 'data'; }
      else { if (result?.table) state.data = { name, table: result.table }; state.tab = 'map'; }
    } else {
      const response = await request(url);
      const contentType = response.headers.get('content-type') || '';
      const text = contentType.includes('application/json') ? (await response.json()).content : await response.text();
      if (id !== state.project?.id) return;
      state.data = { name, text }; state.tab = 'data';
    }
  }
  function startRun(instruction, started = Date.now()) {
    detach();
    const current = generation;
    resetViewer(); gotSummary = false; finishObservation = '';
    for (const m of state.messages) if (m.kind === 'trace') m.open = false;
    if (instruction) addMessage('user', instruction);
    state.running = true; state.status = 'Running';
    timer = setInterval(() => { state.elapsed = Math.floor((Date.now() - started) / 1000); }, 250);
    streamController = new AbortController();
    return current;
  }
  function traceItem(kind, text) {
    if (!trace) trace = addMessage('trace', '', { rows: [], open: true, rounds: 0 });
    trace.rows.push({ kind, text });
    if (kind === 'action') trace.rounds++;
  }
  function closeTrace() { if (trace) trace.open = false; trace = null; }
  function finish(current, success, error, done) {
    if (current !== generation || !state.running) return;
    clearInterval(timer); state.running = false; state.stopping = false; state.serverRun = null;
    state.status = done?.stopped ? 'Stopped' : !success ? 'Failed' : done?.answered && state.chatMode ? 'Idle' : 'Done';
    closeTrace();
    if (done && !done.answered) {
      if (!gotSummary && (finishObservation || done.output_files?.length)) addMessage('answer', cleanFinish(finishObservation), { markdown: true, outputs: done.output_files || [] });
      state.selfCorr = done.self_corrections || 0;
      addMessage('finish', t('Finished in {t}s · {n} rounds · {k} output(s)', { t: done.elapsed_s, n: done.rounds, k: (done.output_files || []).length }));
    }
    if (error) addMessage('error', error);
    guard(refreshTree); guard(refreshBanner);
  }
  function handleEvent(event, msg, current) {
    if (current !== generation) return;
    if (event === 'run') state.serverRun = msg.run_id;
    if (event === 'status') traceItem('status', msg.code ? t(msg.code, msg.params || {}) : msg.content);
    if (event === 'answer') addMessage('answer', msg.content, { markdown: true });
    if (event === 'summary') { gotSummary = true; closeTrace(); addMessage('answer', msg.code ? t(msg.code, msg.params || {}) + (msg.code2 ? t(msg.code2, msg.params || {}) : '') : msg.content, { markdown: true, outputs: msg.outputs || [] }); }
    if (event === 'log') addMessage('log', msg.content, { markdown: true });
    if (event === 'error') finish(current, false, msg.content);
    if (event === 'result') {
      if (!state.tree.outputs.includes(msg.filename)) state.tree.outputs.push(msg.filename);
      const ext = extOf(msg.filename);
      if (['tif', 'tiff'].includes(ext)) guard(() => map.value?.addRaster(msg.filename, 'outputs', projectUrl(`/overlay?run=${encodeURIComponent(msg.run_id)}&path=${encodeURIComponent(msg.filename)}`)));
      else if (GEO_EXT.includes(ext)) guard(() => map.value?.addVector(msg.filename, 'outputs', msg.url, false));
      else if (IMG_EXT.includes(ext) && state.viewerFollow) { state.image = { name: msg.filename, url: msg.url }; state.tab = 'image'; }
    }
    if (event === 'step') {
      if (/^finish\b/.test(msg.action || '')) finishObservation = msg.observation || '';
      if (msg.thought) traceItem('thought', msg.thought);
      if (msg.action) { state.steps++; traceItem('action', msg.action); }
      if (msg.code) { state.code += msg.code.replace(/\n?$/, '\n'); if (state.viewerFollow) state.tab = 'code'; }
      if (msg.observation) { traceItem(msg.success === false ? 'error' : 'observe', msg.observation.slice(0, 600)); if (msg.code) state.stdout.push({ text: msg.observation, ok: msg.success !== false }); }
    }
    if (event === 'done') finish(current, msg.success, null, msg);
  }
  async function stream(url, options, current) {
    const controller = streamController;
    try {
      const response = await request(url, { ...options, signal: controller.signal });
      if ((response.headers.get('content-type') || '').includes('application/json')) { const body = await response.json(); throw new Error(body.error || 'Could not start the run'); }
      await readEvents(response, (event, msg) => handleEvent(event, msg, current), controller.signal);
      if (current === generation && state.running) finish(current, false, t('The connection to the server was lost.'));
    } catch (error) { if (error.name !== 'AbortError' && current === generation) finish(current, false, error.message); }
  }
  async function runAnalysis() {
    if (!canRun.value) return;
    const instruction = state.prompt.trim();
    if (!instruction) { addMessage('error', t('Please describe the analysis first.')); return; }
    if (state.chatMode && currentUser.value?.chat_enabled) {
      if (!state.model) { addMessage('error', t('No model configured')); return; }
      const history = state.messages.filter(m => ['user', 'answer'].includes(m.kind) && m.chat)
        .slice(-6).map(m => ({ role: m.kind === 'user' ? 'user' : 'assistant', text: m.text.slice(0, 500) }));
      const current = startRun(null); state.prompt = '';
      addMessage('user', instruction, { chat: true });
      try {
        const response = await request('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ instruction, model: state.model, language: language.value, history }),
          signal: streamController.signal });
        const result = await response.json();
        if (current === generation) {
          addMessage('answer', result.answer, { markdown: true, chat: true });
          Object.assign(currentUser.value, result.usage);
          finish(current, true, null, { answered: true });
        }
      } catch (error) {
        if (error.name !== 'AbortError') finish(current, false, error.message);
      }
      return;
    }
    if (!state.tree.data.length && !state.selectionCount) { addMessage('error', t('This project has no data yet. Add data first.')); return; }
    if (!state.model) { addMessage('error', t('No model configured')); return; }
    const current = startRun(instruction); state.prompt = '';
    if (currentUser.value?.isolated_analysis_enabled) {
      if (state.viewerFollow) state.tab = 'code';
      state.stdout = [{ text: t('Waiting for the isolated analysis. Tool reports arrive when the request finishes.'), ok: true }];
      const report = (result, failed = false) => {
        const steps = Array.isArray(result?.steps) ? result.steps : [];
        state.code = !failed && typeof result?.code === 'string' ? result.code : steps.map(s => typeof s.code === 'string' ? s.code : '').filter(Boolean).join('\n');
        state.steps = steps.length;
        state.stdout = steps.map(s => ({ text: `${s.action || ''}\n${s.observation || ''}`.trim(), ok: s.success !== false }));
        if (!failed && !steps.length) state.stdout.push({ text: t('The response completed without a tool execution report.'), ok: true });
      };
      try {
        const response = await request(projectUrl('/analysis'), { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ instruction, model: state.model, selection: state.mapSelection }), signal: streamController.signal });
        const result = await response.json();
        if (current === generation) {
          report(result);
          addMessage('answer', result.answer || t('Isolated analysis completed.'), { markdown: true, outputs: result.outputs });
          Object.assign(currentUser.value, result.usage);
          finish(current, result.success, result.success ? null : t('The analysis did not produce a verified result.'), { answered: true });
        }
      } catch (error) {
        if (error.name !== 'AbortError' && current === generation) {
          report(error.details, true);
          state.stdout.push({ text: error.message, ok: false });
          finish(current, false, error.message);
        }
      }
      return;
    }
    await stream('/api/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_id: state.project.id, model: state.model, instruction, language: language.value, selection: state.mapSelection }) }, current);
  }
  async function attachActiveRun() {
    const id = state.project?.id;
    if (!id || state.running) return;
    const info = await api(`/api/run/active?project=${encodeURIComponent(id)}`);
    if (id !== state.project?.id || state.running || !info.active || info.active.done) return;
    const run = info.active, current = startRun(null, run.started * 1000);
    state.serverRun = run.run_id; state.stopping = !!run.stopping;
    addMessage('system', t('Rejoined the run in progress ({id}).', { id: run.run_id }));
    await stream(`/api/run/${encodeURIComponent(run.run_id)}/stream`, {}, current);
  }
  async function stopRun() {
    if (!state.running) return;
    if ((state.chatMode && currentUser.value?.chat_enabled) || currentUser.value?.isolated_analysis_enabled) {
      detach(); state.status = 'Stopped';
      addMessage('system', t('Chat detached; the provider may still finish and charge this request.'));
      return;
    }
    if (state.stopping) { detach(); state.status = 'Stopped'; addMessage('system', t('Stopped watching this run. It ends on the server after the current step, and the result is kept in the project.')); await refreshBanner(); return; }
    state.stopping = true;
    try {
      let runId = state.serverRun;
      if (!runId) runId = (await api(`/api/run/active?project=${encodeURIComponent(state.project.id)}`)).active?.run_id;
      if (runId) await api(`/api/run/${encodeURIComponent(runId)}/cancel`, {});
    } catch (e) { state.stopping = false; throw e; }
  }
  async function clearView() { detach(); resetViewer(); map.value?.clear(); await loadHistory(); guard(attachActiveRun); }
  async function newThread() { if (!state.project || state.running) return; await api(projectUrl('/chat'), undefined, 'DELETE'); await loadHistory(); }
  async function replayRun(id) {
    if (state.running) return;
    const project = state.project?.id;
    const res = await api(projectUrl(`/trace?run=${encodeURIComponent(id)}`));
    if (project !== state.project?.id) return;
    addMessage('divider', t('replay · {id}', { id }));
    for (const e of res.events || []) {
      if (e.thought) traceItem('thought', e.thought);
      if (e.action) traceItem('action', e.action);
      const obs = e.observation_full || e.observation;
      if (obs) { if (/^finish\b/.test(e.action || '')) { closeTrace(); addMessage('answer', cleanFinish(String(obs)), { markdown: true }); } else traceItem(e.success === false ? 'error' : 'observe', String(obs).slice(0, 600)); }
    }
    closeTrace();
    if (res.code) { state.code = res.code; state.tab = 'code'; }
    addMessage('divider', t('end of replay'));
  }
  async function remember(text) { await api('/api/memory/append', { text: text.trim().slice(0, 500), section: 'Notes' }); addMessage('system', t('Remembered') + ': ' + text.slice(0, 120)); }
  async function changeLanguage(code) { setLanguage(code); await api('/api/settings/ui', { language: code }); }
  async function init() {
    currentUser.value = await api('/api/auth/me');
    const settings = await api('/api/settings');
    setLanguage(detectLanguage(settings.language)); state.viewerFollow = settings.viewer_follow !== false;
    await Promise.all([refreshModels(), refreshProjects(), api(isAdmin.value ? '/api/settings/basemap' : '/api/map').then(v => { state.basemap = v; }), api('/api/version').then(v => { state.version = v.version; })]);
    if (!state.models.length) addMessage('error', t('No model configured'));
    await refreshBanner();
  }
  onBeforeUnmount(() => { disposed = true; detach(); clearTimeout(bannerTimer); });
  return { state, map, collapsed, selection, elapsedLabel, elsewhere, canRun, runBlockedReason, guard, projectUrl, addMessage, refreshModels, refreshProjects, refreshTree, selectProject, clearProject, openFile, runAnalysis, stopRun, clearView, newThread, replayRun, remember, changeLanguage, init };
}
