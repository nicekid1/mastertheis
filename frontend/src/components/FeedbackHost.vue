<script setup>
import { onMounted, onBeforeUnmount, nextTick, ref, watch } from 'vue';
import { useFeedback, dismissToast, resolveDialog } from '../feedback';
import { t } from '../i18n';
const feedback = useFeedback();
const dialogElement = ref(null);
watch(() => feedback.dialog, async dialog => { if (dialog) { await nextTick(); dialogElement.value?.querySelector('button')?.focus(); } });
function onKeydown(event) {
  if (!feedback.dialog || !dialogElement.value) return;
  if (event.key === 'Escape') { event.preventDefault(); resolveDialog(false); return; }
  if (event.key === 'Tab') {
    const buttons = [...dialogElement.value.querySelectorAll('button:not(:disabled)')];
    const first = buttons[0], last = buttons.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
}
onMounted(() => window.addEventListener('keydown', onKeydown));
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown));
</script>

<template>
  <Teleport to="body">
    <div class="toast-stack" aria-live="polite" aria-relevant="additions removals">
      <div v-for="item in feedback.toasts" :key="item.id" class="app-toast" :class="'toast-' + item.type" :role="item.type === 'error' ? 'alert' : 'status'">
        <span class="toast-mark" aria-hidden="true">{{ item.type === 'error' ? '!' : item.type === 'success' ? '✓' : 'i' }}</span>
        <span class="toast-text">{{ item.text }}</span>
        <button class="toast-close" :aria-label="t('Dismiss')" @click="dismissToast(item.id)">×</button>
      </div>
    </div>
    <div v-if="feedback.dialog" class="feedback-overlay" @click.self="feedback.dialog.kind === 'message' && resolveDialog()">
      <section ref="dialogElement" class="feedback-dialog" role="dialog" aria-modal="true" :aria-label="t(feedback.dialog.title)" tabindex="-1">
        <header class="feedback-dialog-head"><span class="feedback-dialog-symbol" :class="'toast-' + (feedback.dialog.type || 'info')">{{ feedback.dialog.type === 'warning' ? '!' : 'i' }}</span><h2>{{ t(feedback.dialog.title) }}</h2><button class="modal-close" :aria-label="t('Close')" @click="resolveDialog(false)">×</button></header>
        <p class="feedback-dialog-text">{{ feedback.dialog.text }}</p>
        <footer class="feedback-dialog-foot" :class="{ 'confirm-actions': feedback.dialog.kind === 'confirm' }">
          <template v-if="feedback.dialog.kind === 'confirm'"><button class="reset-btn" @click="resolveDialog(false)">{{ t(feedback.dialog.cancelLabel) }}</button><button class="primary-btn" @click="resolveDialog(true)">{{ t(feedback.dialog.confirmLabel) }}</button></template>
          <button v-else class="primary-btn" @click="resolveDialog(true)">{{ t('OK') }}</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>
