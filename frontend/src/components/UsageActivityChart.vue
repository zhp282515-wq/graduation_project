<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({ kind: String, report: Object, error: String })
defineEmits(['retry'])
const period = ref(7), selected = ref(null)
const tools = { get_weather:'天气查询', knowledge_search:'知识库检索', websearch:'网页搜索', academic_calendar:'校历查询' }
const colors = ['var(--log-info)', 'var(--usage-user)', 'var(--ok)', 'var(--log-critical)']
const isTools = computed(() => props.kind === 'tools')
const title = computed(() => isTools.value ? '工具活动' : '消息')
const days = computed(() => props.report?.items.slice(-period.value) || [])
const series = computed(() => {
  if (!isTools.value) return [{ key:'messages', name:'发送消息', color:colors[0] }]
  const keys = new Set(Object.keys(tools))
  for (const day of days.value) for (const key of Object.keys(day.tools || {})) keys.add(key)
  return [...keys].map((key,i) => ({key, name:tools[key] || key, color:colors[i % colors.length]}))
})
const format = n => n.toLocaleString('zh-CN')
function count(day, key) {
  if (day.messages === null) return null
  return isTools.value ? day.tools[key] || 0 : day.messages
}
const plotted = computed(() => series.value.map(s => ({...s, values:days.value.map(d => count(d,s.key))})))
const total = computed(() => plotted.value.reduce((sum,s) => sum + s.values.reduce((a,b) => a+(b ?? 0),0),0))
const maxY = computed(() => {
  const peak = Math.max(1,...plotted.value.flatMap(s => s.values))
  const base = 10 ** Math.floor(Math.log10(peak))
  return [1,2,5,10].find(n => n*base >= peak)*base
})
const ticks = computed(() => {
  const top=maxY.value
  const step=top%4===0 ? top/4 : top%2===0 ? top/2 : top>=5 ? top/5 : 1
  return Array.from({length:top/step+1},(_,i)=>top-i*step)
})
const x = i => i*100/(period.value-1)
const y = v => 100-(v/maxY.value)*100
function path(values) {
  return values.map((n,i) => n===null ? '' : ((i===0 || values[i-1]===null) ? 'M' : 'L')+x(i)+' '+y(n)).join(' ')
}
const startTime = computed(() => props.report && new Intl.DateTimeFormat('zh-CN',{
  timeZone:'Asia/Shanghai',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23',
}).format(new Date(props.report.started_at)))
const launchDate = computed(() => props.report && new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date(props.report.started_at)))
const point = computed(() => selected.value === null ? null : days.value[selected.value])
function selectAt(event) {
  const rect=event.currentTarget.getBoundingClientRect()
  selected.value=Math.max(0,Math.min(period.value-1,Math.round((event.clientX-rect.left)/rect.width*(period.value-1))))
}
function stepBy(amount) {
  selected.value=Math.max(0,Math.min(period.value-1,(selected.value ?? period.value-1)+amount))
}
watch(period,()=>{selected.value=null})
</script>

<template>
  <section class="activity" :aria-label="title">
    <header><h2>{{ title }}</h2>
      <div class="periods"><button v-for="p in [7,30]" :key="p" type="button" :aria-pressed="period===p" @click="period=p">{{ p }} 天</button></div>
    </header>
    <p v-if="error" role="alert">{{ error }} <button @click="$emit('retry')">重试</button></p>
    <p v-else-if="!report" role="status">正在读取{{ title }}…</p>
    <template v-else>
      <small>{{ isTools ? '工具调用次数' : '发送消息条数' }}</small>
      <strong class="total">{{ format(total) }}</strong>
      <div class="chart">
        <div class="axis" aria-hidden="true"><span v-for="t in ticks" :key="t">{{ format(t) }}</span></div>
        <div class="plot" tabindex="0" role="slider" :aria-label="title+'日期'"
          :aria-valuemin="1" :aria-valuemax="period" :aria-valuenow="(selected ?? period-1)+1"
          :aria-valuetext="point ? point.date + ' ' + (point.messages===null ? '无数据' : series.map(s=>s.name+' '+format(count(point,s.key))).join('，')) : days.at(-1).date"
          @focus="selected ??= period-1" @keydown.left.prevent="stepBy(-1)" @keydown.right.prevent="stepBy(1)"
          @keydown.home.prevent="selected=0" @keydown.end.prevent="selected=period-1"
          @pointermove="selectAt" @pointerdown="selectAt">
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            <line v-for="t in ticks" :key="t" x1="0" x2="100" :y1="y(t)" :y2="y(t)" class="gridline"/>
            <line v-if="point" :x1="x(selected)" :x2="x(selected)" y1="0" y2="100" class="cursor"/>
            <path v-for="s in plotted" :key="s.key" :d="path(s.values)" :stroke="s.color" fill="none"/>
          </svg>
          <template v-for="s in plotted" :key="s.key">
            <template v-for="(v,i) in s.values" :key="i">
              <i v-if="v!==null && (i===selected || i===s.values.length-1)" class="dot" :style="{left:x(i)+'%',top:y(v)+'%',background:s.color}"/>
            </template>
          </template>
        </div>
        <div class="dates"><span v-for="i in [0,Math.floor((period-1)/2),period-1]" :key="i">{{ days[i].date.slice(5) }}</span></div>
      </div>
      <div class="legend"><span v-for="s in series" :key="s.key"><i :style="{background:s.color}"/>{{ s.name }}</span></div>
      <div v-if="point" class="detail"><b>{{ point.date }}</b>
        <template v-if="point.messages!==null"><span v-if="isTools">合计 {{ format(Object.values(point.tools).reduce((sum,n)=>sum+n,0)) }}</span><span v-for="s in series" :key="s.key">{{ s.name }} {{ format(count(point,s.key)) }}</span></template>
        <span v-else>未开始统计</span>
      </div>
      <small v-if="days.some(d=>d.date===launchDate)" class="start">开始统计于 {{ startTime }}（上海时间）</small>
    </template>
  </section>
</template>
<style scoped>
.activity {margin-top:16px; padding:clamp(14px,2vw,24px); border:1px solid var(--line); background:var(--surface); border-radius:12px; color:var(--ink)}
header,.periods,.legend,.detail,.dates {display:flex; align-items:center}
header,.dates {justify-content:space-between}
header {margin-bottom:14px}
h2 {margin:0; font:500 19px var(--font-serif)}
button {color:var(--ink); background:var(--surface-2); border:0; border-radius:6px; padding:5px 10px}
.periods button {font-size:12px; background:transparent}
.periods button[aria-pressed=true] {background:var(--ink); color:var(--bg)}
small,.axis,.dates,.legend,.detail {font-size:12px; color:var(--ink-3)}
.total {display:block; font:500 clamp(26px,4vw,38px) var(--font-serif); font-variant-numeric:tabular-nums}
.chart {display:grid; grid-template-columns:max-content minmax(0,1fr); column-gap:12px; margin:14px 4px 12px 0}
.axis {display:flex; flex-direction:column; justify-content:space-between; text-align:right; margin-block:-7px}
.plot {position:relative; height:clamp(125px,16vw,180px); touch-action:pan-y; cursor:crosshair}
svg {width:100%;height:100%;overflow:visible}
svg * {vector-effect:non-scaling-stroke}
path {stroke-width:2; stroke-linejoin:round}
.gridline {stroke:var(--line)}
.cursor {stroke:var(--ink-3); stroke-dasharray:3 4}
.dot {position:absolute; width:5px; height:5px; border-radius:50%; transform:translate(-50%,-50%); pointer-events:none}
.dates {grid-column:2; margin-top:9px}
.legend,.detail {gap:6px 14px; flex-wrap:wrap}
.legend i {display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:5px}
.detail,.start {margin-top:9px}
.start {display:block}
</style>
