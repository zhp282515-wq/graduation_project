<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { request } from '../api/http'
import UsageActivityChart from '../components/UsageActivityChart.vue'
import Icon from '../components/ui/Icon.vue'

const periods = [1, 7, 30]
const periodName = days => days === 1 ? '今日' : `近 ${days} 天`
const full = value => Number(value ?? 0).toLocaleString('zh-CN')
const clock = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
const calendar = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: 'long', day: 'numeric', weekday: 'long' })
const dayName = day => calendar.format(new Date(day.date + 'T12:00:00+08:00'))
const role = ref('all'), period = ref(1), expanded = ref(false)
const report = ref(null), loading = ref(true), error = ref(''), selected = ref(29)
const activity = ref(null), activityError = ref('')
let timer, controller, activityController
async function refreshActivity() {
  activityController?.abort()
  const current = new AbortController()
  activityController = current
  activityError.value = ''
  try {
    const data = await request('/api/admin/usage/activity', {query:{role:role.value}, signal:current.signal})
    if (activityController === current) activity.value = data
  } catch (err) {
    if (!current.signal.aborted) activityError.value = err.message || '活动统计读取失败'
  }
}
function refreshAll() { refresh(); refreshActivity() }
watch(role, () => { activity.value = null; refreshActivity() })
const selectedDay = computed(() => report.value?.days[selected.value])
const range = computed(() => {
  const recorded = (report.value?.days || []).map(day => day.total).filter(value => value > 0)
  return recorded.length ? [Math.min(...recorded), Math.max(...recorded)] : [0, 0]
})
function tone(day) {
  if (!day.total) return '0%'
  const [low, high] = range.value
  return (high === low ? 60 : 20 + 65 * (day.total - low) / (high - low)) + '%'
}
function dayLabel(day) {
  return dayName(day) + (day.total === null ? ' · 暂无记录' :
    ` · ${full(day.total)} tokens · 用户 ${full(day.user)} · 管理员 ${full(day.admin)}`)
}
async function refresh() {
  controller?.abort()
  const current = new AbortController()
  controller = current
  loading.value = true
  error.value = ''
  const filter = role.value, days = period.value, all = expanded.value
  const get = (path, extra = {}) => request('/api/admin/usage/' + path, {
    query: { role: filter, ...extra }, signal: current.signal,
  })
  try {
    const limit = all ? 100 : 5
    const [cards, trend, ranking] = await Promise.all([
      get('overview'), get('trend'), get('ranking', { days, limit }),
    ])
    const ranks = [...ranking.items]
    while (all && ranks.length < ranking.total) {
      const page = await get('ranking', { days, limit, offset: ranks.length })
      if (!page.items.length) break
      ranks.push(...page.items)
    }
    if (controller === current) report.value = {
      cards: cards.items, days: trend.items, ranks, rankCount: ranking.total, updated: cards.updated_at,
    }
  } catch (err) {
    if (controller === current && !current.signal.aborted) error.value = err.message || '用量读取失败'
  } finally {
    if (controller === current) loading.value = false
  }
}
watch([role, period], () => { expanded.value = false; report.value = null; refresh() })
function toggleAll() { expanded.value = !expanded.value; refresh() }
onMounted(() => { refreshAll(); timer = setInterval(refreshAll, 60000) })
onBeforeUnmount(() => { clearInterval(timer); activityController?.abort(); controller?.abort(); controller = null })
</script>

<template>
  <main class="usage">
    <div class="usage-inner">
      <header class="heading">
        <div><h1>Token 用量</h1><small>仅统计模型接口确认的用量</small></div>
        <div class="controls">
          <select v-model="role" aria-label="按账号角色筛选">
            <option value="all">全部角色</option><option value="user">仅用户</option><option value="admin">仅管理员</option>
          </select>
          <small v-if="report">更新于 {{ clock.format(new Date(report.updated)) }}</small>
          <button class="refresh" type="button" aria-label="刷新用量" :disabled="loading" @click="refreshAll"><Icon name="refresh" /></button>
        </div>
      </header>
      <div v-if="error" class="message" role="alert">{{ error }} <button @click="refresh">重试</button></div>
      <div v-else-if="!report" class="skeletons" role="status" aria-label="正在读取用量"><i v-for="n in 3" :key="n" class="skeleton" /><i class="skeleton matrix-placeholder" /></div>
      <template v-else>
        <section class="cards" aria-label="用量概览">
          <article v-for="card in report.cards" :key="card.period" class="card" tabindex="0">
            <h2>{{ periodName(card.period) }}</h2>
            <strong>{{ card.calls ? full(card.total) : '—' }}</strong>
            <div class="stat-tip" role="tooltip">总量 {{ full(card.total) }} · 输入 {{ full(card.input) }} · 输出 {{ full(card.output) }}<template v-if="card.unclassified"> · 未拆分 {{ full(card.unclassified) }}</template><br>用户 {{ full(card.user) }} · 管理员 {{ full(card.admin) }}</div>
            <div class="split" :style="{ '--share': (100 * card.user / (card.total || 1)) + '%' }" :class="{ filled: card.total }" />
            <div class="stats">
              <span :title="card.period === 1 ? '对比昨日同时段' : '对比前 ' + card.period + ' 天'">{{ card.change === null ? '无对比数据' : (card.change > 0 ? '▲ ' : card.change < 0 ? '▼ ' : '') + Math.abs(card.change) + '%' }}</span>
              <span>{{ full(card.active) }} 人</span><span>{{ full(card.calls) }} 次</span>
            </div>
          </article>
        </section>

        <section class="panel">
          <header><h2>每日用量</h2><small>{{ report.days[0].date.slice(5) }} — {{ report.days[29].date.slice(5) }}</small></header>
          <div class="heat-layout">
            <div class="matrix">
              <button v-for="(day, i) in report.days" :key="day.date" type="button" class="cell"
                :class="{ today: i === 29, selected: selected === i }"
                :style="{ '--tone': tone(day) }" :aria-label="dayLabel(day)" :title="dayLabel(day)"
                @focus="selected = i" @mouseenter="selected = i" @click="selected = i">
                {{ Number(day.date.slice(-2)) }}
              </button>
              <div class="week-outline"><span>7 天</span></div>
            </div>
            <div v-if="selectedDay" class="day-detail">
              <h3>{{ dayName(selectedDay) }}<small v-if="selected === 29">今日</small></h3>
              <strong>{{ selectedDay.total === null ? '—' : full(selectedDay.total) }}</strong>
              <small>{{ selectedDay.total === null ? '暂无用量记录' : 'tokens' }}</small>
              <div><span class="key user">用户</span>{{ full(selectedDay.user) }}</div>
              <div><span class="key admin">管理员</span>{{ full(selectedDay.admin) }}</div>
            </div>
          </div>
        </section>

        <section class="panel ranking">
          <header><h2>用量榜 <small>{{ expanded ? '全部' : 'Top 5' }}</small></h2>
            <div class="tabs" aria-label="榜单时间段"><button v-for="p in periods" :key="p" :aria-pressed="period === p" @click="period = p">{{ p === 1 ? '今日' : p + ' 天' }}</button></div>
          </header>
          <p v-if="!report.ranks.length" class="message">该时段暂无用量记录</p>
          <ol v-else><li v-for="(row, i) in report.ranks" :key="i">
            <span class="rank">{{ i+1 }}</span><span class="name">{{ row.label }} <small v-if="row.roles.includes('admin')" class="badge">管理员</small></span>
            <div class="track"><i :class="{ cool: row.roles.includes('admin') }" :style="{width: (100 * row.total / report.ranks[0].total) + '%'}" /></div>
            <b>{{ full(row.total) }}</b>
          </li></ol>
          <button v-if="report.rankCount > 5" class="more" @click="toggleAll">{{ expanded ? '收起' : '查看全部（' + full(report.rankCount) + '）' }}</button>
        </section>
      </template>
      <UsageActivityChart v-for="kind in ['tools','messages']" :key="kind" :kind="kind"
        :report="activity" :error="activityError" @retry="refreshActivity" />
    </div>
  </main>
</template>

<style scoped>
.usage { --warm:var(--usage-user); --cool:var(--usage-admin); flex:1; min-width:0; overflow:auto; padding:clamp(16px,3vw,44px); color:var(--ink); }
.usage-inner { max-width:1030px; margin:auto; }
.heading,.panel header,.controls,.stats,.tabs,.day-detail div { display:flex; align-items:center; }
.heading,.panel header,.day-detail div { justify-content:space-between; gap:12px; }
.heading { margin-bottom:20px; flex-wrap:wrap; }
h1,h2,h3,p { margin:0; }
h1,h2 { font-family:var(--font-serif); font-weight:500; }
h1 { font-size:clamp(27px,3vw,40px); }
h2 { font-size:19px; }
small,.stats,.rank { font-size:12px; color:var(--ink-3); }
.controls,.tabs { gap:8px; }
select,button { font:inherit; color:inherit; }
select,.refresh,.tabs button,.more { background:var(--surface); border:1px solid var(--line); border-radius:7px; padding:5px 9px; }
.refresh { display:grid; place-items:center; }
.skeletons { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.cards { display:flex; flex-wrap:wrap; gap:12px; }
.card,.panel { background:var(--surface); border:1px solid var(--line); border-radius:12px; }
.card { flex:1 1 0; max-width:100%; position:relative; padding:clamp(12px,2vw,22px); }
.card h2 { font-size:15px; }
.card strong,.day-detail strong { display:block; font-weight:500; font-variant-numeric:tabular-nums; font-family:var(--font-serif); }
.card strong { overflow-wrap:break-word; font-size:clamp(18px,3.4vw,45px); line-height:1.4; }
.stat-tip { display:none; position:absolute; z-index:2; top:65%; left:8px; background:var(--ink); color:var(--bg); padding:8px; border-radius:6px; font-size:12px; }
.card:is(:hover,:focus) .stat-tip { display:block; }
.split,.track { height:5px; border-radius:5px; background:var(--line); overflow:hidden; }
.split.filled { background:linear-gradient(to right,var(--warm) var(--share),var(--cool) var(--share)); }
.stats { gap:8px; margin-top:10px; flex-wrap:wrap; }
.panel { margin-top:16px; padding:clamp(14px,2vw,24px); }
.panel header { margin-bottom:16px; }
.heat-layout { display:grid; grid-template-columns:minmax(0,2fr) minmax(160px,1fr); align-items:center; gap:clamp(20px,5vw,64px); }
.matrix { width:calc(100% - 6px); max-width:500px; display:grid; grid-template:repeat(3,auto)/repeat(10,minmax(0,1fr)); position:relative; gap:5px; margin:3px 3px 14px; }
.cell { width:100%; aspect-ratio:1; padding:0; border:1px solid var(--line); border-radius:4px; font-size:12px; background:color-mix(in srgb,var(--cool) var(--tone),var(--surface-2)); color:var(--ink); font-variant-numeric:tabular-nums; }
.cell.selected { outline:1px solid var(--ink-2); outline-offset:-2px; }
.cell.today { animation:breathe 3s ease-in-out infinite; }
@keyframes breathe { 50% { box-shadow:inset 0 0 0 2px var(--ink-2); } }
@media(prefers-reduced-motion:reduce) { .cell.today { animation:none; box-shadow:inset 0 0 0 2px var(--ink-2); } }
.week-outline { position:absolute; grid-column:4 / 11; grid-row:3 / 4; inset:-3px; pointer-events:none; border:1px solid var(--ink-2); border-radius:7px; }
.week-outline span { position:absolute; right:4px; bottom:-15px; font-size:10px; color:var(--ink-3); }
.day-detail h3 { font-size:15px; font-weight:500; }
.day-detail h3 small { margin-left:8px; }
.day-detail strong { font-size:30px; }
.day-detail div { font-size:13px; border-top:1px solid var(--line); padding-top:4px; margin-top:4px; }
.key::before { content:''; display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; background:var(--warm); }
.key.admin::before,.track i.cool { background:var(--cool); }
.tabs { gap:2px; }
.tabs button { border:0; font-size:12px; }
.tabs button[aria-pressed=true] { background:var(--ink); color:var(--bg); }
ol { padding:0; margin:0; list-style:none; }
li { display:grid; grid-template-columns:18px minmax(100px,1fr) minmax(32px,2fr) minmax(50px,auto); align-items:center; gap:10px; min-height:32px; font-size:13px; }
.track i { display:block; height:100%; background:var(--warm); }
.badge { color:var(--cool); font-size:10px; }
li b { text-align:right; font-variant-numeric:tabular-nums; }
.more { margin-top:10px; font-size:12px; }
.message { padding:16px 0; color:var(--ink-3); }
.skeletons i { min-height:120px; border-radius:10px; }
.matrix-placeholder { grid-column:1/-1; }
@media(min-width:701px) and (max-height:800px) {
  .usage { padding-block:14px; }
  .heading,.panel header { margin-bottom:10px; }
  .card,.panel { padding:14px 20px; }
  .panel { margin-top:10px; }
  .matrix { max-width:420px; }
  li { min-height:27px; }
}
@media(max-width:700px) {
  .usage { padding:14px 10px; }
  .cards { gap:5px; }
  .card { padding:8px; }
  .card h2,.stats { font-size:11px; }
  .stats { gap:3px 5px; }
  .heat-layout { grid-template-columns:1fr; gap:9px; }
  .matrix { gap:4px; }
  .day-detail { display:flex; flex-wrap:wrap; align-items:center; gap:8px; }
  .day-detail strong { font-size:19px; }
  .day-detail div { gap:4px; border:0; padding:0; margin:0; }
  .panel { margin-top:10px; }
  .card:last-child .stat-tip { left:auto; right:0; }
  li { grid-template-columns:16px minmax(0,1fr) minmax(16px,1fr) max-content; gap:6px; }
}
</style>
