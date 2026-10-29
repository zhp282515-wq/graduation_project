<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { changePassword } from '../api/auth'
const auth = useAuthStore()
const router = useRouter()
const current = ref(''), next = ref(''), confirm = ref(''), error = ref(''), busy = ref(false)
async function submit() {
  error.value = ''
  if (next.value !== confirm.value) { error.value = '两次新密码不一致'; return }
  busy.value = true
  try {
    await changePassword({ current_password: current.value, new_password: next.value })
    auth.clear(); auth.ready = true
    await router.replace({ path: '/login', query: { changed: '1' } })
  } catch (err) { error.value = err.message } finally { busy.value = false }
}
</script>
<template>
  <section class="account-view view"><div class="view-inner"><header class="view-head"><div><h1 class="head-title">修改密码</h1><p>{{ auth.user?.must_change_password ? '当前为临时密码，请修改后继续使用。' : '修改成功后，所有设备需要重新登录。' }}</p></div></header><form class="password-form" @submit.prevent="submit"><label>当前密码<input v-model="current" type="password" autocomplete="current-password" required maxlength="128" :disabled="busy" /></label><label>新密码<input v-model="next" type="password" autocomplete="new-password" required minlength="8" maxlength="128" :disabled="busy" /></label><label>确认新密码<input v-model="confirm" type="password" autocomplete="new-password" required minlength="8" maxlength="128" :disabled="busy" /></label><p role="alert" class="account-error">{{ error }}</p><button class="btn accent" :disabled="busy">{{ busy ? '保存中…' : '保存并重新登录' }}</button></form></div></section>
</template>
<style scoped>
.account-view { overflow:auto;padding-bottom:40px; }.view-head p { margin-top:18px;color:var(--ink-3);font-size:14px; }.password-form { display:grid;gap:22px;max-width:440px;margin-top:42px; }.password-form label { display:grid;gap:8px;font-size:14px; }.password-form input { width:100%;background:var(--surface);border:1px solid var(--line-strong);padding:11px 12px;border-radius:var(--r-xs); }.password-form button { min-height:44px; }.account-error { color:var(--err);min-height:24px;font-size:14px; }
</style>
