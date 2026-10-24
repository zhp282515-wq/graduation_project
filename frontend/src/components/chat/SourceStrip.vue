<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { groupSources, sourceKindLabel } from '../../utils/citations'
import Icon from '../ui/Icon.vue'

const props = defineProps({
  sources: { type: Array, default: () => [] },
})

const emit = defineEmits(['open', 'open-all'])

const groups = computed(() => groupSources(props.sources))

const stripEl = ref(null)

// 竖直滚轮在出处条上转成横向滚动，长列表不必去抓细滚动条。
function onWheel(event) {
  const el = stripEl.value
  if (!el || el.scrollWidth <= el.clientWidth) return
  if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return
  event.preventDefault()
  el.scrollLeft += event.deltaY
}

onMounted(() => stripEl.value?.addEventListener('wheel', onWheel, { passive: false }))
onBeforeUnmount(() => stripEl.value?.removeEventListener('wheel', onWheel))
</script>

<template>
  <div v-if="sources.length" class="source-strip">
    <span class="strip-label mono">出处</span>
    <div ref="stripEl" class="strip-items" tabindex="0" aria-label="本轮全部出处，可左右滚动">
      <button
        v-for="(group, index) in groups"
        :key="group.key"
        type="button"
        class="source-pill"
        :title="group.title"
        @click="emit('open', group.items[0])"
      >
        <span class="pill-index mono">{{ String(index + 1).padStart(2, '0') }}</span>
        <span class="pill-title">{{ group.title }}</span>
        <span class="pill-meta mono">
          {{ sourceKindLabel(group.items[0]) }}
          <template v-if="group.items[0].page"> · p.{{ group.items[0].page }}</template>
        </span>
        <span v-if="group.items.length > 1" class="pill-count mono">×{{ group.items.length }}</span>
      </button>
    </div>
    <button
      type="button"
      class="strip-all mono"
      title="在右侧抽屉里逐条核对全部出处"
      @click="emit('open-all')"
    >
      核对 {{ sources.length }}
      <Icon name="arrowRight" :size="12" />
    </button>
  </div>
</template>

<style scoped>
.source-strip {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px dashed var(--line);
  min-width: 0;
}

.strip-label {
  flex: none;
  font-size: var(--text-2xs);
  letter-spacing: 0.2em;
  color: var(--ink-4);
}

.strip-items {
  display: flex;
  flex: 1 1 auto;
  align-items: center;
  gap: 6px;
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: none;
  padding-bottom: 2px;
  /* 两侧渐隐，提示这一排可以继续横向滚动 */
  mask-image: linear-gradient(90deg, transparent 0, #000 7px, #000 calc(100% - 14px), transparent 100%);
  -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 7px, #000 calc(100% - 14px), transparent 100%);
}

.strip-items:focus-visible {
  outline: 1px solid var(--accent-line);
  outline-offset: 2px;
}

.strip-items::-webkit-scrollbar {
  display: none;
}

.source-pill {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: baseline;
  gap: 6px;
  max-width: 300px;
  padding: 4px 9px;
  border: 1px solid var(--line);
  border-radius: var(--r-full);
  background: var(--surface-2);
  white-space: nowrap;
  transition: border-color var(--t-fast), background var(--t-fast);
}

.source-pill:hover {
  border-color: var(--accent-line);
  background: var(--accent-soft);
}

.pill-index {
  font-size: 9px;
  color: var(--accent);
}

.pill-title {
  max-width: 170px;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: var(--text-xs);
  color: var(--ink-2);
}

.pill-meta {
  font-size: 9.5px;
  color: var(--ink-4);
  letter-spacing: 0.04em;
}

.pill-count {
  font-size: 9px;
  color: var(--accent);
  letter-spacing: 0.02em;
}

.pill-more {
  font-size: var(--text-2xs);
  color: var(--ink-4);
  padding-left: 2px;
}

.strip-all {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  font-size: var(--text-2xs);
  color: var(--ink-3);
  letter-spacing: 0.06em;
}

.strip-all:hover {
  color: var(--accent);
}

@media (min-width: 1180px) {
  .source-strip {
    /* 借用右侧为走栏预留的留白，让出处条比正文更宽一些 */
    margin-right: calc(-1 * (var(--thread-gutter, 92px) + var(--thread-gap, 26px)));
  }
}

@media (max-width: 640px) {
  .source-strip {
    flex-wrap: wrap;
  }

  .strip-all {
    margin-left: 0;
  }
}
</style>
