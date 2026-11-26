<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue';
import App from './App.vue';
import FeedbackHost from './components/FeedbackHost.vue';
import { api } from './api';
import { currentUser } from './auth';
import { reportError } from './feedback';
import BrandMark from './components/BrandMark.vue';
import { BRAND_NAME, brandTagline } from './brand';
const loading = ref(true), busy = ref(false), username = ref(''), password = ref('');
const expire = () => { currentUser.value = null; };
window.addEventListener('auth-expired', expire);
onBeforeUnmount(() => window.removeEventListener('auth-expired', expire));
onMounted(async () => {
  try { currentUser.value = await api('/api/auth/me'); }
  catch { currentUser.value = null; }
  finally { loading.value = false; }
});
async function login() {
  busy.value = true;
  try { currentUser.value = await api('/api/auth/login', { username: username.value, password: password.value }); }
  catch (error) { reportError(error); }
  finally { password.value = ''; busy.value = false; }
}
</script>
<template>
  <div v-if="loading" class="auth-page" dir="rtl">در حال بررسی نشست…</div>
  <App v-else-if="currentUser" />
  <div v-else class="auth-page" dir="rtl">
    <form class="auth-card" @submit.prevent="login">
      <!-- Self-registration disabled: accounts are created only in the admin panel. -->
      <div class="auth-brand"><BrandMark /><div><h1>{{ BRAND_NAME }}</h1><p>{{ brandTagline('fa') }}</p></div></div>
      <h2>ورود به فضای اختصاصی</h2>
      <p>حساب کاربری خود را از مدیر سامانه دریافت کنید.</p>
      <label for="login-user">نام کاربری</label><input id="login-user" v-model="username" autocomplete="username" dir="auto" required />
      <label for="login-password">رمز عبور</label><input id="login-password" v-model="password" autocomplete="current-password" type="password" dir="ltr" required maxlength="256" />
      <button class="primary-btn" :disabled="busy">{{ busy ? 'در حال ورود…' : 'ورود' }}</button>
      <small>اگر سامانه تازه نصب شده است، مدیر باید حساب اولیه را از خط فرمان ایجاد کند.</small>
    </form>
    <FeedbackHost />
  </div>
</template>
<style>
.auth-page{min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);padding:24px}
.auth-card{width:min(420px,100%);display:grid;gap:14px;background:var(--panel,var(--bg));padding:28px;border:1px solid var(--line);border-radius:16px;box-shadow:0 12px 40px #0001}
.auth-card h1,.auth-card h2,.auth-card p{margin:0}.auth-card p,.auth-card small{color:var(--ink-soft);line-height:1.8}
.auth-brand{display:flex;align-items:center;gap:14px;padding-bottom:16px;border-bottom:1px solid var(--line)}
.auth-brand .brand-mark{width:48px;height:48px;flex:none}.auth-brand h1{font-family:var(--font-ui);font-size:28px;font-weight:750}
.auth-brand p{font-size:12px}.auth-card h2{font-size:18px}
.auth-card input,.account-form input,.account-form select{background:var(--bg);color:var(--ink);border:1px solid var(--line);padding:10px;border-radius:8px;min-width:0}
</style>
