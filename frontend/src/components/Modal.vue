<script setup>
import { onMounted, onBeforeUnmount, ref, watch, nextTick } from 'vue';
const props = defineProps({ open: Boolean, title: String, id: String, closeId: String, small: Boolean });
const emit = defineEmits(['close']);
const panel = ref(null);
let previousFocus;
watch(() => props.open, async open => {
  if (open) { previousFocus = document.activeElement; await nextTick(); panel.value?.focus(); }
  else if (previousFocus?.isConnected) previousFocus.focus();
});
function keydown(event) {
  if (!props.open || !panel.value?.contains(document.activeElement)) return;
  if (event.key === 'Escape') { event.stopPropagation(); emit('close'); }
  if (event.key === 'Tab') {
    const items = [...panel.value.querySelectorAll('button, input, select, textarea, a[href], [tabindex="0"]')].filter(el => !el.disabled && el.getClientRects().length);
    const first = items[0], last = items.at(-1);
    if (!first) { event.preventDefault(); return; }
    if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.value)) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
}
onMounted(() => document.addEventListener('keydown', keydown));
onBeforeUnmount(() => document.removeEventListener('keydown', keydown));
</script>
<template>
  <Teleport to="body">
    <div :id="id" class="modal-overlay" :class="{ hidden: !open }" @click.self="$emit('close')">
      <section ref="panel" class="modal" :class="small ? 'modal-sm' : 'modal-lg'" role="dialog" aria-modal="true" :aria-label="title" tabindex="-1">
        <div class="modal-head"><span class="modal-title">{{ title }}</span><button :id="closeId" class="modal-close" aria-label="Close" @click="$emit('close')">✕</button></div>
        <slot />
      </section>
    </div>
  </Teleport>
</template>
