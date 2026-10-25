<script setup>
import { computed, ref, watch } from 'vue'
import { formatNumber } from '../../utils/format'
import { sourceMeta, typeLabel } from '../../utils/citations'
import BaseSheet from '../ui/BaseSheet.vue'
import Icon from '../ui/Icon.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  sources: { type: Array, default: () => [] },
  initialId: { type: String, default: '' },
})

const emit = defineEmits(['update:open', 'locate', 'archive', 'ask'])

const activeId = ref('')
const copied = ref(false)

const active = computed(
  () => props.sources.find((item) => item.id === activeId.value) || props.sources[0] || null,
)

watch(
  () => [props.open, props.initialId, props.sources],
  () => {
    if (!props.open) return
    copied.value = false
    activeId.value = props.initialId || props.sources[0]?.id || ''
  },
  { immediate: true },
)

// 只允许 http(s) 链接，避免把 unknown scheme 直接塞进 href。
const webHref = computed(() => {
  const raw = String(active.value?.url || '').trim()
  return /^https?:\/\//i.test(raw) ? raw : ''
})

// 网页引用的 title 常常就是 URL 本身，此时不再重复渲染一遍标题。
const titleIsUrl = computed(() => {
  if (active.value?.kind !== 'web') return false
  const title = String(active.value?.title || '').trim()
  const url = String(active.value?.url || '').trim()
  return Boolean(title) && title === url
})

const webHost = computed(() => {
  const raw = String(active.value?.url || '').trim()
  try {
    return new URL(raw).hostname
  } catch {
    return ''
  }
})

const title = computed(() => (props.sources.length > 1 ? '本轮出处' : active.value?.title || '出处'))
const subtitle = computed(() =>
  props.sources.length > 1 ? `${props.sources.length} 条引用，点击左侧切换` : active.value ? sourceMeta(active.value) : '',
)

async function copyText() {
  if (!active.value?.text) return
  try {
    await navigator.clipboard.writeText(active.value.text)
    copied.value = true
    window.setTimeout(() => (copied.value = false), 1800)
  } catch {
    copied.value = false
  }
}

function close() {
  emit('update:open', false)
}
</script>

<template>
  <BaseSheet
    :open="open"
    :title="title"
    :subtitle="subtitle"
    eyebrow="引用 · SOURCES"
    :width="560"
    @update:open="emit('update:open', $event)"
  >
    <div class="source-sheet">
      <nav v-if="sources.length > 1" class="source-nav" aria-label="引用列表">
        <button
          v-for="(item, index) in sources"
          :key="item.id"
          type="button"
          class="nav-row"
          :class="{ 'is-active': item.id === active?.id }"
          @click="activeId = item.id"
        >
          <span class="nav-index mono">{{ String(index + 1).padStart(2, '0') }}</span>
          <span class="nav-main">
            <span class="nav-title">{{ item.title }}</span>
            <span class="nav-meta mono">{{ sourceMeta(item) }}</span>
          </span>
        </button>
      </nav>

      <template v-if="active">
        <div class="source-head">
          <h3 v-if="!titleIsUrl" class="source-title">{{ active.title }}</h3>
          <p v-else class="source-url-title">{{ webHost || active.url }}</p>
          <p class="source-meta mono">
            <template v-if="active.kind === 'web'">网页引用</template>
            <template v-else>{{ typeLabel(active.fileType) }}</template>
            <span v-if="active.page"> · 第 {{ active.page }} 页</span>
            <span v-if="active.chunkIndex !== null"> · 分片 #{{ active.chunkIndex }}</span>
            <span v-if="active.text"> · {{ formatNumber(active.text.length) }} 字</span>
          </p>
          <p v-if="active.sectionPath" class="section-path mono">{{ active.sectionPath }}</p>
        </div>

        <blockquote v-if="active.text" class="source-text">{{ active.text }}</blockquote>
        <p v-else-if="active.kind === 'web'" class="source-empty">这条网页引用没有保存正文快照，可打开原始网页查看。</p>
        <p v-else class="source-empty">这条引用没有附带正文快照。</p>

        <p v-if="active.kind === 'web' && webHref" class="web-url mono">
          <a class="inline-link" :href="webHref" target="_blank" rel="noopener noreferrer">
            {{ active.url }}
            <Icon name="external" :size="12" />
          </a>
          <span class="web-hint">在新标签页打开原始网页</span>
        </p>

        <div class="source-actions">
          <button v-if="active.kind === 'knowledge'" type="button" class="btn btn--sm" @click="emit('locate', active)">
            <Icon name="atlas" :size="13" />
            在星图中定位
          </button>
          <button v-if="active.kind === 'knowledge'" type="button" class="btn btn--sm" @click="emit('archive', active)">
            <Icon name="archive" :size="13" />
            所属文档
          </button>
          <button type="button" class="btn btn--sm" :disabled="!active.text" @click="copyText">
            <Icon :name="copied ? 'check' : 'copy'" :size="13" />
            {{ copied ? '已复制' : '复制正文' }}
          </button>
          <button v-if="active.kind === 'knowledge'" type="button" class="btn btn--sm btn--quiet" @click="emit('ask', active)">
            <Icon name="inquiry" :size="13" />
            以此提问
          </button>
        </div>
      </template>
      <p v-else class="source-empty">这一轮没有记录引用。</p>
    </div>
  </BaseSheet>
</template>

<style scoped>
.source-sheet {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.source-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface-2);
  max-height: 220px;
  overflow-y: auto;
}

.nav-row {
  display: flex;
  gap: 10px;
  padding: 7px 8px;
  border-radius: var(--r-xs);
  text-align: left;
  color: var(--ink-2);
}

.nav-row:hover,
.nav-row.is-active {
  background: var(--surface);
}

.nav-index {
  font-size: 11px;
  color: var(--accent);
  padding-top: 2px;
}

.nav-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-title {
  font-size: var(--text-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-meta {
  font-size: 11px;
  color: var(--ink-4);
}

.source-title {
  font-family: var(--font-serif);
  font-size: var(--text-lg);
  font-weight: 500;
  letter-spacing: 0.03em;
  line-height: 1.45;
}

.source-meta {
  margin: 4px 0 14px;
  font-size: 11px;
  letter-spacing: 0.05em;
  color: var(--ink-4);
}

.source-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.section-path {
  margin-top: 10px;
  font-size: 11px;
  color: var(--ink-3);
  letter-spacing: 0.03em;
}

.source-text {
  margin: 0;
  padding: 16px 18px;
  border-left: 2px solid var(--accent-line);
  background: var(--surface-2);
  border-radius: 0 var(--r-sm) var(--r-sm) 0;
  font-size: var(--text-sm);
  line-height: 1.85;
  color: var(--ink-2);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 46vh;
  overflow-y: auto;
}

.source-empty {
  font-size: var(--text-sm);
  color: var(--ink-3);
}

.source-url-title {
  margin: 0;
  font-family: var(--font-mono);
  font-size: var(--text-md);
  color: var(--ink);
  overflow-wrap: anywhere;
}

.web-hint {
  display: block;
  margin-top: 4px;
  font-size: 11px;
  color: var(--ink-4);
  letter-spacing: 0.04em;
}

.web-url {
  font-size: 11px;
  word-break: break-all;
}

.inline-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--accent);
  text-decoration: underline;
  text-underline-offset: 0.2em;
  text-align: left;
}

.source-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 4px;
}
</style>
