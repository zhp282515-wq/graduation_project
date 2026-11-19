<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { request } from '../api/http'
import { copyText } from '../utils/clipboard'
import { useUiStore } from '../stores/ui'

const ui = useUiStore()
async function copyId(id) {
  try { await copyText(id); ui.notify('已复制用户 ID', 'ok') }
  catch { ui.notify('复制失败，可选中 ID 手动复制', 'err') }
}

const categories = [{key:'runtime', label:'运行日志'}, {key:'operations', label:'用户操作'}]
const levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
const sources = ['API','DeepSeek','通义千问','OpenAI','会话服务','对话流程','用量统计','知识库','知识星图','向量化','重排','文档解析','工具执行','记忆','应用']
const timestamp = new Intl.DateTimeFormat('zh-CN', {
  timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit',
  hour:'2-digit', minute:'2-digit', second:'2-digit', hourCycle:'h23',
})
const category = ref('runtime'), rows = ref([]), next = ref(null), cursors = ref([null])
const form = reactive({start:'', end:'', level:'', source:'', actor_id:'', outcome:''})
const active = ref({}), busy = ref(true), error = ref('')
let controller
async function load() {
  controller?.abort()
  const current = new AbortController()
  controller = current
  busy.value = true
  error.value = ''
  try {
    const data = await request('/api/admin/logs', {
      query:{category:category.value, ...active.value, before:cursors.value.at(-1)}, signal:current.signal,
    })
    if (controller === current) { rows.value = data.items; next.value = data.next }
  } catch (e) {
    if (controller === current && !current.signal.aborted) error.value = e.message || '读取日志失败'
  } finally {
    if (controller === current) busy.value = false
  }
}
function apply() {
  const {start,end,level,source,actor_id,outcome} = form
  active.value = category.value === 'runtime' ? {start,end,level,source,actor_id:actor_id.trim()} : {start,end,actor_id:actor_id.trim(),outcome}
  cursors.value = [null]
  load()
}
function switchTo(key) {
  if (category.value === key) return
  category.value = key
  apply()
}
function turn(forward) {
  if (forward) cursors.value.push(next.value)
  else cursors.value.pop()
  load()
}
onMounted(load)
onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <main class="log-view">
    <header><h1>日志看板</h1><button class="btn" :disabled="busy" @click="apply">刷新</button></header>
    <nav class="log-tabs" aria-label="日志分类">
      <button v-for="tab in categories" :key="tab.key" :aria-pressed="category === tab.key" @click="switchTo(tab.key)">{{ tab.label }}</button>
    </nav>
    <form class="filters" @submit.prevent="apply">
      <label>开始日期<input type="date" v-model="form.start" :max="form.end || undefined"></label>
      <label>结束日期<input type="date" v-model="form.end" :min="form.start || undefined"></label>
      <template v-if="category === 'runtime'">
        <label>级别<select v-model="form.level"><option value="">全部级别</option><option v-for="l in levels" :key="l">{{ l }}</option></select></label>
        <label>来源<select v-model="form.source"><option value="">全部来源</option><option v-for="s in sources" :key="s">{{ s }}</option></select></label>
      </template>
      <template v-else>
        <label>结果<select v-model="form.outcome"><option value="">全部结果</option><option>成功</option><option>失败</option></select></label>
      </template>
      <label>用户 ID<input v-model="form.actor_id" maxlength="64" placeholder="完整用户 ID"></label>
      <button class="btn">查询</button>
    </form>
    <p v-if="busy" role="status">正在读取日志…</p>
    <p v-else-if="error" role="alert">{{ error }} <button class="btn" @click="load">重试</button></p>
    <p v-else-if="!rows.length" role="status">没有符合条件的日志</p>
    <ul v-else class="entries">
      <li v-for="row in rows" :key="row.id">
        <time :datetime="row.occurred_at">{{ timestamp.format(new Date(row.occurred_at)) }}</time>
        <span class="indicator" :data-level="row.level" :class="{warning: row.outcome==='失败'}">{{ row.level || row.outcome }}</span>
        <div class="event">
          <strong>{{ row.event }}</strong>
          <span v-if="category==='runtime'">{{ row.source }}<template v-if="row.purpose"> · {{ row.purpose }}</template><template v-if="row.model"> · {{ row.model }}</template><template v-if="!row.actor_kind && ['DeepSeek','OpenAI','通义千问','向量化','重排'].includes(row.source)"> · 用途及模型未记录</template></span>
        </div>
        <span v-if="row.actor_id" class="actor">
          <code :aria-label="'用户 ID ' + row.actor_id">{{ row.actor_id }}</code>
          <button class="copy-id" type="button" :aria-label="'复制用户 ID ' + row.actor_id" @click="copyId(row.actor_id)">复制</button>
        </span>
        <span v-else class="identity">{{ row.actor_kind==='system' ? '系统任务' : category==='runtime' && !row.actor_kind ? '用户 ID 未记录' : '未识别用户' }}</span>
      </li>
    </ul>
    <footer><button class="btn" :disabled="busy || cursors.length===1" @click="turn(false)">上一页</button><span>第 {{ cursors.length }} 页</span><button class="btn" :disabled="busy || !!error || !next" @click="turn(true)">下一页</button></footer>
  </main>
</template>

<style scoped>
.log-view { flex:1; min-width:0; overflow:auto; padding:clamp(16px,4vw,54px); color:var(--ink); }
.log-view > * {max-width:1120px; margin-inline:auto}
header,footer,.filters,.log-tabs {display:flex; align-items:center; gap:12px}
header {justify-content:space-between}
h1 {font:normal clamp(28px,4vw,40px) var(--font-serif); margin:0}
.log-tabs {border-bottom:1px solid var(--line); margin-block:20px}
.log-tabs button {border:0; background:transparent; color:var(--ink-3); padding:10px 4px}
.log-tabs button[aria-pressed=true] {color:var(--ink); box-shadow:inset 0 -2px var(--ink)}
.filters {align-items:end; flex-wrap:wrap}
.filters label {display:grid; gap:5px; color:var(--ink-2); font-size:12px}
input,select {font:inherit; color:var(--ink); background:var(--surface); border:1px solid var(--line); border-radius:6px; min-height:34px; padding:4px 8px; min-width:0}
.entries {padding:0; list-style:none; margin-block:18px}
.entries li {display:grid; grid-template-columns:160px 78px minmax(100px,1fr) minmax(100px,1fr); gap:12px; align-items:center; padding:12px 0; border-bottom:1px solid var(--line); font-size:13px}
time,code,footer {font-size:12px; font-variant-numeric:tabular-nums; color:var(--ink-2)}
code {overflow-wrap:anywhere; user-select:all; min-width:0}
.event {display:grid; gap:3px; overflow-wrap:anywhere}
.event span,.identity {color:var(--ink-2); font-size:12px}
.actor {display:inline-flex; width:fit-content; max-width:100%; align-items:center; gap:5px}
.copy-id {opacity:0; pointer-events:none; flex:none; font-size:12px; color:var(--ink-2); background:var(--surface); border:1px solid var(--line); border-radius:4px; padding:2px 6px}
.actor:hover .copy-id,.actor:focus-within .copy-id {opacity:1; pointer-events:auto}
@media(hover:none) { .actor .copy-id {opacity:1; pointer-events:auto} }
.indicator {font:12px var(--font-mono); color:var(--ink-2)}
.warning {color:var(--usage-user)}
.indicator[data-level] {display:inline-flex; align-items:center; gap:5px}
.indicator[data-level]::before {content:''; width:6px; height:6px; flex:none; border-radius:50%; background:currentColor}
.indicator[data-level="DEBUG"] {color:var(--ink-3)}
.indicator[data-level="INFO"] {color:var(--log-info)}
.indicator[data-level="WARNING"] {color:var(--warn)}
.indicator[data-level="ERROR"] {color:var(--err)}
.indicator[data-level="CRITICAL"] {color:var(--log-critical); font-weight:700}
footer {justify-content:flex-end; margin-top:16px}
@media(max-width:700px) {
  .entries li {grid-template-columns:1fr auto; gap:5px}
  .entries .event,.entries li > :last-child {grid-column:1 / -1}
  .filters label {flex:1 1 40%; min-width:0}
}
</style>
