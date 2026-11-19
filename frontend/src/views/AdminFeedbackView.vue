<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { dislikeReasons, feedbackCategories } from '../api/feedback'
import { http } from '../api/http'
import { copyText } from '../utils/clipboard'
import { formatCount, shanghaiTime } from '../utils/reports'
import { useUiStore } from '../stores/ui'
import ReportChart from '../components/ReportChart.vue'
import BaseSheet from '../components/ui/BaseSheet.vue'
import '../styles/reports.css'

const ui = useUiStore()
const filters = reactive({ category: '', source: '', user_id: '', start: '', end: '' })
const statusFilter = ref('all')
let applied = {}
let pendingList, pendingTrend
const page = ref(null)
const cursors = ref([null])
const listError = ref('')
const listLoading = ref(false)
const trendError = ref('')
const trend = ref(null)
const period = ref(7)
const detail = ref(null)
const detailOpen = ref(false)
const savingStatus = reactive(new Set())
const points = computed(() => trend.value?.days.slice(-period.value) || [])
const series = [
  { key: 'like', label: '点赞', color: 'var(--ok)' },
  { key: 'dislike', label: '点踩', color: 'var(--err)' },
]
function total(key) {
  return points.value.every(p => p[key] == null) ? null : points.value.reduce((sum,p) => sum + (p[key] ?? 0),0)
}
async function loadList(history = cursors.value) {
  pendingList?.abort()
  const controller = new AbortController()
  pendingList = controller
  listLoading.value = true
  listError.value = ''
  try {
    const result = await http.get('/api/admin/feedback', {
      query: { ...applied, status: statusFilter.value, before: history.at(-1) }, signal: controller.signal,
    })
    if (controller.signal.aborted) return
    if (!result.items.length && history.length > 1) return loadList([null])
    page.value = result
    cursors.value = history
  } catch (error) {
    if (!controller.signal.aborted) listError.value = error.message
  } finally {
    if (!controller.signal.aborted) listLoading.value = false
  }
}
function filter() {
  applied = { ...filters, user_id: filters.user_id.trim() }
  loadList([null])
}
async function loadTrend() {
  pendingTrend?.abort()
  const controller = new AbortController()
  pendingTrend = controller
  trendError.value = ''
  try { trend.value = await http.get('/api/admin/feedback/trend', { signal: controller.signal }) }
  catch (error) { if (!controller.signal.aborted) trendError.value = error.message }
}
function refresh() { loadList(); loadTrend() }
function open(entry) { detail.value = entry; detailOpen.value = true }
async function changeStatus(entry, event) {
  const processed = event.target.value === 'processed'
  event.target.value = entry.processed ? 'processed' : 'pending'
  if (savingStatus.has(entry.id) || entry.processed === processed) return
  savingStatus.add(entry.id)
  try {
    const status = await http.put(`/api/admin/feedback/${entry.id}/status`, { processed })
    entry.processed = status.processed
    const listed = page.value?.items.find(item => item.id === entry.id)
    if (listed) listed.processed = status.processed
    if (detail.value?.id === entry.id) detail.value.processed = status.processed
    if (statusFilter.value !== 'all' || listLoading.value) {
      await loadList(listLoading.value ? [null] : cursors.value)
    }
  } catch (error) {
    if (error.name !== 'AbortError') ui.notify(error.message || '状态保存失败，请重试', 'err')
  } finally {
    savingStatus.delete(entry.id)
  }
}
async function copy(id) {
  try { await copyText(id); ui.notify('已复制用户 ID', 'ok') }
  catch { ui.notify('复制失败，可手动选中用户 ID', 'err') }
}
watch(statusFilter, () => loadList([null]))
onMounted(refresh)
onBeforeUnmount(() => { pendingList?.abort(); pendingTrend?.abort() })
</script>

<template>
  <div class="view report-view">
    <div class="view-inner report report-stack">
      <header class="view-head">
        <h1 class="serif">反馈管理</h1>
        <button type="button" class="btn" @click="refresh">刷新</button>
      </header>
      <section class="report-card">
        <div class="trend-head">
          <h2>回答评价趋势</h2>
          <div class="report-segment" aria-label="评价趋势统计周期">
            <button v-for="days in [7,30]" :key="days" type="button" :aria-pressed="period === days" @click="period = days">{{ days }} 天</button>
          </div>
        </div>
        <p v-if="trendError" class="report-error" role="alert">{{ trendError }} <button class="btn" @click="loadTrend">重试</button></p>
        <div v-else-if="!trend" class="report-loading" role="status" aria-label="正在读取评价"><i /><i /><i /></div>
        <template v-else>
          <div class="totals">
            <div v-for="line in series" :key="line.key"><small>{{ line.label }}</small><strong>{{ formatCount(total(line.key)) }}</strong></div>
          </div>
          <ReportChart :points="points" :series="series" title="回答评价" />
          <small class="report-muted">开始统计于 {{ shanghaiTime(trend.started_at) }}（上海时间）</small>
        </template>
      </section>

      <section class="report-card">
        <h2>用户反馈</h2>
        <form class="report-controls filters" @submit.prevent="filter">
          <label>类别 <select v-model="filters.category">
            <option value="">全部</option><option v-for="(name,key) in feedbackCategories" :key="key" :value="key">{{ name }}</option>
          </select></label>
          <label>来源 <select v-model="filters.source">
            <option value="">全部</option><option value="general">意见反馈</option><option value="dislike">回答点踩</option>
          </select></label>
          <label>处理状态 <select v-model="statusFilter">
            <option value="all">全部</option>
            <option value="pending">未处理</option>
            <option value="processed">已处理</option>
          </select></label>
          <label>用户 ID <input v-model="filters.user_id" type="search" maxlength="32" placeholder="完整用户 ID" pattern="[a-fA-F0-9]{32}" /></label>
          <label>开始日期 <input v-model="filters.start" type="date" /></label>
          <label>结束日期 <input v-model="filters.end" type="date" /></label>
          <button type="submit" class="btn">筛选</button>
        </form>
        <p v-if="listError" class="report-error" role="alert">{{ listError }} <button class="btn" @click="loadList()">重试</button></p>
        <div v-else-if="listLoading" class="report-loading" role="status" aria-label="正在读取反馈"><i /><i /><i /></div>
        <p v-else-if="!page?.items.length" class="report-muted">没有符合条件的反馈</p>
        <div v-else class="report-scroll">
          <table class="report-table">
            <thead><tr><th scope="col">时间</th><th scope="col">账号</th><th scope="col">类别</th><th scope="col">来源</th><th scope="col">处理状态</th><th scope="col">详情</th></tr></thead>
            <tbody><tr v-for="entry in page.items" :key="entry.id">
              <td>{{ shanghaiTime(entry.created_at) }}</td><td>{{ entry.username || '已注销用户' }}</td>
              <td>{{ feedbackCategories[entry.category] }}</td><td>{{ entry.from_dislike ? '回答点踩' : '意见反馈' }}</td>
              <td>
                <select class="status-select" :class="{ processed: entry.processed }"
                  :aria-label="'反馈 #' + entry.id + ' 的处理状态'" :value="entry.processed ? 'processed' : 'pending'"
                  :disabled="savingStatus.has(entry.id)" @change="changeStatus(entry, $event)">
                  <option value="pending">未处理</option>
                  <option value="processed">已处理</option>
                </select>
              </td>
              <td><button class="btn btn--sm" @click="open(entry)">查看</button></td>
            </tr></tbody>
          </table>
        </div>
        <nav class="report-buttons pager" aria-label="反馈分页">
          <button class="btn btn--sm" :disabled="listLoading || cursors.length <= 1" @click="loadList(cursors.slice(0,-1))">上一页</button>
          <span>第 {{ cursors.length }} 页</span>
          <button class="btn btn--sm" :disabled="listLoading || !page?.next" @click="loadList([...cursors,page.next])">下一页</button>
        </nav>
      </section>
    </div>
    <BaseSheet v-model:open="detailOpen" title="反馈详情">
      <div v-if="detail" class="feedback-detail">
        <p>{{ detail.username || '已注销用户' }} · {{ shanghaiTime(detail.created_at) }}</p>
        <div class="identity"><code>{{ detail.user_id }}</code> <button class="btn btn--sm" @click="copy(detail.user_id)">复制 ID</button></div>
        <p>{{ feedbackCategories[detail.category] }}<template v-if="detail.reason"> · {{ dislikeReasons[detail.reason] }}</template>
          · {{ detail.processed ? '已处理' : '未处理' }}</p>
        <p v-if="detail.description" class="description">{{ detail.description }}</p>
        <div v-if="detail.images.length" class="pictures">
          <a v-for="position in detail.images" :key="position" :href="`/api/feedback/${detail.id}/images/${position}`" target="_blank" rel="noopener">
            <img :src="`/api/feedback/${detail.id}/images/${position}`" :alt="'反馈图片 ' + position" loading="lazy" />
          </a>
        </div>
      </div>
    </BaseSheet>
  </div>
</template>

<style scoped>
.trend-head, .totals, .identity { display: flex; align-items: center; flex-wrap: wrap; gap: 10px }
.trend-head { justify-content: space-between }
.trend-head h2 { margin: 0 }
.totals { gap: 30px; margin-top: 10px }
.totals div { display: grid; gap: 2px }
.totals strong { font-size: clamp(24px, 4vw, 36px); font-variant-numeric: tabular-nums }
.totals small, .report-muted { color: var(--ink-3) }
.report-card > .report-muted { margin-top: 12px }
.filters { align-items: end; margin-bottom: 12px }
.filters label { display: grid; gap: 4px; font-size: .82rem; color: var(--ink-2) }
.pager { justify-content: end; margin-top: 12px }
.pager span { font-size: .85rem }
.status-select { font-size: .85rem; min-width: max-content }
.status-select.processed { color: var(--ok); background: var(--ok-soft) }
.identity code, .description { overflow-wrap: anywhere }
.description { white-space: pre-wrap }
.pictures { display: grid; gap: 12px }
.pictures img { display: block; border-radius: 8px; max-width: 100%; max-height: 300px; object-fit: contain }
</style>
