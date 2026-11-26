<script setup>
import { ref, reactive, watch } from 'vue';
import Modal from './Modal.vue';
import { api } from '../api';
import { currentUser, isAdmin } from '../auth';
import { language } from '../i18n';
import { runSafely, showMessage, confirmMessage } from '../feedback';
const props = defineProps({ open: Boolean });
const emit = defineEmits(['close']);
const tab = ref('profile'), users = ref([]), files = ref([]), owner = ref(null), busy = ref(false);
const account = ref(null), resetId = ref(''), resetPassword = ref('');
const quotaUser = ref(null), quotaMiB = ref(50);
const create = reactive({ username: '', password: '', role: 'user' });
const passwords = reactive({ current_password: '', new_password: '' });
const text = (fa, en) => language.value === 'fa' ? fa : en;
const mb = bytes => (bytes / 1024 / 1024).toFixed(2);
async function perform(fn) { if (busy.value) return; busy.value = true; try { await runSafely(fn); } finally { busy.value = false; } }
async function refresh() { account.value = await api('/api/account'); if (isAdmin.value) users.value = await api('/api/admin/users'); }
watch(() => props.open, value => { if (value) { tab.value = 'profile'; perform(refresh); } });
async function add() { await api('/api/admin/users', create); create.password = ''; create.username = ''; await refresh(); showMessage(text('حساب ساخته شد. اطلاعات ورود را از مسیر امن به کاربر بدهید.', 'Account created. Deliver credentials securely.')); }
async function toggle(user) { if (!await confirmMessage(text(`وضعیت حساب ${user.username} تغییر کند؟`, `Change status for ${user.username}?`))) return; await api('/api/admin/users/' + user.id, { active: !user.active }, 'PATCH'); await refresh(); }
async function reset() { await api('/api/admin/users/' + resetId.value, { password: resetPassword.value }, 'PATCH'); resetPassword.value = ''; resetId.value = ''; showMessage(text('رمز تغییر کرد و همهٔ نشست‌های کاربر باطل شدند.', 'Password changed; all sessions revoked.')); }
function editQuota(user) { quotaUser.value = user; quotaMiB.value = user.quota / 1048576; }
async function saveQuota() {
  const quota = Math.round(Number(quotaMiB.value) * 1048576);
  if (quotaMiB.value === '' || !Number.isSafeInteger(quota) || quota < 0) throw new Error(text('مقدار فضای اختصاصی معتبر نیست.', 'Invalid storage quota.'));
  if (quota < quotaUser.value.used_bytes && !await confirmMessage(text('سهمیه از مصرف فعلی کمتر است. فایل‌ها حذف نمی‌شوند، ولی بارگذاری جدید مسدود می‌شود. ادامه می‌دهید؟', 'Quota is below current usage. Files will remain, but new uploads will be blocked. Continue?'))) return;
  await api('/api/admin/users/' + quotaUser.value.id, { quota }, 'PATCH');
  quotaUser.value = null; await refresh();
  showMessage(text('سهمیهٔ فضای کاربر تغییر کرد.', 'User storage quota updated.'));
}
async function changePassword() { await api('/api/auth/password', passwords); location.reload(); }
async function loadFiles(user) { owner.value = user; files.value = await api(`/api/admin/users/${user.id}/files`); tab.value = 'files'; }
function downloadUrl(file) { return `/api/admin/users/${owner.value.id}/file?path=${encodeURIComponent(file.path)}`; }
async function remove(file) { if (!await confirmMessage(text(`فایل «${file.path}» حذف شود؟ این حذف قابل بازگردانی نیست.`, `Delete ${file.path}? This cannot be undone.`))) return; await api(downloadUrl(file), undefined, 'DELETE'); await loadFiles(owner.value); await refresh(); showMessage(text('فایل حذف شد و قابل بازگردانی نیست.', 'File permanently deleted.')); }
</script>
<template>
  <Modal id="accountModal" :open="open" :title="text('حساب کاربری و مدیریت', 'Account and administration')" @close="!busy && emit('close')">
    <div class="set-tabs"><button class="set-tab" @click="tab = 'profile'">{{ text('حساب و فضا', 'Account & storage') }}</button><button v-if="isAdmin" class="set-tab" @click="tab = 'users'">{{ text('مدیریت کاربران و فایل‌ها', 'Users & files') }}</button></div>
    <section v-if="tab === 'profile' && account" class="account-body">
      <h3>{{ account.username }} · {{ account.role === 'admin' ? text('مدیر', 'Administrator') : text('کاربر', 'User') }}</h3>
      <p v-if="account.token_budget_enabled === false" role="status">{{ text('حالت تست: محاسبه و محدودیت توکن حساب غیرفعال است. هزینه و محدودیت ارائه‌دهندهٔ مدل همچنان برقرار است.', 'Test mode: account token accounting and limits are disabled. Provider charges and limits still apply.') }}</p>
      <template v-else>
      <p>{{ text('توکن مصرف‌شده', 'Tokens used') }}: {{ account.tokens_used }} / {{ account.token_limit }} · {{ text('باقی‌مانده', 'Remaining') }}: {{ account.tokens_remaining }}</p>
      <p v-if="account.tokens_reserved">{{ text('توکن رزروشده یا مصرف تأییدنشده', 'Reserved or unconfirmed tokens') }}: {{ account.tokens_reserved }}</p>
      <p>{{ text('این سهمیه مجموع ورودی و خروجی کل حساب است و روزانه بازنشانی نمی‌شود.', 'This lifetime account quota includes input and output; it does not reset daily.') }}</p>
      </template>
      <p>{{ text('فضای مصرف‌شده', 'Storage used') }}: {{ mb(account.used_bytes) }} MiB <span v-if="!isAdmin">/ {{ mb(account.quota) }} MiB</span></p>
      <p v-if="isAdmin">{{ text('فضای ادمین مشترک و بدون محدودیت سهمیه است؛ محدودیت فضای اختصاصی فقط برای کاربران عادی اعمال می‌شود.', 'Administrators share storage without a quota; private storage quotas apply only to regular users.') }}</p>
      <progress v-if="!isAdmin" :value="Math.min(account.used_bytes, account.quota || 1)" :max="account.quota || 1" :aria-label="text('مصرف فضا', 'Storage usage')" />
      <p v-if="!isAdmin && account.used_bytes >= account.quota" role="status">{{ text('سهمیه تکمیل شده است؛ برای بارگذاری، فایل حذف کنید یا از ادمین افزایش فضا بخواهید.', 'Storage quota reached. Remove files or ask an administrator for more space.') }}</p>
      <p v-if="!account.analysis_enabled" role="status">{{ text('بارگذاری و مشاهدهٔ فایل فعال است. گفت‌وگوی GIS به محیط اجرای ایزولهٔ آماده نیاز دارد؛ با مدیر تماس بگیرید.', 'Upload and file viewing are available. GIS chat requires a ready isolated worker; contact the administrator.') }}</p>
      <form class="account-form" @submit.prevent="perform(changePassword)"><h4>{{ text('تغییر رمز عبور', 'Change password') }}</h4><label>{{ text('رمز فعلی', 'Current password') }}<input v-model="passwords.current_password" type="password" autocomplete="current-password" required /></label><label>{{ text('رمز جدید', 'New password') }}<input v-model="passwords.new_password" type="password" autocomplete="new-password" maxlength="256" required /></label><button class="primary-btn" :disabled="busy">{{ text('ذخیره و ورود مجدد', 'Save and sign in again') }}</button></form>
    </section>
    <section v-if="tab === 'users' && isAdmin" class="account-body">
      <form class="account-form" @submit.prevent="perform(add)"><h3>{{ text('ایجاد حساب', 'Create account') }}</h3><label>{{ text('نام کاربری', 'Username') }}<input v-model="create.username" required minlength="3" maxlength="64" dir="ltr" /></label><label>{{ text('رمز عبور', 'Password') }}<input v-model="create.password" type="password" autocomplete="new-password" required maxlength="256" /></label><label>{{ text('نقش', 'Role') }}<select v-model="create.role"><option value="user">{{ text('کاربر', 'User') }}</option><option value="admin">{{ text('مدیر', 'Administrator') }}</option></select></label><button class="primary-btn" :disabled="busy">{{ text('ساخت حساب', 'Create') }}</button></form>
      <div v-for="user in users" :key="user.id" class="account-row"><strong>{{ user.username }}</strong><span>{{ user.role }} · {{ user.active ? text('فعال', 'Active') : text('غیرفعال', 'Disabled') }} · {{ mb(user.used_bytes) }} <template v-if="user.role === 'user'">/ {{ mb(user.quota) }}</template> MiB</span><button v-if="user.role === 'user'" class="reset-btn" :disabled="busy" @click="editQuota(user)">{{ text('تغییر سهمیه', 'Storage quota') }}</button><button class="reset-btn" :disabled="busy" @click="perform(() => loadFiles(user))">{{ text('فایل‌ها', 'Files') }}</button><button class="reset-btn" :disabled="busy || user.id === currentUser.id" @click="perform(() => toggle(user))">{{ user.active ? text('غیرفعال‌کردن', 'Disable') : text('فعال‌کردن', 'Enable') }}</button><button class="reset-btn" @click="resetId = user.id">{{ text('تغییر رمز', 'Reset password') }}</button></div>
      <form v-if="quotaUser" class="account-form" @submit.prevent="perform(saveQuota)"><h4>{{ quotaUser.username }}</h4><label>{{ text('فضای اختصاصی (MiB)؛ صفر: توقف بارگذاری', 'Storage (MiB); zero blocks uploads') }}<input v-model="quotaMiB" type="number" min="0" step="any" required /></label><p>{{ text('کاهش سهمیه، فایل‌های موجود را حذف نمی‌کند.', 'Reducing the quota does not delete existing files.') }}</p><button class="primary-btn" :disabled="busy">{{ text('ذخیرهٔ سهمیه', 'Save quota') }}</button></form>
      <form v-if="resetId" class="account-form" @submit.prevent="perform(reset)"><label>{{ text('رمز جدید کاربر', 'New user password') }}<input v-model="resetPassword" type="password" maxlength="256" autocomplete="new-password" required /></label><button class="primary-btn" :disabled="busy">{{ text('ثبت رمز جدید', 'Set password') }}</button></form>
    </section>
    <section v-if="tab === 'files' && isAdmin" class="account-body"><h3>{{ owner?.username }}</h3><p v-if="!files.length">{{ text('فایلی وجود ندارد.', 'No files.') }}</p><div v-for="file in files" :key="file.path" class="account-row"><bdi>{{ file.path }}</bdi><span>{{ mb(file.bytes) }} MiB</span><a :href="downloadUrl(file)" download>{{ text('دانلود', 'Download') }}</a><button class="reset-btn" :disabled="busy" @click="perform(() => remove(file))">{{ text('حذف', 'Delete') }}</button></div></section>
  </Modal>
</template>
<style scoped>
.account-body{padding:20px;max-height:65vh;overflow:auto}.account-form{display:grid;gap:12px;padding:16px 0}.account-form label{display:grid;gap:6px}.account-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap;border-top:1px solid var(--line);padding:12px 0}.account-row bdi{overflow-wrap:anywhere}.account-body progress{width:100%;accent-color:var(--accent)}
</style>
