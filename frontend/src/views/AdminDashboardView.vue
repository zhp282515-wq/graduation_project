<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { http } from '../api/http'
import { dislikeReasons } from '../api/feedback'
import { formatCount, formatPercent, shanghaiClock, shanghaiTime } from '../utils/reports'
import ReportChart from '../components/ReportChart.vue'
import '../styles/reports.css'

const tabs = { overview: '概览', quality: '内容与质量', knowledge: '知识库', system: '系统', security: '安全' }
const tools = { direct: '直接回答', knowledge_search: '知识库检索', academic_calendar: '校历', get_weather: '天气', websearch: '联网搜索' }
const failures = { timeout: '超时', upstream: '上游服务异常', tool_error: '工具执行失败', internal: '内部异常' }
const cards = { active: '活跃用户', sessions: '对话数', new: '新增用户', approval: '好评率', missing: '没查到率', errors: '错误率' }
const actions = { errors: '请求错误率持续偏高', latency: '首字响应过慢', missing: '没查到率上升', ingest: '知识库入库失败', frequency: '异常高频账号' }
const detections = { sensitive_block: '敏感内容拦截', suspected_injection: '疑似提示词注入', crisis: '心理危机触发' }
const thisPeriod = { key: 'active', label: '本期', color: 'var(--ok)' }
const priorPeriod = { key: 'previous', label: '上期', color: 'var(--ink-3)' }
const durationSeries = (prefix) => [
  { key: prefix + '_p50', label: 'P50', color: 'var(--ok)' },
  { key: prefix + '_p95', label: 'P95', color: 'var(--err)' },
]
const percentCards = new Set(['approval','missing','errors'])
const days = { 1: '今日', 7: '近 7 天', 30: '近 30 天' }
const selected = ref('overview'), period = ref(7), role = ref('all')
const data = ref(null), error = ref(''), loading = ref(false)
const auditData = ref(null), auditError = ref(''), auditLoading = ref(false), auditAction = ref(''), auditPages = ref([null])
const marking = ref('')
let pending, pendingAudit, timer

async function load({ reset = false } = {}) {
  pending?.abort()
  const controller = new AbortController()
  pending = controller
  if (reset) data.value = null
  loading.value = true
  error.value = ''
  try {
    data.value = await http.get('/api/admin/dashboard/' + selected.value, {
      query: { period: period.value, role: role.value }, signal: controller.signal,
    })
  } catch (err) {
    if (!controller.signal.aborted) error.value = err.message || '运营数据读取失败'
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}

async function loadAudit(pages = auditPages.value) {
  pendingAudit?.abort()
  const controller = new AbortController()
  pendingAudit = controller
  auditLoading.value = true
  auditError.value = ''
  try {
    auditData.value = await http.get('/api/admin/dashboard/audit', {
      query: { period: period.value, role: role.value, action: auditAction.value, before: pages.at(-1) },
      signal: controller.signal,
    })
    auditPages.value = pages
  } catch (err) {
    if (!controller.signal.aborted) auditError.value = err.message
  } finally {
    if (!controller.signal.aborted) auditLoading.value = false
  }
}

function refresh() {
  load()
  if (selected.value === 'security') loadAudit()
}

watch([selected, period, role], () => {
  load({ reset: true })
  pendingAudit?.abort()
  auditData.value = null
  auditPages.value = [null]
  if (selected.value === 'security') loadAudit([null])
})
onMounted(() => {
  refresh()
  timer = setInterval(refresh, 60_000)
})
onBeforeUnmount(() => { clearInterval(timer); pending?.abort(); pendingAudit?.abort() })

async function markGap(keyword, state) {
  if (marking.value) return
  marking.value = keyword
  try {
    await http.put('/api/admin/dashboard/gaps/' + encodeURIComponent(keyword), { state })
    await load()
  } catch (err) {
    error.value = err.message || '标记失败，请重试'
  } finally {
    marking.value = ''
  }
}
function filledDays(rows, dateKey = 'date') {
  if (!data.value) return []
  const mapped = new Map(rows.map(row => [row[dateKey], row]))
  const start = Date.parse(data.value.start_date + 'T00:00:00Z')
  return Array.from({ length: period.value }, (_, i) => {
    const date = new Date(start + i * 86_400_000).toISOString().slice(0,10)
    return { ...mapped.get(date), date }
  })
}
function alertName(rule) {
  return rule.startsWith('tool:') ? (tools[rule.slice(5)] || '工具') + '失败率过高' : actions[rule]
}
function alertValue(alert) {
  if (alert.rule === 'latency') return formatCount(alert.value) + ' ms'
  if (alert.rule === 'missing') return formatCount(alert.value) + ' 个百分点'
  if (['ingest','frequency'].includes(alert.rule)) return formatCount(alert.value)
  return formatPercent(alert.value)
}
const heat = computed(() => new Map((data.value?.heatmap || []).map(p => [`${p.weekday}:${p.hour}`,p.count])))
const heatPeak = computed(() => Math.max(1, ...heat.value.values()))
const weekdays = ['一','二','三','四','五','六','日']
const growing = computed(() => (data.value?.topics || []).filter(r => r.previous != null && r.count > r.previous)
  .sort((a, b) => (b.count - b.previous) - (a.count - a.previous)).slice(0,5))
const activeAlerts = computed(() => (data.value?.alerts || []).filter(alert => !alert.recovered_at))
const recoveredAlerts = computed(() => (data.value?.alerts || []).filter(alert => alert.recovered_at))
</script>

<template>
  <div class="view report-view">
    <div class="view-inner report report-stack">
      <header class="view-head">
        <h1 class="serif">运营看板</h1>
        <div class="report-controls">
          <span class="report-muted">更新于 {{ shanghaiClock(data?.updated_at) }}</span>
          <button class="btn btn--sm" :disabled="loading" @click="refresh">{{ loading && data ? '刷新中…' : '刷新' }}</button>
        </div>
      </header>
      <div class="report-controls toolbar">
        <nav class="report-segment tabs" aria-label="看板分类">
          <button v-for="(name,key) in tabs" :key="key" type="button" :aria-current="selected === key ? 'page' : undefined" @click="selected = key">{{ name }}</button>
        </nav>
        <div class="report-controls">
          <div class="report-segment" aria-label="统计周期">
            <button v-for="(label,n) in days" :key="n" type="button" :aria-pressed="period === Number(n)" @click="period = Number(n)">{{ label }}</button>
          </div>
          <select v-model="role" aria-label="账号范围"><option value="all">全部</option><option value="user">仅用户</option></select>
        </div>
      </div>
      <p v-if="error" class="report-error" role="alert">{{ error }} <button class="btn btn--sm" @click="refresh">重试</button></p>
      <div v-if="!data && loading" class="report-loading" role="status" aria-label="正在读取运营数据"><i v-for="i in 6" :key="i" /></div>

      <template v-if="data && selected === 'overview'">
        <section class="report-card">
          <h2>待办与告警</h2>
          <div class="report-grid">
            <div>
              <button class="btn btn--quiet btn--sm" @click="selected = 'knowledge'">待更新文档 {{ formatCount(data.stale) }} · 查看知识库</button>
              <ul v-if="data.gaps.length" class="report-list">
                <li v-for="gap in data.gaps" :key="gap.keyword"><span>{{ gap.keyword }}</span><span>{{ formatCount(gap.count) }} 次</span></li>
              </ul>
              <p v-else class="report-muted">所选期间暂无待处理的知识缺口</p>
            </div>
            <div>
              <ul v-if="activeAlerts.length" class="report-list">
                <li v-for="alert in activeAlerts" :key="alert.rule + alert.triggered_at">
                  <span><strong>{{ alertName(alert.rule) }}</strong><br /><small class="report-muted">{{ shanghaiTime(alert.triggered_at) }} · {{ alertValue(alert) }}</small></span>
                  <span class="warning">生效中</span>
                </li>
              </ul>
              <p v-else class="report-muted">暂无生效中的告警</p>
              <details v-if="recoveredAlerts.length" class="history">
                <summary>已恢复 {{ formatCount(recoveredAlerts.length) }} 条</summary>
                <ul class="report-list">
                  <li v-for="alert in recoveredAlerts" :key="alert.rule + alert.triggered_at">
                    <span>{{ alertName(alert.rule) }}<br /><small class="report-muted">{{ shanghaiTime(alert.triggered_at) }} · {{ alertValue(alert) }}</small></span>
                    <span class="resolved">{{ shanghaiTime(alert.recovered_at) }}</span>
                  </li>
                </ul>
              </details>
              <small class="report-muted">系统告警使用全站数据</small>
            </div>
          </div>
        </section>
        <div class="metrics">
          <section v-for="card in data.cards" :key="card.key" class="report-card metric">
            <h2>{{ cards[card.key] }}</h2>
            <strong>{{ percentCards.has(card.key) ? formatPercent(card.value) : formatCount(card.value) }}</strong>
            <small class="report-muted">
              <template v-if="card.change != null">{{ card.change > 0 ? '▲' : card.change < 0 ? '▼' : '·' }} {{ formatPercent(Math.abs(card.change)) }}</template>
              <template v-else>{{ card.previous === 0 ? '上期为 0' : '暂无可比数据' }}</template>
            </small>
            <ReportChart title="指标趋势" :points="data.trend" :series="[{ key: card.key, label: cards[card.key] }]" compact />
          </section>
        </div>
        <section class="report-card">
          <h2>活跃趋势</h2>
          <ReportChart title="活跃趋势" :points="data.trend" :series="[thisPeriod,priorPeriod]" />
        </section>
      </template>

      <div v-else-if="data && selected === 'quality'" class="report-grid">
        <section class="report-card report-wide">
          <h2>回答质量</h2>
          <div class="quality-metrics">
            <div>好评率 <b>{{ formatPercent(data.metrics.approval) }}</b>
              <small>{{ formatCount(data.metrics.votes) }} 票{{ data.metrics.votes < 20 ? ' · 样本较少' : '' }}</small></div>
            <div>评价覆盖率 <b>{{ formatPercent(data.metrics.feedback) }}</b></div>
            <div>没查到率 <b>{{ formatPercent(data.metrics.missing) }}</b></div>
            <div>疑似重复提问 <b>{{ formatPercent(data.repeat) }}</b></div>
            <div>带来源占比 <b>{{ formatPercent(data.metrics.sources) }}</b></div>
            <div>平均检索次数 <b>{{ formatCount(data.metrics.avg_searches) }}</b></div>
            <div>检索达到 3 次 <b>{{ formatPercent(data.metrics.capped) }}</b></div>
          </div>
          <ReportChart title="没查到率趋势" :points="filledDays(data.trend)" :series="[{ key: 'missing', label: '没查到率' }]" unit="%" />
        </section>
        <section class="report-card">
          <h2>热门关键词 Top 10</h2>
          <ul v-if="data.keywords.length" class="report-list"><li v-for="row in data.keywords" :key="row.keyword"><span>{{ row.keyword }}</span><b>{{ formatCount(row.count) }}</b></li></ul>
          <p v-else class="report-muted">暂无关键词数据</p>
        </section>
        <section class="report-card">
          <h2>话题分布</h2>
          <ul v-if="data.topics.length" class="report-list"><li v-for="row in data.topics" :key="row.topic"><span>{{ row.topic }}</span><b>{{ formatPercent(row.share) }}</b></li></ul>
          <p v-else class="report-muted">暂无话题数据</p>
          <h3>增长最多 Top 5</h3>
          <ul v-if="growing.length" class="report-list"><li v-for="row in growing" :key="row.topic">{{ row.topic }} <b>+{{ formatCount(row.count - row.previous) }}</b></li></ul>
          <p v-else class="report-muted">暂无可展示的增长话题</p>
        </section>
        <section class="report-card">
          <h2>问题分流</h2>
          <ul v-if="data.routes.length" class="report-list"><li v-for="row in data.routes" :key="row.route"><span>{{ tools[row.route] }}</span><b>{{ formatPercent(row.share) }}</b></li></ul>
          <p v-else class="report-muted">暂无分流数据</p>
        </section>
        <section class="report-card">
          <h2>点踩原因</h2>
          <ul v-if="data.reasons.length" class="report-list"><li v-for="row in data.reasons" :key="row.reason">{{ dislikeReasons[row.reason] }} <b>{{ formatCount(row.count) }}</b></li></ul>
          <p v-else class="report-muted">暂无点踩原因</p>
        </section>
        <section class="report-card report-wide">
          <h2>提问时段 · 上海时间</h2>
          <div v-if="heat.size" class="heatmap">
            <template v-for="(weekday,index) in weekdays" :key="weekday">
              <small>{{ weekday }}</small>
              <span v-for="hour in 24" :key="hour" class="heat-cell"
                :style="{ '--intensity': (heat.get(`${index+1}:${hour-1}`) || 0) / heatPeak }"
                :title="`星期${weekday} ${hour-1}:00，${heat.get(`${index+1}:${hour-1}`) ?? 0} 条提问`" />
            </template>
          </div>
          <p v-else class="report-muted">暂无提问时段数据</p>
        </section>
        <section class="report-card report-wide">
          <h2>留存</h2>
          <ul class="report-list"><li v-for="(row,n) in data.retention" :key="n"><span>{{ n === '1' ? '次日留存' : '第 7 日留存' }}</span><span>{{ formatPercent(row.rate) }} · {{ formatCount(row.retained) }} / {{ formatCount(row.eligible) }} 人</span></li></ul>
        </section>
      </div>

      <div v-else-if="data && selected === 'knowledge'" class="report-grid">
        <section class="report-card">
          <h2>知识库文档</h2>
          <div class="quality-metrics">
            <div>已入库 <b>{{ formatCount(data.documents.reduce((sum,row) => sum + row.count,0)) }}</b></div>
            <div>最近更新 <b>{{ shanghaiTime(data.documents.map(r => r.last_update).sort().at(-1)) }}</b></div>
            <div>联网搜索占比 <b>{{ formatPercent(data.web_share) }}</b></div>
          </div>
          <ul class="report-list"><li v-for="row in data.documents" :key="row.file_type"><span>{{ row.file_type.toUpperCase() }}</span><b>{{ formatCount(row.count) }}</b></li></ul>
        </section>
        <section class="report-card">
          <h2>缺口词榜</h2>
          <ul v-if="data.gaps.length" class="report-list">
            <li v-for="row in data.gaps" :key="row.keyword" class="gap">
              <div>{{ row.keyword }} <small class="report-muted">{{ formatCount(row.count) }} 次 / {{ formatCount(row.people) }} 人</small></div>
              <div class="report-buttons">
                <button class="btn btn--sm" :disabled="Boolean(marking)" @click="markGap(row.keyword,'fixed')">已补充</button>
                <button class="btn btn--quiet btn--sm" :disabled="Boolean(marking)" @click="markGap(row.keyword,'ignored')">忽略</button>
              </div>
            </li>
          </ul>
          <p v-else class="report-muted">所选期间暂无待处理的知识缺口</p>
        </section>
        <section class="report-card">
          <h2>久未更新 · {{ formatCount(data.stale[0]?.total ?? 0) }} 份</h2>
          <ul v-if="data.stale.length" class="report-list"><li v-for="row in data.stale" :key="row.file_md5"><RouterLink :to="'/archive/' + row.file_md5">{{ row.file_name }}</RouterLink><small>{{ shanghaiTime(row.updated_at) }}</small></li></ul>
          <p v-else class="report-muted">暂无超过 365 天未更新的文档</p>
        </section>
        <section class="report-card">
          <h2>引用最多 Top 10</h2>
          <ul v-if="data.cited.length" class="report-list"><li v-for="row in data.cited" :key="row.file_md5"><RouterLink :to="'/archive/' + row.file_md5">{{ row.file_name }}</RouterLink><b>{{ formatCount(row.count) }}</b></li></ul>
          <p v-else class="report-muted">所选期间暂无引用数据</p>
        </section>
        <section class="report-card report-wide">
          <h2>近 30 天零引用</h2>
          <p v-if="data.unused === null" class="report-muted">待收集满 30 个自然日的引用数据</p>
          <p v-else-if="!data.unused.length" class="report-muted">暂无零引用文档</p>
          <ul v-else class="report-list"><li v-for="row in data.unused" :key="row.file_md5"><RouterLink :to="'/archive/' + row.file_md5">{{ row.file_name }}</RouterLink><small>{{ shanghaiTime(row.updated_at) }}</small></li></ul>
        </section>
      </div>

      <div v-else-if="data && selected === 'system'" class="report-grid">
        <section v-for="item in [{key:'first',title:'首字响应时间'},{key:'total',title:'总耗时'}]" :key="item.key" class="report-card">
          <h2>{{ item.title }} · 毫秒</h2>
          <ReportChart :title="item.title" :points="filledDays(data.times,'day')" :series="durationSeries(item.key)" unit=" ms" />
        </section>
        <section class="report-card report-wide">
          <h2>请求错误率</h2>
          <ReportChart title="错误率" :points="filledDays(data.times,'day')" :series="[{ key: 'error_rate',label: '错误率',color: 'var(--err)' }]" unit="%" />
        </section>
        <section class="report-card report-wide">
          <h2>工具表现</h2>
          <div v-if="data.tools.length" class="report-scroll">
            <table class="report-table">
              <thead><tr><th>工具</th><th>调用</th><th>成功率</th><th>平均耗时</th><th>P95</th><th>失败原因</th></tr></thead>
              <tbody><tr v-for="row in data.tools" :key="row.name"><td>{{ tools[row.name] }}</td><td>{{ formatCount(row.count) }}</td><td>{{ formatPercent(row.success) }}</td>
                <td>{{ formatCount(row.average) }} ms</td><td>{{ formatCount(row.p95) }} ms</td>
                <td>{{ row.reasons.map(x => failures[x.error] + ' ' + formatCount(x.count)).join('、') || '—' }}</td>
              </tr></tbody>
            </table>
          </div>
          <p v-else class="report-muted">暂无工具调用数据</p>
        </section>
      </div>

      <div v-else-if="data && selected === 'security'" class="report-grid">
        <section v-for="(name,key) in detections" :key="key" class="report-card">
          <h2>{{ name }}</h2>
          <p v-if="key === 'crisis'" class="report-muted">仅计数，不含内容。请按学校相关流程人工关注。</p>
          <template v-if="data.detections[key]?.started_at">
            <b>{{ formatCount(data.detections[key].data.reduce((n,p) => n + p.count,0)) }}</b>
            <ReportChart :title="name" :points="filledDays(data.detections[key].data)" :series="[{ key:'count',label:name }]" />
          </template>
          <p v-else class="report-muted">未接入</p>
        </section>
        <section class="report-card">
          <h2>异常高频账号</h2>
          <ul v-if="data.frequency.length" class="report-list"><li v-for="row in data.frequency" :key="row.account + row.time"><code>{{ row.account }}</code><span>{{ formatCount(row.count) }} 次 · {{ shanghaiTime(row.time) }}</span></li></ul>
          <p v-else class="report-muted">所选期间暂无异常高频账号</p>
        </section>
        <section class="report-card report-wide">
          <h2>管理员操作审计</h2>
          <div class="report-controls">
            <select v-model="auditAction" aria-label="审计操作类型" @change="loadAudit([null])">
              <option value="">全部操作</option>
              <option v-for="(label,key) in auditData?.actions" :key="key" :value="key">{{ label }}</option>
            </select>
          </div>
          <p v-if="auditError" role="alert" class="report-error">{{ auditError }} <button class="btn" @click="loadAudit()">重试</button></p>
          <p v-else-if="auditLoading" role="status" class="report-muted">正在读取审计记录…</p>
          <p v-else-if="!auditData?.items.length" class="report-muted">{{ role === 'user' ? '仅用户范围未包含管理员操作' : '暂无管理员操作' }}</p>
          <div v-else class="report-scroll">
            <table class="report-table">
              <thead><tr><th>时间</th><th>操作人</th><th>操作类型</th><th>对象</th></tr></thead>
              <tbody><tr v-for="row in auditData.items" :key="row.id"><td>{{ shanghaiTime(row.time) }}</td><td><code>{{ row.actor }}</code></td><td>{{ row.action }}</td><td>{{ row.object || '—' }}</td></tr></tbody>
            </table>
          </div>
          <nav v-if="auditData?.next || auditPages.length > 1" class="report-buttons" aria-label="审计分页">
            <button class="btn btn--sm" :disabled="auditPages.length <= 1 || auditLoading" @click="loadAudit(auditPages.slice(0,-1))">上一页</button>
            <button class="btn btn--sm" :disabled="!auditData?.next || auditLoading" @click="loadAudit([...auditPages,auditData.next])">下一页</button>
          </nav>
        </section>
      </div>
      <p v-if="data" class="report-muted">
        运营数据开始统计于 {{ shanghaiTime(data.started_at) }}（上海时间）
        <template v-if="data.activity_started_at !== data.started_at"> · 活跃数据起于 {{ shanghaiTime(data.activity_started_at) }}</template>
      </p>
    </div>
  </div>
</template>

<style scoped>
.toolbar { justify-content: space-between; align-items: flex-start; padding-bottom: 12px; border-bottom: 1px solid var(--line) }
.tabs { max-width: 100%; overflow-x: auto }
.metrics { display: grid; grid-template-columns: repeat(6,minmax(0,1fr)); gap: 10px }
.metric h2 { font-size: .85rem; margin-bottom: 5px }
.metric strong { font-size: clamp(20px, 2.7vw, 30px); letter-spacing: -.035em; line-height: 1.2; font-variant-numeric: tabular-nums; overflow-wrap: anywhere }
.metric small { margin-top: 4px }
.quality-metrics { display: flex; flex-wrap: wrap; gap: 12px 24px }
.quality-metrics div { display: grid; gap: 3px; font-size: .85rem; color: var(--ink-3) }
.quality-metrics b { font-size: 1.2rem; color: var(--ink) }
.warning, .resolved { white-space: nowrap; font-size: .81rem }
.warning { color: var(--err) }
.resolved { color: var(--ok) }
.history { margin-block: 8px; font-size: .85rem }
.history summary { cursor: pointer }
.gap { flex-wrap: wrap }
h3 { font-size: .87rem; margin: 14px 0 4px }
.heatmap { display: grid; grid-template-columns: 16px repeat(24,minmax(0,1fr)); gap: 3px; align-items: center }
.heat-cell { aspect-ratio: 1; border-radius: 2px; background: color-mix(in srgb, var(--ok) calc(var(--intensity) * 90%), var(--surface-2)) }
.report-buttons { margin-top: 8px }
@media (max-width: 1050px) { .metrics { grid-template-columns: repeat(3,minmax(0,1fr)) } }
@media (max-width: 540px) { .metrics { grid-template-columns: repeat(2,minmax(0,1fr)) } .heatmap { gap: 2px } .tabs button { padding-inline: 6px } }
</style>
