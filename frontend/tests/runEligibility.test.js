import test from 'node:test';
import assert from 'node:assert/strict';
import { runDisabledReason } from '../src/runEligibility.js';

const user = { chat_enabled: true, analysis_enabled: true, isolated_analysis_enabled: true };
const state = { chatMode: true, running: false, project: null, activeRun: null };

test('text chat works without a project, data or an analysis worker', () => {
  assert.equal(runDisabledReason(state, { chat_enabled: true }), '');
});
test('analysis explains the missing project instead of silently disabling Run', () => {
  assert.match(runDisabledReason({ ...state, chatMode: false }, user), /Select a project/);
  assert.equal(runDisabledReason({ ...state, chatMode: false, project: { id: 'mine' } }, user), '');
});
test('isolated jobs are not disabled by an unrelated legacy admin run', () => {
  const busy = { ...state, chatMode: false, project: { id: 'mine' }, activeRun: { project_id: 'other', done: false } };
  assert.equal(runDisabledReason(busy, user), '');
  assert.match(runDisabledReason(busy, { ...user, isolated_analysis_enabled: false }), /Another project/);
});
test('permissions and in-flight state still block duplicate or unauthorized runs', () => {
  assert.match(runDisabledReason(state, null), /Sign in/);
  assert.match(runDisabledReason({ ...state, running: true }, user), /already/);
  assert.match(runDisabledReason({ ...state, chatMode: false }, { chat_enabled: true }), /isolated worker/);
});

test('GIS-only mode ignores a stale text-mode preference and requires a project', () => {
  const gisOnly = { ...user, chat_enabled: false };
  assert.match(runDisabledReason(state, gisOnly), /Select a project/);
  assert.equal(runDisabledReason({ ...state, project: { id: 'mine' } }, gisOnly), '');
  assert.match(runDisabledReason(state, { chat_enabled: false, analysis_enabled: false }), /isolated worker/);
});
