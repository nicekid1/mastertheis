<script setup>
import { inject, ref, watch, nextTick } from 'vue';
import { workspaceKey } from '../workspace';
import { t } from '../i18n';
import { prose } from '../format';
import { isAdmin, currentUser } from '../auth';
const w = inject(workspaceKey);
const { state, canRun, runBlockedReason, elsewhere, guard } = w;
const scroll = ref(null);
watch(() => state.messages, async () => { await nextTick(); if (scroll.value) scroll.value.scrollTop = scroll.value.scrollHeight; }, { deep: true });
const labels = { system: 'Info', user: 'You', answer: 'Answer', error: 'Issue', finish: 'Info', thought: 'Thought', action: 'Action', observe: 'Observation', status: 'Info' };
function submit(event) { if (!event.shiftKey && !event.isComposing) { event.preventDefault(); guard(w.runAnalysis); } }
</script>
<template>
  <aside class="panel panel-right">
    <div class="chat-head"><div><div id="chatTaskTitle" class="chat-task-title">{{ state.project?.name || t('No project selected') }}</div><div class="chat-sub">{{ t('AI analyst') }}</div></div></div>
    <div class="chat-mode" style="padding: 12px">
      <template v-if="currentUser?.chat_enabled">
        <label>{{ t('Conversation mode') }} <select v-model="state.chatMode" :disabled="state.running"><option :value="true">{{ t('Text chat') }}</option><option :value="false" :disabled="!currentUser?.analysis_enabled">{{ t('GIS analysis') }}</option></select></label>
        <p v-if="state.chatMode">{{ t('Text chat has no file or map access. Chat history is temporary and clears on reload.') }}</p>
      </template>
      <template v-else><strong>{{ t('GIS chat') }}</strong><p>{{ t('Ask the agent to analyze project layers or selected map features.') }}</p></template>
      <p v-if="runBlockedReason && !state.running" id="runBlockedReason" role="status">{{ t(runBlockedReason) }}</p>
    </div>
    <div id="chatScroll" ref="scroll" class="chat-scroll">
      <div v-if="!state.messages.length" class="msg system"><div class="msg-body">{{ t('Describe the analysis, pick a model, then press Run.') }}</div></div>
      <template v-for="m in state.messages" :key="m.id">
        <div v-if="m.kind === 'divider'" class="chat-divider">{{ m.text }}</div>
        <div v-else-if="m.kind === 'trace'" class="trace" :class="{ open: m.open }">
          <div class="trace-head" role="button" tabindex="0" @click="m.open = !m.open" @keydown.enter="m.open = !m.open"><span class="trace-caret"></span><span class="trace-title">{{ t('Reasoning · {n} steps', { n: m.rounds }) }}</span><span class="trace-sub">{{ m.rows.at(-1)?.text?.slice(0, 90) }}</span></div>
          <div class="trace-body"><div v-for="(row, i) in m.rows" :key="i" class="trace-row" :class="'trace-' + row.kind"><span class="trace-tag">{{ t(labels[row.kind]) }}</span><span class="trace-text">{{ row.text }}</span></div></div>
        </div>
        <details v-else-if="m.kind === 'log'" class="msg msg-history log-fold"><summary>{{ t('Log entry written to LOG.md') }}</summary><div class="prose" v-html="prose(m.text)"></div></details>
        <div v-else class="msg" :class="['msg-' + m.kind, { 'msg-history': m.history }]">
          <div class="msg-meta"><span class="agent-tag">{{ t(labels[m.kind] || 'Info') }}</span><button v-if="isAdmin" class="msg-act" :title="t('Remember')" @click="guard(() => w.remember(m.text))">☆</button></div>
          <div class="msg-body">
            <div v-if="m.entry" class="msg-run-head"><button class="run-chip" :class="m.entry.success ? 'ok' : 'bad'" :disabled="state.running || m.entry.kind === 'tool'" @click="guard(() => w.replayRun(m.entry.run_id))">{{ m.entry.run_id || t('failed') }}</button><span>{{ m.entry.rounds || 0 }} {{ t('rounds') }} · {{ m.entry.elapsed_s || 0 }}s</span></div>
            <div v-if="m.markdown" class="prose" v-html="prose(m.text)"></div><div v-else class="message-text">{{ m.text }}</div>
            <div v-if="m.outputs?.length" class="ans-files"><span class="ans-files-label">{{ t('Produced') }}</span><a v-for="file in m.outputs" :key="file" class="run-file" href="#" @click.prevent="guard(() => w.openFile(file))">{{ file }}</a></div>
          </div>
        </div>
      </template>
      <div v-if="state.running" class="assistant-working" role="status" aria-live="polite" aria-atomic="true">
        <div class="assistant-bot-mark" aria-hidden="true">
          <svg viewBox="0 0 40 40" fill="none">
            <path class="bot-antenna" d="M20 5v5m0-5a2 2 0 1 0 0 .01" />
            <rect x="7" y="11" width="26" height="22" rx="8" />
            <path d="M7 18H4m32 0h-3" />
            <circle class="bot-eye" cx="15" cy="21" r="2" />
            <circle class="bot-eye" cx="25" cy="21" r="2" />
            <path d="M15 27c2.5 2 7.5 2 10 0" />
          </svg>
          <span class="bot-orbit"></span>
        </div>
        <div class="assistant-working-copy">
          <strong>{{ t(state.chatMode ? 'The assistant is thinking…' : 'The assistant is analyzing your data…') }}</strong>
          <span>{{ t('This may take a little while. Your request is still running.') }}</span>
        </div>
        <span class="working-dots" aria-hidden="true"><i></i><i></i><i></i></span>
      </div>
    </div>
    <div id="runBanner" class="run-banner" :class="{ hidden: !elsewhere }"><span>{{ t('Running in {p}', { p: state.activeRun?.project_name || state.activeRun?.project_id }) }}</span> <button class="banner-link" @click="guard(() => w.selectProject(state.activeRun.project_id))">{{ t('Open it') }}</button></div>
    <div class="chat-compose"><div v-if="state.selectionCount" class="selection-scope" role="status"><strong>{{ t('Analysis scope: {n} selected features', { n: state.selectionCount }) }}</strong><span>{{ t('Your next prompt will analyze these features.') }}</span><span v-for="group in state.mapSelection" :key="`${group.where}/${group.run || ''}/${group.path}`"><bdi>{{ group.path }}</bdi> · {{ group.ids.length }}</span><button class="reset-btn" :disabled="state.running" @click="w.map.value?.clearSelection()">{{ t('Clear selection') }}</button></div><div class="textarea-wrap"><textarea id="promptInput" v-model="state.prompt" rows="4" spellcheck="false" :placeholder="t('e.g. Compute building density per block and map it.')" @keydown.enter="submit"></textarea></div><div class="compose-actions">
      <select id="modelSelect" v-model="state.model" class="model-select" :disabled="!state.models.length" :title="t('Model')"><option v-if="!state.models.length" value="">{{ t('No model configured') }}</option><option v-for="m in state.models" :key="m.id" :value="m.id">{{ m.display }}</option></select>
      <span class="ca-spacer"></span><button id="resetBtn" class="reset-btn" @click="guard(w.clearView)">{{ t('Clear') }}</button><button id="startBtn" class="primary-btn" :class="{ hidden: state.running }" :disabled="!canRun" @click="guard(w.runAnalysis)">{{ t('Run') }}</button><button id="stopBtn" class="secondary-btn" :class="{ hidden: !state.running }" @click="guard(w.stopRun)">{{ t(state.stopping ? 'Stopping…' : 'Stop') }}</button>
    </div></div>
  </aside>
</template>
<style>.message-text, .trace-text { white-space: pre-wrap; }.trace-head { cursor: pointer; }.chat-task-title { font-weight: 600; }</style>
