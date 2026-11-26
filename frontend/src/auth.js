import { ref, computed } from 'vue';
export const currentUser = ref(null);
export const isAdmin = computed(() => currentUser.value?.role === 'admin');
