<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  title: { type: String, required: true },
  points: { type: Array, required: true },
  series: { type: Array, required: true },
  unit: { type: String, default: '' },
  compact: Boolean,
})
const number = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 })
const selected = ref(null)
const hasData = computed(() => props.points.some(point => props.series.some(line => point[line.key] != null)))
const peak = computed(() => Math.max(1, ...props.points.flatMap(point => props.series.map(line => point[line.key] ?? 0))))
const x = (index) => props.points.length === 1 ? 300 : index * 600 / (props.points.length - 1)
const y = (value) => 100 - 94 * value / peak.value
const point = computed(() => props.points[selected.value])
watch(() => props.points.length, () => { selected.value = null })

function path(key) {
  return props.points.map((p, i) => {
    if (p[key] == null) return ''
    return `${i > 0 && props.points[i - 1][key] != null ? 'L' : 'M'}${x(i)} ${y(p[key])}`
  }).join(' ')
}
function choose(event) {
  const rect = event.currentTarget.getBoundingClientRect()
  selected.value = Math.max(0, Math.min(props.points.length - 1,
    Math.round((event.clientX - rect.left) / rect.width * (props.points.length - 1))))
}
function move(step) {
  selected.value = Math.max(0, Math.min(props.points.length - 1, (selected.value ?? 0) + step))
}
</script>

<template>
  <div v-if="hasData" class="report-chart" :class="{ compact }">
    <div class="chart-body">
      <div v-if="!compact" class="axis" aria-hidden="true"><span>{{ number.format(peak) }}</span><span>0</span></div>
      <div class="plot" :tabindex="compact ? undefined : 0" :role="compact ? undefined : 'slider'"
        :aria-label="compact ? undefined : title + '日期'" :aria-valuemin="compact ? undefined : 1"
        :aria-valuemax="compact ? undefined : points.length" :aria-valuenow="compact ? undefined : (selected ?? 0) + 1"
        :aria-valuetext="compact ? undefined : point ? point.date + ' ' + series.map(line => line.label + ' ' + (point[line.key] ?? '暂无')).join('，') : points[0].date"
        @keydown.left.prevent="move(-1)" @keydown.right.prevent="move(1)"
        @keydown.home.prevent="selected = 0" @keydown.end.prevent="selected = points.length - 1"
        @focus="selected ??= 0" @pointermove="!compact && choose($event)" @pointerdown="!compact && choose($event)">
        <svg viewBox="0 0 600 100" preserveAspectRatio="none" aria-hidden="true">
          <line v-for="tick in (compact ? [100] : [5, 37, 69, 100])" :key="tick" x1="0" x2="600" :y1="tick" :y2="tick" class="gridline" />
          <line v-if="point" :x1="x(selected)" :x2="x(selected)" y1="0" y2="100" class="cursor" />
          <path v-for="line in series" :key="line.key" :d="path(line.key)" :stroke="line.color || 'var(--accent)'" />
        </svg>
        <template v-for="line in series" :key="line.key">
          <template v-for="(p, i) in points" :key="p.date">
            <i v-if="p[line.key] != null && (i === selected || (points[i - 1]?.[line.key] == null && points[i + 1]?.[line.key] == null))"
              class="dot" :style="{ left: x(i) / 6 + '%', top: y(p[line.key]) + '%', background: line.color || 'var(--accent)' }" />
          </template>
        </template>
      </div>
      <div v-if="!compact" class="dates"><span>{{ points[0]?.date?.slice(5) }}</span><span v-if="points.length > 1">{{ points.at(-1)?.date?.slice(5) }}</span></div>
    </div>
    <div v-if="!compact" class="chart-key">
      <span v-for="line in series" :key="line.key"><i :style="{ background: line.color || 'var(--accent)' }" />{{ line.label }}</span>
    </div>
    <div v-if="!compact && point" class="chart-detail">
      <b>{{ point.date }}</b>
      <span v-for="line in series" :key="line.key">{{ line.label }} {{ point[line.key] == null ? '—' : number.format(point[line.key]) + unit }}</span>
    </div>
  </div>
  <p v-else-if="!compact" class="report-empty">此期间暂无可绘制的数据</p>
</template>

<style scoped>
.chart-body { display: grid; grid-template-columns: min-content minmax(0, 1fr); gap: 8px 12px; margin: 16px 4px 0 }
.axis { display: flex; flex-direction: column; justify-content: space-between; font-size: 11px; color: var(--ink-3); text-align: right }
.plot { position: relative; height: clamp(100px, 13vw, 170px); touch-action: pan-y; cursor: crosshair }
.compact .chart-body { display: block; margin: 6px 2px 2px }
.compact .plot { height: 24px; cursor: default }
svg { display: block; width: 100%; height: 100%; overflow: visible }
svg * { vector-effect: non-scaling-stroke }
path { fill: none; stroke-width: 2px; stroke-linejoin: round }
.gridline { stroke: var(--line) }
.cursor { stroke: var(--ink-3); stroke-dasharray: 3 4 }
.dot { position: absolute; width: 6px; height: 6px; border-radius: 50%; transform: translate(-50%, -50%); pointer-events: none }
.dates { grid-column: 2; display: flex; justify-content: space-between; color: var(--ink-3); font-size: 11px }
.chart-key, .chart-detail { display: flex; gap: 6px 16px; flex-wrap: wrap; margin-top: 10px; font-size: 12px; color: var(--ink-3) }
.chart-key i { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-inline-end: 5px }
.report-empty { color: var(--ink-3); font-size: .9rem }
</style>
