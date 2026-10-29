<script setup>
import { onMounted, ref } from 'vue'
import { request } from '../api/http'
import { useAuthStore } from '../stores/auth'
import { useUiStore } from '../stores/ui'
import { useConfirm } from '../composables/confirm'
const auth = useAuthStore(), ui = useUiStore()
const { confirm } = useConfirm()
const users = ref([]), total = ref(0), page = ref(1), query = ref(''), loading = ref(false), error = ref('')
const creating = ref(false), username = ref(''), password = ref(''), role = ref('user'), saving = ref(false)
const resetId = ref(''), temporary = ref(''), busyId = ref('')
let sequence = 0
async function load() {
  const id = ++sequence; loading.value = true; error.value = ''
  try {
    const data = await request('/api/admin/users', { query: { q: query.value, page: page.value } })
    if (id !== sequence) return
    users.value = data.items; total.value = data.total
  } catch (err) { if (id === sequence) error.value = err.message }
  finally { if (id === sequence) loading.value = false }
}
async function create() {
  saving.value = true; error.value = ''
  try {
    await request('/api/admin/users', { method:'POST', body: { username:username.value,password:password.value,role:role.value } })
    password.value = ''; username.value = ''; creating.value = false; page.value = 1
    ui.notify('账号已创建，首次登录需修改临时密码','ok'); await load()
  } catch (err) { error.value = err.message } finally { saving.value = false }
}
async function update(user, patch) {
  if (!await confirm({ title:'调整账号权限', body:`修改 ${user.username} 后，该账号的现有登录会失效。`, confirmText:'确认修改', danger:true })) return
  busyId.value = user.id; error.value = ''
  try {
    await request(`/api/admin/users/${encodeURIComponent(user.id)}`, { method:'PATCH',body:patch })
    if (user.id === auth.user.id) { window.dispatchEvent(new Event('auth-expired')); return }
    await load(); ui.notify('账号已更新','ok')
  } catch (err) { error.value = err.message } finally { busyId.value = '' }
}
async function reset(user) {
  busyId.value = user.id; error.value = ''
  try {
    await request(`/api/admin/users/${encodeURIComponent(user.id)}/reset-password`,{ method:'POST',body:{ password:temporary.value } })
    temporary.value=''; resetId.value=''; ui.notify('已重置，用户下次登录必须修改密码','ok')
    if (user.id === auth.user.id) window.dispatchEvent(new Event('auth-expired'))
  } catch (err) { error.value = err.message } finally { busyId.value = '' }
}
async function remove(user) {
  const ok = await confirm({
    title: `注销「${user.username}」？`,
    body: '这个账号的会话、长期记忆和全部笔记会一起删除，登录凭据立即失效，且无法恢复。',
    detail: '知识库里的文档不会跟着删除，仍归知识库所有。',
    confirmText: '注销账号',
    requireText: user.username,
    danger: true,
  })
  if (!ok) return
  busyId.value = user.id; error.value = ''
  try {
    await request(`/api/admin/users/${encodeURIComponent(user.id)}`, { method:'DELETE' })
    if (users.value.length === 1 && page.value > 1) page.value -= 1
    await load(); ui.notify(`已注销 ${user.username}`,'ok')
  } catch (err) { error.value = err.message } finally { busyId.value = '' }
}
onMounted(load)
</script>
<template>
  <section class="admin-view view"><div class="view-inner"><header class="view-head"><div><h1>账号管理</h1><p>管理身份与访问权限。会话和个人记忆由各账号自行管理。</p></div><button type="button" class="btn accent" @click="creating=!creating">{{ creating ? '收起创建' : '创建账号' }}</button></header>
    <form v-if="creating" class="create-account" @submit.prevent="create"><label>用户名<input v-model="username" autocomplete="off" required pattern="[A-Za-z0-9_-]{3,32}" maxlength="32" placeholder="3–32位字母、数字、_ 或 -" /></label><label>临时密码<input v-model="password" type="password" autocomplete="new-password" required minlength="8" maxlength="128" /></label><label>角色<select v-model="role"><option value="user">普通用户</option><option value="admin">管理员</option></select></label><button class="btn solid" :disabled="saving">{{ saving ? '创建中…' : '创建账号' }}</button></form>
    <form class="account-toolbar" @submit.prevent="page=1;load()"><label class="sr-only" for="user-search">搜索用户名</label><input id="user-search" v-model="query" type="search" placeholder="搜索用户名" /><button class="btn" :disabled="loading">查询</button><span>{{ total }} 个账号</span></form><p role="alert" class="admin-error">{{ error }}</p>
    <div class="account-table"><table><thead><tr><th>用户名</th><th>角色</th><th>状态</th><th>密码</th><th>操作</th></tr></thead><tbody><template v-for="user in users" :key="user.id"><tr><td>{{ user.username }} <span v-if="user.id===auth.user?.id" class="self-label">本人</span></td><td>{{ user.role==='admin' ? '管理员' : '普通用户' }}</td><td>{{ user.enabled ? '启用' : '停用' }}</td><td>{{ user.must_change_password ? '待修改临时密码' : '已设置' }}</td><td><div class="row-actions"><button type="button" :disabled="busyId===user.id" @click="update(user,{ role:user.role==='admin' ? 'user' : 'admin' })">{{ user.role==='admin' ? '改为普通用户' : '设为管理员' }}</button><button type="button" :disabled="busyId===user.id" @click="update(user,{ enabled:!user.enabled })">{{ user.enabled ? '停用' : '启用' }}</button><button type="button" @click="resetId=resetId===user.id?'':user.id;temporary=''">重置密码</button><button v-if="user.id!==auth.user?.id" type="button" class="danger" :disabled="busyId===user.id" @click="remove(user)">注销账号</button></div></td></tr><tr v-if="resetId===user.id"><td colspan="5"><form class="reset-row" @submit.prevent="reset(user)"><label :for="`reset-${user.id}`">{{ user.username }} 的临时密码</label><input :id="`reset-${user.id}`" v-model="temporary" type="password" autocomplete="new-password" required minlength="8" maxlength="128" /><button class="btn" :disabled="busyId===user.id">确认重置</button></form></td></tr></template><tr v-if="!users.length"><td colspan="5">{{ loading ? '正在加载账号…' : '没有匹配的账号' }}</td></tr></tbody></table></div>
    <div class="account-pagination"><button type="button" class="btn" :disabled="page===1||loading" @click="page--;load()">上一页</button><span>第 {{ page }} / {{ Math.max(1,Math.ceil(total/20)) }} 页</span><button type="button" class="btn" :disabled="page*20>=total||loading" @click="page++;load()">下一页</button></div>
  </div></section>
</template>
<style scoped>
.admin-view { overflow:auto;padding-bottom:44px; }.view-head p { color:var(--ink-3);font-size:14px;margin-top:18px;max-width:55ch; }.create-account { display:flex;flex-wrap:wrap;align-items:end;gap:20px;padding-block:30px;border-bottom:1px solid var(--line); }.create-account label { display:grid;gap:7px;font-size:14px; }.admin-view input,.admin-view select { background:var(--surface);border:1px solid var(--line-strong);padding:9px 12px;border-radius:var(--r-xs);min-height:42px; }.create-account .btn { min-height:42px; }.account-toolbar { display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-top:30px; }.account-toolbar>span { margin-left:auto;color:var(--ink-3);font-size:14px; }.account-toolbar .btn { min-height:42px; }.admin-error { color:var(--err);min-height:24px;margin-block:12px;font-size:14px; }.account-table { overflow-x:auto; }table { width:100%;border-collapse:collapse;text-align:left;font-size:14px;white-space:nowrap; }th { font-size:13px;font-weight:500;color:var(--ink-3); }td,th { border-bottom:1px solid var(--line);padding:18px 15px 18px 0; }.row-actions { display:flex;gap:15px; }.row-actions button { color:var(--accent);font-size:13px; }.row-actions button:hover { text-decoration:underline; }.row-actions button.danger { color:var(--err); }.self-label { font-size:11px;color:var(--ink-3);margin-left:7px; }.reset-row { display:flex;align-items:center;gap:16px;flex-wrap:wrap; }.account-pagination { display:flex;justify-content:flex-end;align-items:center;gap:20px;margin-top:28px;font-size:13px; }
</style>
