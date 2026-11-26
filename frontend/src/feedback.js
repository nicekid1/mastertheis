import { reactive } from 'vue';

const state = reactive({ toasts: [], dialog: null });
const modalQueue = [];
let nextId = 0;

export function useFeedback() { return state; }

export function toast(message, type = 'info', duration = type === 'error' ? 8000 : 4500) {
  const text = String(message ?? '').trim();
  if (!text) return;
  const duplicate = state.toasts.find(item => item.text === text && item.type === type);
  if (duplicate) {
    clearTimeout(duplicate.timer);
    duplicate.timer = setTimeout(() => dismissToast(duplicate.id), duration);
    return;
  }
  const item = { id: ++nextId, text, type, timer: null };
  item.timer = setTimeout(() => dismissToast(item.id), duration);
  state.toasts.push(item);
  if (state.toasts.length > 4) dismissToast(state.toasts[0].id);
}

export function dismissToast(id) {
  const index = state.toasts.findIndex(item => item.id === id);
  if (index < 0) return;
  clearTimeout(state.toasts[index].timer);
  state.toasts.splice(index, 1);
}

export function reportError(error) {
  if (error?.name === 'AbortError') return;
  toast(error?.message || error || 'Unexpected error', 'error');
}

function enqueueDialog(dialog) {
  modalQueue.push(dialog);
  if (!state.dialog) state.dialog = modalQueue.shift();
}

export function showMessage(message, { title = 'Message', type = 'info' } = {}) {
  const text = String(message ?? '').trim();
  if (!text) return;
  enqueueDialog({ id: ++nextId, kind: 'message', title, text, type });
}

export function confirmMessage(message, { title = 'Confirm', confirmLabel = 'Continue', cancelLabel = 'Cancel' } = {}) {
  return new Promise(resolve => enqueueDialog({
    id: ++nextId, kind: 'confirm', title, text: String(message ?? ''),
    confirmLabel, cancelLabel, resolve,
  }));
}

export function resolveDialog(answer = false) {
  const current = state.dialog;
  if (!current) return;
  state.dialog = null;
  if (current.resolve) current.resolve(answer);
  queueMicrotask(() => { if (!state.dialog) state.dialog = modalQueue.shift() || null; });
}

export async function runSafely(action) {
  try { return await action(); }
  catch (error) { reportError(error); return undefined; }
}
