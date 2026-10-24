<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { uploadImage } from '../../api/uploads'
import { useUiStore } from '../../stores/ui'
import { imageUrl } from '../../utils/history'
import Icon from '../ui/Icon.vue'

const props = defineProps({
  busy: { type: Boolean, default: false },
  sessionId: { type: String, default: '' },
  reasoning: { type: Boolean, default: false },
  placeholder: { type: String, default: '写下你的问题，或粘贴一张图片…' },
})

const emit = defineEmits(['send', 'stop', 'update:reasoning'])

const ui = useUiStore()

const text = ref('')
const textarea = ref(null)
const fileInput = ref(null)
const images = ref([])
const composing = ref(false)
const dragging = ref(false)
const focused = ref(false)

let imageSeed = 0
let draftTimer = null

const uploading = computed(() => images.value.some((item) => item.state === 'uploading'))
const readyImages = computed(() => images.value.filter((item) => item.state === 'done' && item.path))
const canSend = computed(() => !props.busy && !uploading.value && Boolean(text.value.trim() || readyImages.value.length))
const charCount = computed(() => text.value.length)

function draftKey(sessionId) {
  return `jxnu.draft.${sessionId || 'new'}`
}

function saveDraft() {
  if (draftTimer) window.clearTimeout(draftTimer)
  draftTimer = window.setTimeout(() => {
    try {
      const value = text.value
      if (value.trim()) localStorage.setItem(draftKey(props.sessionId), value)
      else localStorage.removeItem(draftKey(props.sessionId))
    } catch {
      /* noop */
    }
  }, 400)
}

function loadDraft(sessionId) {
  try {
    text.value = localStorage.getItem(draftKey(sessionId)) || ''
  } catch {
    text.value = ''
  }
  nextTick(resize)
}

watch(() => props.sessionId, (id, previous) => {
  if (previous === undefined) {
    loadDraft(id)
    return
  }
  loadDraft(id)
})

watch(text, saveDraft)

watch(
  () => props.reasoning,
  (value) => {
    try {
      localStorage.setItem('jxnu.reasoning', value ? '1' : '0')
    } catch {
      /* noop */
    }
  },
)

function resize() {
  const node = textarea.value
  if (!node) return
  node.style.height = 'auto'
  node.style.height = `${Math.min(node.scrollHeight, 220)}px`
}

function onInput() {
  resize()
}

function submit() {
  if (!canSend.value) return
  const payload = {
    text: text.value.trim(),
    images: readyImages.value.map((item) => item.path),
    reasoning: props.reasoning,
  }
  emit('send', payload)
  text.value = ''
  images.value = []
  nextTick(() => {
    resize()
    try {
      localStorage.removeItem(draftKey(props.sessionId))
    } catch {
      /* noop */
    }
  })
}

function onKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !composing.value && !event.isComposing) {
    event.preventDefault()
    submit()
  }
}

async function ingest(files) {
  const list = Array.from(files || []).filter((file) => file.type.startsWith('image/'))
  for (const file of list) {
    imageSeed += 1
    const entry = {
      id: `img-${imageSeed}`,
      name: file.name,
      preview: URL.createObjectURL(file),
      progress: 0,
      state: 'uploading',
      path: '',
      error: '',
    }
    images.value = [...images.value, entry]
    try {
      const result = await uploadImage(file, {
        onProgress: ({ ratio }) => {
          const target = images.value.find((item) => item.id === entry.id)
          if (target) target.progress = Math.round(ratio * 100)
        },
      })
      const target = images.value.find((item) => item.id === entry.id)
      if (target) {
        target.state = 'done'
        target.path = result?.path || ''
        target.url = result?.url || entry.preview
        target.progress = 100
      }
    } catch (error) {
      const target = images.value.find((item) => item.id === entry.id)
      if (target) {
        target.state = 'error'
        target.error = error?.message || '上传失败'
      }
      ui.notify(error?.message || '图片上传失败', 'err')
    }
  }
}

function pickFiles() {
  fileInput.value?.click()
}

function onFiles(event) {
  ingest(event.target.files)
  event.target.value = ''
}

function onPaste(event) {
  const items = event.clipboardData?.items || []
  const files = []
  for (const item of items) {
    if (item.kind === 'file') {
      const file = item.getAsFile()
      if (file) files.push(file)
    }
  }
  if (files.length) {
    event.preventDefault()
    ingest(files)
  }
}

function onDrop(event) {
  dragging.value = false
  ingest(event.dataTransfer?.files)
}

function removeImage(id) {
  const target = images.value.find((item) => item.id === id)
  if (target?.preview?.startsWith('blob:')) URL.revokeObjectURL(target.preview)
  images.value = images.value.filter((item) => item.id !== id)
}

function toggleReasoning() {
  emit('update:reasoning', !props.reasoning)
}

function setText(value) {
  text.value = value
  nextTick(() => {
    resize()
    textarea.value?.focus()
  })
}

onMounted(() => {
  loadDraft(props.sessionId)
  resize()
})

onBeforeUnmount(() => {
  if (draftTimer) window.clearTimeout(draftTimer)
  for (const item of images.value) {
    if (item.preview?.startsWith('blob:')) URL.revokeObjectURL(item.preview)
  }
})

defineExpose({
  setText,
  focus: () => textarea.value?.focus(),
  // 失败重试时把历史提问（含图片）放回书写台，等价旧版的「重新填写问题」。
  setImages(paths = []) {
    images.value = (paths || [])
      .map((path) => String(path || ''))
      .filter(Boolean)
      .map((path) => {
        imageSeed += 1
        const url = imageUrl(path)
        return {
          id: `restore-${imageSeed}`,
          name: path.split('/').pop() || '图片',
          preview: url,
          url,
          path,
          state: 'done',
          progress: 100,
        }
      })
  },
})
</script>

<template>
  <div
    class="composer"
    :class="{ 'is-focused': focused, 'is-dragging': dragging, 'is-busy': busy }"
    @dragover.prevent="dragging = true"
    @dragleave.prevent="dragging = false"
    @drop.prevent="onDrop"
  >
    <div class="composer-ticks" aria-hidden="true">
      <span /><span /><span /><span />
    </div>

    <div v-if="images.length" class="attach-strip">
      <figure v-for="item in images" :key="item.id" class="attach" :data-state="item.state">
        <img :src="item.preview" :alt="item.name" />
        <span v-if="item.state === 'uploading'" class="attach-progress mono">{{ item.progress }}%</span>
        <button type="button" class="attach-remove" aria-label="移除图片" @click="removeImage(item.id)">
          <Icon name="close" :size="11" />
        </button>
      </figure>
    </div>

    <label class="composer-field">
      <span class="sr-only">输入问题</span>
      <textarea
        ref="textarea"
        v-model="text"
        rows="1"
        :placeholder="placeholder"
        :disabled="busy"
        spellcheck="false"
        @input="onInput"
        @keydown="onKeydown"
        @compositionstart="composing = true"
        @compositionend="composing = false"
        @paste="onPaste"
        @focus="focused = true"
        @blur="focused = false"
      />
    </label>

    <div class="composer-foot">
      <div class="foot-left">
        <button
          type="button"
          class="tool"
          aria-label="添加图片"
          title="添加图片（≤10MB，jpg/png/gif/webp）"
          :disabled="busy"
          @click="pickFiles"
        >
          <Icon name="paperclip" :size="15" />
        </button>
        <input
          ref="fileInput"
          class="sr-only"
          type="file"
          accept="image/jpeg,image/png,image/gif,image/webp"
          multiple
          tabindex="-1"
          @change="onFiles"
        />
        <button
          type="button"
          class="tool toggle"
          :class="{ 'is-on': reasoning }"
          :aria-pressed="reasoning"
          title="让 Agent 在回答前多推演一步（qwen 的思考模式）"
          @click="toggleReasoning"
        >
          <span class="toggle-dot" />
          深度思考
        </button>
      </div>

      <div class="foot-right">
        <span v-if="charCount" class="count mono">{{ charCount }}</span>
        <span class="hint mono">⏎ 发送 · ⇧⏎ 换行</span>
        <button v-if="busy" type="button" class="send stop" aria-label="停止生成" @click="emit('stop')">
          <Icon name="stop" :size="13" fill />
        </button>
        <button
          v-else
          type="button"
          class="send"
          :disabled="!canSend"
          :aria-label="uploading ? '图片上传中' : '发送问题'"
          @click="submit"
        >
          <Icon name="arrowUp" :size="16" />
        </button>
      </div>
    </div>

    <p v-if="dragging" class="drop-hint mono">松手即可附上图片</p>
  </div>
</template>

<style scoped>
.composer {
  position: relative;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-md);
  background: var(--surface);
  box-shadow: var(--shadow-float);
  transition: border-color var(--t-base), box-shadow var(--t-base);
}

.composer.is-focused {
  border-color: var(--ink-3);
  box-shadow: 0 22px 60px -36px rgba(28, 24, 19, 0.55);
}

.composer.is-dragging {
  border-color: var(--accent);
}

.composer.is-busy {
  background: var(--surface-2);
}

.composer-ticks span {
  position: absolute;
  width: 7px;
  height: 7px;
  border-color: var(--ink-4);
  border-style: solid;
  pointer-events: none;
  opacity: 0.7;
}

.composer-ticks span:nth-child(1) {
  top: -4px;
  left: -4px;
  border-width: 1px 0 0 1px;
  opacity: 0.55;
}

.composer-ticks span:nth-child(2) {
  top: -4px;
  right: -4px;
  border-width: 1px 1px 0 0;
}

.composer-ticks span:nth-child(3) {
  bottom: -4px;
  left: -4px;
  border-width: 0 0 1px 1px;
}

.composer-ticks span:nth-child(4) {
  bottom: -4px;
  right: -4px;
  border-width: 0 1px 1px 0;
}

.attach-strip {
  display: flex;
  gap: 8px;
  padding: 12px 14px 0;
  flex-wrap: wrap;
}

.attach {
  position: relative;
  width: 54px;
  height: 54px;
  margin: 0;
  border-radius: var(--r-sm);
  overflow: hidden;
  border: 1px solid var(--line);
  background: var(--surface-2);
}

.attach img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.attach[data-state='uploading'] img {
  opacity: 0.45;
}

.attach[data-state='error'] {
  border-color: var(--err);
}

.attach-progress {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  font-size: 10px;
  color: var(--ink);
  background: color-mix(in srgb, var(--surface) 55%, transparent);
}

.attach-remove {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 16px;
  height: 16px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: color-mix(in srgb, var(--bg-deep) 82%, transparent);
  color: var(--ink);
}

.composer-field {
  display: block;
  padding: 4px 2px 0;
}

textarea {
  display: block;
  width: 100%;
  min-height: 52px;
  max-height: 220px;
  padding: 14px 18px 4px;
  border: 0;
  background: transparent;
  resize: none;
  outline: none;
  font-family: var(--font-serif);
  font-size: var(--text-md);
  line-height: 1.75;
  letter-spacing: 0.015em;
  color: var(--ink);
}

textarea::placeholder {
  color: var(--ink-4);
  font-family: var(--font-ui);
  font-size: var(--text-sm);
  letter-spacing: 0.02em;
}

.composer-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px 10px 8px 12px;
}

.foot-left,
.foot-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.tool {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 8px;
  border-radius: var(--r-sm);
  color: var(--ink-3);
  font-size: var(--text-xs);
  transition: color var(--t-fast), background var(--t-fast);
}

.tool:hover {
  color: var(--ink);
  background: var(--surface-2);
}

.tool:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.tool.toggle {
  letter-spacing: 0.06em;
}

.tool.toggle.is-on {
  color: var(--accent);
  background: var(--accent-soft);
}

.toggle-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  border: 1px solid currentColor;
  transition: background var(--t-fast);
}

.tool.toggle.is-on .toggle-dot {
  background: currentColor;
}

.count {
  font-size: var(--text-2xs);
  color: var(--ink-4);
}

.hint {
  font-size: var(--text-2xs);
  color: var(--ink-4);
  letter-spacing: 0.04em;
}

.send {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  margin-left: 2px;
  border-radius: 50%;
  background: var(--accent);
  color: var(--accent-ink);
  transition: transform var(--t-fast) var(--ease-out), background var(--t-fast), opacity var(--t-fast);
}

.send:hover:not(:disabled) {
  transform: translateY(-1px);
  background: var(--accent);
  color: var(--accent-ink);
}

.send:disabled {
  background: transparent;
  border: 1px solid var(--line-strong);
  color: var(--ink-4);
  cursor: not-allowed;
}

.send.stop {
  background: var(--accent);
  color: var(--accent-ink);
}

.drop-hint {
  position: absolute;
  inset: auto 0 8px;
  text-align: center;
  font-size: var(--text-2xs);
  color: var(--accent);
  letter-spacing: 0.1em;
  pointer-events: none;
}

@media (max-width: 640px) {
  .hint {
    display: none;
  }
}
</style>
