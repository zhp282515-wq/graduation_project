<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { useMemoryStore } from '../stores/memory'
import { useConfirm } from '../composables/confirm'
import Icon from '../components/ui/Icon.vue'
import { formatStamp, relativeTime, truncate } from '../utils/format'

const memory = useMemoryStore()
const { confirm } = useConfirm()

const editor = ref(null)

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
      </div>
    </header>

    <div class="mem-scroll">
      <div class="mem-inner">
        <p class="mem-lede">
          每次回答结束后，Agent 会在后台把对话里值得记住的事写进这里；
          下一次提问，它们会作为你的上下文一起送进模型。你可以改写或删掉任何一条。
        </p>

        <div v-if="memory.status === 'loading' && !items.length" class="mem-grid">
          <div v-for="n in 4" :key="n" class="mem-card is-skeleton">
            <span class="skeleton bar" />
            <span class="skeleton bar short" />
          </div>
        </div>

        <div v-else-if="memory.status === 'error'" class="mem-state">
          <p class="mono state-tag">LOAD FAILED</p>
          <p class="state-text">{{ memory.error }}</p>
          <button type="button" class="btn ghost" @click="memory.fetchMemories()">重试</button>
        </div>

        <div v-else-if="!items.length" class="mem-state">
          <div class="mem-figure" aria-hidden="true">
            <span class="dash" />
            <Icon name="memory" :size="24" />
            <span class="dash" />
          </div>
          <h2 class="state-title">还没有记忆</h2>
          <p class="state-text">
            先问几个问题。回答完成后，后台抽取的记忆会出现在这里；如果暂时没有，
            可能是这一轮还没有值得长期保留的信息。
          </p>
          <RouterLink class="btn solid" :to="{ name: 'inquiry' }">
            <Icon name="inquiry" :size="13" />
            去问学
          </RouterLink>
        </div>

        <div v-else class="mem-grid">
          <article
            v-for="(item, index) in items"
            :key="item.id"
            class="mem-card"
            :class="{ 'is-editing': memory.editingId === item.id }"
          >
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
                aria-label="编辑记忆内容"
                @keydown="onEditorKeydown($event, item)"
              />
              <div class="mem-edit-foot">
                <span class="mono count">{{ memory.draft.length }} 字</span>
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
                <button type="button" class="link-btn mono" :disabled="editing && memory.editingId !== item.id" @click="startEdit(item)">
                  <Icon name="edit" :size="11" />
                  改写
                </button>
                <button
                  type="button"
                  class="link-btn mono danger"
                  :disabled="memory.removingId === item.id"
                  @click="removeItem(item)"
                >
                  <Icon name="trash" :size="11" />
                  删除
                </button>
                <span class="spacer" />
                <span class="mem-id mono" :title="`记忆编号 ${item.id}`">{{ String(index + 1).padStart(2, '0') }} / {{ memory.count }}</span>
              </div>
            </template>
          </article>
        </div>

        <p class="mem-note mono">
          记忆由后端在响应结束后异步抽取 · 删除后不可恢复 · 会话上下文按 context_revision 记录
        </p>
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
  /* 与问学同一套内容栅格：抬头与卡片都落在 --maxw + --gutter 里 */
  width: 100%;
  max-width: var(--maxw);
  margin-inline: auto;
  padding: 0 var(--gutter);
}

.memory-view > .view-head {
  padding: 22px 0 16px;
}

.head-title {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin: 2px 0 0;
  font-family: var(--font-serif);
  font-size: 17px;
  font-weight: 500;
  letter-spacing: 0.02em;
}

.head-count {
  font-size: 11px;
  letter-spacing: 0.08em;
  color: var(--ink-3);
}

.head-actions {
  display: flex;
  gap: 8px;
}

.mem-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 0 0 60px;
}

.mem-inner {
  max-width: none;
  margin: 0 auto;
}

.mem-lede {
  max-width: 62ch;
  margin: 8px 0 30px;
  font-size: var(--text-sm);
  line-height: 1.95;
  color: var(--ink-2);
  text-wrap: pretty;
}

.mem-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}

.mem-card {
  display: flex;
  flex-direction: column;
  padding: 16px 18px 14px;
  border: 1px solid var(--line);
  background: var(--surface);
  transition: border-color var(--t-base), transform var(--t-base);
}

.mem-card:hover {
  border-color: var(--line-strong);
  transform: translateY(-1px);
}

.mem-card.is-editing {
  border-color: var(--accent-line);
  transform: none;
}

.mem-card.is-skeleton {
  gap: 10px;
}

.mem-card.is-skeleton .bar {
  height: 11px;
  display: block;
}

.mem-card.is-skeleton .bar.short {
  width: 56%;
}

.mem-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.spacer {
  flex: 1;
}

.mem-no {
  font-size: 11px;
  letter-spacing: 0.1em;
  color: var(--accent);
}

.mem-cat {
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--ink-3);
  padding: 2px 6px;
  border: 1px solid var(--line);
  border-radius: 999px;
}

.mem-time {
  font-size: 11px;
  color: var(--ink-4);
}

.mem-content {
  margin: 12px 0 16px;
  font-size: var(--text-sm);
  line-height: 1.9;
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
  font-size: var(--text-sm);
  line-height: 1.8;
  resize: vertical;
  outline: none;
}

.mem-editor:focus {
  border-color: var(--ink-3);
}

.mem-edit-foot,
.mem-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}

.count {
  font-size: 11px;
  color: var(--ink-4);
  margin-right: auto;
}

.link-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--ink-3);
  transition: color var(--t-fast);
}

.link-btn:hover:not(:disabled) {
  color: var(--ink);
}

.link-btn.danger:hover:not(:disabled) {
  color: var(--err);
}

.link-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.mem-id {
  font-size: 11px;
  color: var(--ink-4);
  letter-spacing: 0.06em;
}

.mem-state {
  display: grid;
  justify-items: start;
  gap: 12px;
  max-width: 460px;
  padding: 26px 0;
}

.mem-figure {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--ink-3);
  width: 100%;
}

.dash {
  flex: 1;
  height: 1px;
  background: var(--line-strong);
  max-width: 64px;
}

.state-tag {
  margin: 0;
  font-size: 11px;
  letter-spacing: 0.2em;
  color: var(--accent);
}

.state-title {
  margin: 0;
  font-family: var(--font-serif);
  font-size: 24px;
  font-weight: 400;
  letter-spacing: 0.04em;
}

.state-text {
  margin: 0;
  font-size: var(--text-xs);
  line-height: 1.9;
  color: var(--ink-3);
}

.mem-note {
  margin: 34px 0 0;
  padding-top: 14px;
  border-top: 1px solid var(--line);
  font-size: 11px;
  letter-spacing: 0.08em;
  color: var(--ink-4);
}

@media (max-width: 640px) {
  .mem-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
