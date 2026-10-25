<script setup>
import { computed, ref, watch } from 'vue'
import { STATUS_LABEL, toolArgsSummary, toolHint, toolLabel } from '../../utils/tools'
import { formatDuration } from '../../utils/format'
import { sourceKindLabel } from '../../utils/citations'
import Icon from '../ui/Icon.vue'

const props = defineProps({
  steps: { type: Array, default: () => [] },
  sources: { type: Array, default: () => [] },
  live: { type: Boolean, default: false },
})

const visible = computed(() => props.steps)
// 一轮结束后轨迹保留但收起：它是这次回答“怎么来的”证据，不该随着流结束一起消失。
const open = ref(props.live)
watch(
  () => props.live,
  (value) => {
    if (value) open.value = true
  },
)
const totalElapsed = computed(() =>
  visible.value.reduce((sum, step) => sum + (Number(step.elapsedMs) || 0), 0),
)
</script>

<template>
  <section v-if="visible.length" class="trace" :class="{ 'is-live': live }">
    <div class="trace-head">
      <button
        type="button"
        class="trace-toggle"
        :disabled="live"
        :aria-expanded="open"
        @click="open = !open"
      >
        <span class="trace-title mono">
          <Icon name="sparkle" :size="12" />
          工具轨迹
        </span>
        <Icon :name="open ? 'chevronDown' : 'chevronRight'" :size="12" class="trace-arrow" />
      </button>
      <span class="trace-meta mono">
        {{ visible.length }} 次调用<template v-if="totalElapsed"> · {{ formatDuration(totalElapsed) }}</template>
      </span>
    </div>
    <ol v-show="open" class="trace-list">
      <li v-for="step in visible" :key="step.id" class="trace-step" :data-status="step.status">
        <span class="step-rail" aria-hidden="true">
          <span class="step-dot" />
        </span>
        <div class="step-main">
          <div class="step-line">
            <span class="step-name">{{ toolLabel(step.name) }}</span>
            <span class="step-status mono">{{ STATUS_LABEL[step.status] || step.status }}</span>
            <span v-if="step.elapsedMs" class="step-elapsed mono">{{ formatDuration(step.elapsedMs) }}</span>
          </div>
          <p v-if="toolArgsSummary(step.name, step.args)" class="step-args mono">
            {{ toolArgsSummary(step.name, step.args) }}
          </p>
          <p v-else-if="toolHint(step.name)" class="step-args mono">{{ toolHint(step.name) }}</p>
          <p v-if="step.sources?.length" class="step-sources mono">
            {{ sourceKindLabel(step.sources[0]) }} · {{ step.sources.length }} 条引用
          </p>
        </div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.trace {
  margin: 4px 0 20px;
  padding: 12px 16px 14px;
  border: 1px solid var(--line);
  border-left: 2px solid var(--line-strong);
  border-radius: 0 var(--r-sm) var(--r-sm) 0;
  background: color-mix(in srgb, var(--surface-2) 62%, transparent);
}

.trace.is-live {
  border-left-color: var(--accent);
}

.trace-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 8px;
  border-bottom: 1px dashed var(--line);
}

.trace-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  letter-spacing: 0.18em;
  color: var(--ink-3);
}

.trace-meta {
  font-size: 11px;
  color: var(--ink-4);
}

.trace-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  cursor: pointer;
}

.trace-toggle:disabled {
  cursor: default;
}

.trace-toggle:hover .trace-title {
  color: var(--ink-2);
}

.trace-arrow {
  color: var(--ink-4);
}

.trace-list {
  list-style: none;
  margin: 10px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.trace-step {
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr);
  gap: 8px;
}

.step-rail {
  position: relative;
  display: flex;
  justify-content: center;
  padding-top: 5px;
}

.step-rail::after {
  content: "";
  position: absolute;
  top: 13px;
  bottom: -12px;
  width: 1px;
  background: var(--line);
}

.trace-step:last-child .step-rail::after {
  display: none;
}

.step-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--ink-4);
}

.trace-step[data-status='running'] .step-dot {
  background: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
  animation: pulse 1.4s var(--ease-in-out) infinite;
}

.trace-step[data-status='completed'] .step-dot {
  background: var(--ok);
}

.trace-step[data-status='failed'] .step-dot {
  background: var(--err);
}

@keyframes pulse {
  0%,
  100% {
    box-shadow: 0 0 0 2px var(--accent-soft);
  }
  50% {
    box-shadow: 0 0 0 5px transparent;
  }
}

.step-line {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px;
}

.step-name {
  font-size: var(--text-sm);
  color: var(--ink);
  letter-spacing: 0.02em;
}

.step-status,
.step-elapsed {
  font-size: 11px;
  color: var(--ink-4);
  letter-spacing: 0.08em;
}

.step-args {
  margin-top: 2px;
  font-size: 11px;
  color: var(--ink-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-sources {
  margin-top: 2px;
  font-size: 11px;
  color: var(--accent);
}
</style>
