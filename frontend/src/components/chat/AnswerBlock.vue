<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { renderMarkdown } from '../../utils/markdown'
import { copyText } from '../../utils/clipboard'
import { formatDuration, formatNumber, plainText } from '../../utils/format'
import { sourceKindLabel } from '../../utils/citations'
import { useNotesStore } from '../../stores/notes'
import { useUiStore } from '../../stores/ui'
import RunTrace from './RunTrace.vue'
import SourceStrip from './SourceStrip.vue'
import BaseSheet from '../ui/BaseSheet.vue'
import Icon from '../ui/Icon.vue'

const props = defineProps({
  answer: { type: Object, required: true },
  live: { type: Boolean, default: false },
  reasoning: { type: String, default: '' },
  steps: { type: Array, default: () => [] },
  phase: { type: String, default: '' },
  error: { type: String, default: '' },
  finishReason: { type: String, default: '' },
  elapsedMs: { type: Number, default: 0 },
  index: { type: Number, default: 1 },
})

const emit = defineEmits(['regenerate', 'open-source', 'open-sources', 'refill'])

const notes = useNotesStore()
const ui = useUiStore()
const router = useRouter()
const reasoningOpen = ref(false)
const copied = ref(false)
const copyTimers = new Map()
const saveOpen = ref(false)
const saveTitle = ref('')
const saveBusy = ref(false)
const savedNoteId = ref('')

onBeforeUnmount(() => {
  copyTimers.forEach((timer) => window.clearTimeout(timer))
})

function resetCopyState(key, reset, delay = 1600) {
  window.clearTimeout(copyTimers.get(key))
  copyTimers.set(key, window.setTimeout(() => {
    reset()
    copyTimers.delete(key)
  }, delay))
}

const hasText = computed(() => Boolean(props.answer.text && props.answer.text.trim()))
const html = computed(() => renderMarkdown(props.answer.text))
const streaming = computed(() => Boolean(props.answer.streaming))
const failed = computed(() => props.phase === 'failed' || props.phase === 'aborted')
const awaiting = computed(() => props.live && !hasText.value && !failed.value)
const reasoningChars = computed(() => props.reasoning.trim().length)
const showTrace = computed(() => props.steps.length > 0)
const sources = computed(() => props.answer.sources || [])

const elapsedLabel = computed(() => (props.elapsedMs ? formatDuration(props.elapsedMs) : ''))

async function copyAnswer() {
  const text = plainText(props.answer.text)
  if (!text) return
  try {
    await copyText(text)
    copied.value = true
    resetCopyState('answer', () => (copied.value = false))
  } catch {
    copied.value = false
  }
}

/** 从正文里挑一句像标题的话：第一个标题，其次第一句非空文本。 */
function suggestTitle() {
  const text = props.answer.text || ''
  const heading = text.match(/^#{1,3}\s+(.+)$/m)
  const line = heading?.[1] || text.split('\n').find((row) => row.trim() && !row.trim().startsWith('![')) || ''
  const clean = line
    .replace(/[*_`>#\[\]()]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  return (clean || `回答 ${props.index}`).slice(0, 40)
}

function openSave() {
  if (!hasText.value) return
  saveTitle.value = suggestTitle()
  saveOpen.value = true
}

async function confirmSave() {
  if (saveBusy.value) return
  saveBusy.value = true
  try {
    const note = await notes.create({
      title: saveTitle.value.trim() || suggestTitle(),
      content: props.answer.text || '',
    })
    savedNoteId.value = note.id
    saveOpen.value = false
    ui.notify('已存进左侧笔记', 'success', {
      action: { label: '打开', run: () => router.push(`/notes/${note.id}`) },
      duration: 5200,
    })
  } catch (err) {
    ui.notify(err?.message || '保存失败', 'error')
  } finally {
    saveBusy.value = false
  }
}

async function onBodyClick(event) {
  const button = event.target.closest?.('[data-copy-code]')
  if (!button || !event.currentTarget.contains(button)) return
  const block = button.closest('.code-block')
  const code = block?.querySelector('code')
  if (!code) return
  const label = button.querySelector('.code-copy-label')
  const setState = (state, text) => {
    button.dataset.copyState = state
    button.setAttribute('aria-label', text)
    label.textContent = text
  }
  try {
    await copyText(code.textContent)
    setState('success', '已复制')
  } catch {
    setState('error', '复制失败，请手动复制')
  }
  resetCopyState(button, () => setState('', '复制代码'), 2000)
}
</script>

<template>
  <article class="answer" :class="{ 'is-live': live }">
    <RunTrace v-if="showTrace" :steps="steps" :sources="sources" :live="streaming" />

    <div v-if="reasoningChars" class="reasoning" :class="{ 'is-open': reasoningOpen }">
      <button type="button" class="reasoning-toggle" @click="reasoningOpen = !reasoningOpen">
        <Icon name="sparkle" :size="12" />
        <span class="mono reasoning-label">{{ streaming ? '思考中' : '思考过程' }}</span>
        <span class="mono reasoning-count">{{ formatNumber(reasoningChars) }} 字</span>
        <Icon :name="reasoningOpen ? 'chevronDown' : 'chevronRight'" :size="12" class="reasoning-arrow" />
      </button>
      <div v-if="reasoningOpen" class="reasoning-body">
        <p>{{ reasoning }}</p>
      </div>
    </div>

    <div v-if="awaiting" class="thinking-lines" aria-label="正在生成回答">
      <span class="skeleton line w-90" />
      <span class="skeleton line w-76" />
      <span class="skeleton line w-84" />
    </div>

    <div
      v-if="hasText"
      class="md markdown-body"
      :class="{ 'is-streaming': streaming }"
      @click="onBodyClick"
      v-html="html"
    />
    <span v-if="streaming && hasText" class="caret" aria-hidden="true" />

    <div v-if="failed" class="run-error" role="alert">
      <span class="error-mark mono">{{ phase === 'aborted' ? '已停止' : '未完成' }}</span>
      <p>{{ error || (phase === 'aborted' ? '这一轮已停止，回答没有保存。' : '这一轮没有返回结果。') }}</p>
      <p class="error-hint">问题已记录在会话里，可以直接再次发送，或换一种问法。</p>
      <button type="button" class="btn btn--quiet btn--sm error-retry" @click="emit('refill')">
        <Icon name="edit" :size="12" />
        把问题放回书写台
      </button>
    </div>

    <p v-if="finishReason === 'max_turns_exceeded'" class="run-note">
      本轮达到 Agent 的最大工具轮次，回答可能不完整。
    </p>

    <SourceStrip
      v-if="sources.length"
      :sources="sources"
      @open="emit('open-source', $event)"
      @open-all="emit('open-sources', sources)"
    />

    <div v-if="!awaiting" class="answer-foot">
      <div class="foot-actions">
        <button type="button" class="btn btn--quiet btn--sm" :disabled="!hasText" @click="copyAnswer">
          <Icon :name="copied ? 'check' : 'copy'" :size="12" />
          {{ copied ? '已复制' : '复制' }}
        </button>
        <button
          type="button"
          class="btn btn--quiet btn--sm"
          :disabled="!hasText || streaming"
          :title="savedNoteId ? '再存一份' : '把这条回答原样存成 Markdown 笔记'"
          @click="openSave"
        >
          <Icon :name="savedNoteId ? 'check' : 'file'" :size="12" />
          {{ savedNoteId ? '已保存' : '保存为笔记' }}
        </button>
        <button
          v-if="!streaming"
          type="button"
          class="btn btn--quiet btn--sm"
          :disabled="!answer.canRegenerate"
          :title="answer.canRegenerate ? '基于同一条提问重新生成' : '这条回答还没有保存，暂不能重新生成'"
          @click="emit('regenerate')"
        >
          <Icon name="refresh" :size="12" />
          重新生成
        </button>
        <button
          v-if="sources.length"
          type="button"
          class="btn btn--quiet btn--sm"
          @click="emit('open-sources')"
        >
          <Icon name="quote" :size="12" />
          {{ sources.length }} 条出处
        </button>
      </div>
      <div class="foot-meta mono">
        <span v-if="live && streaming" class="live-tag"><span class="live-dot" />生成中</span>
        <span v-else-if="elapsedLabel">{{ elapsedLabel }}</span>
        <span v-if="answer.tokenTotal" class="meta-usage">{{ formatNumber(answer.tokenTotal) }} tokens</span>
        <span v-if="sources.length">{{ sourceKindLabel(sources[0]) }}</span>
      </div>
    </div>
    <BaseSheet
      :open="saveOpen"
      title="保存为笔记"
      subtitle="正文按原始 Markdown 存下，之后可以继续编辑、下载。"
      eyebrow="笔记"
      :width="460"
      @update:open="saveOpen = $event"
    >
      <label class="save-field">
        <span class="save-label">标题</span>
        <input
          v-model="saveTitle"
          class="save-input"
          maxlength="200"
          autocomplete="off"
          @keydown.enter.prevent="confirmSave"
        />
      </label>
      <template #foot>
        <button type="button" class="btn btn--quiet btn--sm" @click="saveOpen = false">取消</button>
        <button type="button" class="btn btn--solid btn--sm" :disabled="saveBusy" @click="confirmSave">
          {{ saveBusy ? '保存中…' : '保存' }}
        </button>
      </template>
    </BaseSheet>
  </article>
</template>

<style scoped>
.answer {
  position: relative;
  min-width: 0;
}

.save-field {
  display: grid;
  gap: 8px;
}

.save-label {
  font-size: var(--text-xs);
  letter-spacing: 0.08em;
  color: var(--ink-4);
}

.save-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-sm);
  background: var(--surface);
  font-size: var(--text-base);
  color: var(--ink);
}

.save-input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: var(--focus-ring);
}

.reasoning {
  margin-bottom: 14px;
  border-left: 1px solid var(--line-strong);
  padding-left: 12px;
}

.reasoning-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-3);
  font-size: 11px;
  letter-spacing: 0.06em;
  padding: 2px 0;
}

.reasoning-toggle:hover {
  color: var(--ink);
}

.reasoning-label {
  letter-spacing: 0.14em;
}

.reasoning-count {
  color: var(--ink-4);
}

.reasoning-arrow {
  color: var(--ink-4);
}

.reasoning-body {
  margin-top: 6px;
  max-height: 280px;
  overflow-y: auto;
  font-size: var(--text-sm);
  line-height: 1.8;
  color: var(--ink-3);
  white-space: pre-wrap;
}

.thinking-lines {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 6px 0 2px;
}

.thinking-lines .line {
  display: block;
  height: 11px;
}

.w-90 {
  width: 90%;
}

.w-76 {
  width: 76%;
}

.w-84 {
  width: 84%;
}

.caret {
  display: inline-block;
  width: 7px;
  height: 1.05em;
  margin-left: 3px;
  vertical-align: -0.16em;
  background: var(--accent);
  animation: blink 1.1s steps(2, start) infinite;
}

@keyframes blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0;
  }
}

.run-error {
  margin-top: 12px;
  padding: 12px 14px;
  border: 1px solid color-mix(in srgb, var(--err) 30%, transparent);
  border-left: 2px solid var(--err);
  border-radius: 0 var(--r-sm) var(--r-sm) 0;
  background: var(--err-soft);
  font-size: var(--text-sm);
  color: var(--ink-2);
}

.error-mark {
  font-size: 11px;
  letter-spacing: 0.2em;
  color: var(--err);
}

.run-error p {
  margin-top: 5px;
}

.error-hint {
  color: var(--ink-3);
  font-size: var(--text-xs);
}

.error-retry {
  margin-top: 8px;
  color: var(--ink-2);
}

.run-note {
  margin-top: 10px;
  font-size: var(--text-xs);
  color: var(--warn);
}

.answer-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 14px;
  flex-wrap: wrap;
}

.foot-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-left: -8px;
}

.foot-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11px;
  color: var(--ink-4);
  letter-spacing: 0.05em;
}

.live-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--accent);
}

.live-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  animation: blink 1.4s ease-in-out infinite;
}
</style>
