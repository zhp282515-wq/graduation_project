<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { useMemoryStore } from '../stores/memory'
import { useConfirm } from '../composables/confirm'
import Icon from '../components/ui/Icon.vue'
import { formatStamp, relativeTime, truncate } from '../utils/format'

const memory = useMemoryStore()
const { confirm } = useConfirm()

const editor = ref(null)
const composer = ref(null)
const composeOpen = ref(false)
const composeText = ref('')
const MEMORY_LIMIT = 200

const items = computed(() => memory.items || [])
const editing = computed(() => Boolean(memory.editingId))

/** v-for 里的 ref 会收集成数组，聚焦时按当前编辑项取节点。 */
function editorNode() {
  const value = editor.value
  if (Array.isArray(value)) return value.filter(Boolean).at(-1) || null
  return value || null
}

async function startEdit(item) {
  memory.beginEdit(item)
  await nextTick()
  const node = editorNode()
  node?.focus()
  if (node?.setSelectionRange) node.setSelectionRange(node.value.length, node.value.length)
}

function cancel() {
  memory.cancelEdit()
}

async function saveItem(item) {
  await memory.save(item)
}

async function openCompose() {
  composeOpen.value = true
  await nextTick()
  composer.value?.focus()
}

function cancelCompose() {
  composeOpen.value = false
  composeText.value = ''
}

async function submitCompose() {
  if (memory.creating || !composeText.value.trim()) return
  const ok = await memory.create(composeText.value)
  if (ok) cancelCompose()
}

function onComposeKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    cancelCompose()
  }
  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
    event.preventDefault()
    submitCompose()
  }
}

async function removeItem(item) {
  const ok = await confirm({
    title: '删除这条长期记忆？',
    message: `「${truncate(item.content, 60)}」会从记忆库里永久移除，之后的对话不再带上它。`,
    confirmText: '删除',
    tone: 'danger',
  })
  if (!ok) return
  await memory.remove(item)
}

function onEditorKeydown(event, item) {
  if (event.key === 'Escape') {
    event.preventDefault()
    cancel()
  }
  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
    event.preventDefault()
    saveItem(item)
  }
}

onMounted(() => {
  memory.fetchMemories()
})
</script>

<template>
  <div class="memory-view">
    <header class="view-head">
      <div class="head-main">
        <p class="eyebrow">记忆 <span class="slash">/</span> MEMORY</p>
        <h1 class="head-title">
          长期记忆
          <span class="head-count mono">{{ memory.count }} 条</span>
        </h1>
      </div>
      <div class="head-actions">
        <button type="button" class="btn ghost" :disabled="memory.status === 'loading'" @click="memory.fetchMemories()">
          <Icon name="refresh" :size="13" />
          刷新
        </button>
        <button type="button" class="btn solid" :disabled="composeOpen" @click="openCompose">
          <Icon name="plus" :size="13" />
          添加记忆
        </button>
      </div>
    </header>

    <div class="mem-scroll">
      <p class="mem-lede">每次回答结束后，Agent 会把值得长期保留的信息写进这里，之后的提问会带上它们。</p>

      <div v-if="composeOpen" class="mem-compose">
        <textarea
          ref="composer"
          v-model="composeText"
          class="mem-editor"
          rows="3"
          :maxlength="MEMORY_LIMIT"
          placeholder="写一条希望它一直记得的事，例如：我是计算机学院 2022 级的学生。"
          aria-label="新记忆内容"
          @keydown="onComposeKeydown"
        />
        <div class="mem-edit-foot">
          <span class="mono count" :class="{ over: composeText.length > MEMORY_LIMIT }">
            {{ composeText.length }} / {{ MEMORY_LIMIT }} 字
          </span>
          <button type="button" class="btn ghost sm" :disabled="memory.creating" @click="cancelCompose">
            取消
          </button>
          <button
            type="button"
            class="btn solid sm"
            :disabled="memory.creating || !composeText.trim()"
            @click="submitCompose"
          >
            {{ memory.creating ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>

      <div v-if="memory.status === 'loading' && !items.length" class="mem-grid">
        <div v-for="n in 4" :key="n" class="mem-card is-skeleton">
          <span class="skeleton bar" />
          <span class="skeleton bar short" />
        </div>
      </div>

      <div v-else-if="memory.status === 'error'" class="mem-state state-block">
        <p class="state-title">记忆加载失败</p>
        <p class="state-text">{{ memory.error }}</p>
        <button type="button" class="link-btn" @click="memory.fetchMemories()">重试</button>
      </div>

      <div v-else-if="!items.length" class="mem-state state-block">
        <Icon class="mem-mark" name="memory" :size="22" />
        <p class="state-title">还没有记忆</p>
        <p class="state-text">先问几个问题。回答完成后，值得长期保留的信息会出现在这里。</p>
        <div class="state-actions">
          <RouterLink class="btn solid" :to="{ name: 'inquiry' }">
            <Icon name="inquiry" :size="13" />
            去问学
          </RouterLink>
          <button type="button" class="btn ghost" @click="openCompose">
            <Icon name="plus" :size="13" />
            手动写一条
          </button>
        </div>
      </div>

      <div v-else class="mem-grid">
        <article v-for="(item, index) in items" :key="item.id" class="mem-card">
          <header class="mem-head">
            <span class="mem-no mono">{{ String(index + 1).padStart(2, '0') }}</span>
            <span class="mem-cat mono">{{ item.category || 'fact' }}</span>
            <span class="spacer" />
            <span class="mem-time mono" :title="formatStamp(item.updated_at || item.created_at)">
              {{ relativeTime(item.updated_at || item.created_at) }}
            </span>
          </header>

          <template v-if="memory.editingId === item.id">
            <textarea
              ref="editor"
              v-model="memory.draft"
              class="mem-editor"
              rows="4"
              :maxlength="MEMORY_LIMIT"
              aria-label="编辑记忆内容"
              @keydown="onEditorKeydown($event, item)"
            />
            <div class="mem-edit-foot">
              <span class="mono count">{{ memory.draft.length }} / {{ MEMORY_LIMIT }} 字</span>
              <button type="button" class="btn ghost sm" :disabled="memory.savingId === item.id" @click="cancel">
                取消
              </button>
              <button
                type="button"
                class="btn solid sm"
                :disabled="memory.savingId === item.id || !memory.draft.trim()"
                @click="saveItem(item)"
              >
                {{ memory.savingId === item.id ? '保存中…' : '保存' }}
              </button>
            </div>
          </template>

          <template v-else>
            <p class="mem-content">{{ item.content }}</p>
            <div class="mem-foot">
              <button type="button" class="link-btn" :disabled="editing && memory.editingId !== item.id" @click="startEdit(item)">
                <Icon name="edit" :size="11" />
                改写
              </button>
              <button
                type="button"
                class="link-btn danger"
                :disabled="memory.removingId === item.id"
                @click="removeItem(item)"
              >
                <Icon name="trash" :size="11" />
                删除
              </button>
            </div>
          </template>
        </article>
      </div>
    </div>
  </div>
</template>

<style scoped>
.memory-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  /* 与问学同一套内容栅格：抬头与记忆列表都落在 --maxw + --gutter 里 */
  width: 100%;
  max-width: var(--maxw);
  margin-inline: auto;
  padding: 0 var(--gutter);
}

.memory-view > .view-head {
  padding: 22px 0 16px;
}

/* 标题字号由全局 .head-title 决定，这里只负责标题与计数的基线对齐。 */
.head-title {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 12px;
  margin: 2px 0 0;
}

.head-count {
  font-size: var(--text-xs);
  letter-spacing: 0.08em;
  color: var(--ink-3);
}

.mem-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 0 0 56px;
}

.mem-lede {
  max-width: 62ch;
  margin: 22px 0 26px;
  font-size: var(--text-sm);
  line-height: 1.9;
  color: var(--ink-3);
  text-wrap: pretty;
}

/* 记忆是散文化内容，限制阅读宽度，避免长行横穿整个工作区。 */
.mem-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  max-width: var(--reading-w);
}

.mem-card {
  display: flex;
  flex-direction: column;
  padding: 20px 0;
  border-bottom: 1px solid var(--line);
}

.mem-card:last-child {
  border-bottom: 0;
}

/* 手动添加：与记忆条目同宽，只多一圈强调边，写完即回到列表 */
.mem-compose {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: var(--reading-w);
  margin: 0 0 8px;
  padding: 16px 18px;
  border: 1px solid color-mix(in srgb, var(--accent) 22%, var(--line));
  border-radius: var(--r-md);
  background: var(--surface);
}

.mem-compose .mem-editor {
  min-height: 76px;
  border: 0;
  background: transparent;
  padding: 0;
}

.mem-compose .mem-editor:focus {
  outline: none;
}

.mem-compose .count.over {
  color: var(--err);
}

.state-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.mem-card.is-skeleton {
  gap: 10px;
}

.mem-card.is-skeleton .bar {
  display: block;
  height: 11px;
}

.mem-card.is-skeleton .bar.short {
  width: 56%;
}

.mem-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mem-no {
  font-size: var(--text-xs);
  letter-spacing: 0.1em;
  color: var(--accent);
}

.mem-cat {
  padding: 1px 7px;
  border: 1px solid var(--line);
  border-radius: var(--r-full);
  font-size: var(--text-xs);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ink-3);
}

.mem-time {
  font-size: var(--text-xs);
  color: var(--ink-4);
}

.mem-content {
  margin: 12px 0 10px;
  font-size: var(--text-base);
  line-height: 1.85;
  color: var(--ink);
  white-space: pre-wrap;
  word-break: break-word;
}

.mem-editor {
  margin: 12px 0 10px;
  padding: 10px 12px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-sm);
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font-ui);
  font-size: var(--text-base);
  line-height: 1.8;
  resize: vertical;
  outline: none;
  transition: border-color var(--t-fast) var(--ease-out);
}

.mem-editor:focus {
  border-color: var(--accent);
}

.mem-foot {
  display: flex;
  align-items: center;
  gap: 18px;
}

.mem-edit-foot {
  display: flex;
  align-items: center;
  gap: 18px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}

.count {
  margin-right: auto;
  font-size: var(--text-xs);
  color: var(--ink-4);
}

.link-btn.danger:hover:not(:disabled) {
  color: var(--err);
}

.link-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.mem-mark {
  color: var(--ink-4);
}

.mem-state {
  gap: 12px;
  padding-top: 8px;
}
</style>
