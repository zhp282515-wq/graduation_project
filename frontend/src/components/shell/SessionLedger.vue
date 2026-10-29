<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useConversationStore } from '../../stores/conversations'
import { useNotesStore } from '../../stores/notes'
import { useUiStore } from '../../stores/ui'
import { confirm } from '../../composables/confirm'
import { dateBucket, relativeTime, sessionTimestamp } from '../../utils/format'
import { sessionTitle } from '../../utils/history'
import Icon from '../ui/Icon.vue'

const props = defineProps({ inline: { type: Boolean, default: false } })
const ui = useUiStore()
const conversation = useConversationStore()
const notes = useNotesStore()
const route = useRoute()
const router = useRouter()

const tab = ref('sessions')
const keyword = ref('')
const renamingId = ref('')
const renameDraft = ref('')
const listRef = ref(null)
const searchRef = ref(null)
const ledgerRef = ref(null)
const cursor = ref(-1)
let previousFocus = null

const filtered = computed(() => {
  const needle = keyword.value.trim().toLowerCase()
  const list = conversation.sortedSessions
  if (!needle) return list
  return list.filter((session) => sessionTitle(session).toLowerCase().includes(needle))
})

const groups = computed(() => {
  const order = ['今天', '昨天', '本周', '更早']
  const buckets = new Map(order.map((key) => [key, []]))
  for (const session of filtered.value) {
    const bucket = dateBucket(sessionTimestamp(session))
    if (!buckets.has(bucket)) buckets.set(bucket, [])
    buckets.get(bucket).push(session)
  }
  return order
    .filter((key) => buckets.get(key)?.length)
    .map((key) => ({ key, items: buckets.get(key) }))
})

const flatSessions = computed(() => groups.value.flatMap((group) => group.items))

const filteredNotes = computed(() => {
  const needle = keyword.value.trim().toLowerCase()
  const list = notes.sorted
  if (!needle) return list
  return list.filter((note) => {
    const title = (note.title || '').toLowerCase()
    return title.includes(needle) || (note.content || '').toLowerCase().includes(needle)
  })
})

const activeNoteId = computed(() => String(route.params.noteId || ''))
const searchHint = computed(() => (tab.value === 'notes' ? '搜索笔记标题或正文' : '按标题搜索会话'))

watch(
  () => route.name,
  (name) => {
    if (name === 'notes') tab.value = 'notes'
  },
  { immediate: true },
)

watch(tab, (next) => {
  keyword.value = ''
  cursor.value = -1
  if (next === 'notes' && notes.status === 'idle') notes.fetchNotes()
})

watch(
  () => ui.ledgerOpen,
  async (open) => {
    if (props.inline) return
    if (!open) {
      previousFocus?.focus?.()
      previousFocus = null
      return
    }
    previousFocus = document.activeElement
    cursor.value = -1
    if (conversation.sessionsStatus === 'idle') conversation.fetchSessions()
    await nextTick()
    searchRef.value?.focus()
  },
)

watch(keyword, () => {
  cursor.value = -1
})

function openLedgerFor(session) {
  if (!props.inline) ui.openLedger(false)
  if (conversation.activeId === session.id) {
    ui.markVisited(session.id)
    return
  }
  router.push(`/inquiry/${session.id}`)
}

function openNote(note) {
  if (!props.inline) ui.openLedger(false)
  router.push(`/notes/${note.id}`)
}

function startRename(note) {
  renamingId.value = note.id
  renameDraft.value = note.title
  nextTick(() => {
    const input = ledgerRef.value?.querySelector('.rename-input')
    input?.focus()
    input?.select()
  })
}

async function commitRename(note) {
  if (renamingId.value !== note.id) return
  const title = renameDraft.value.trim()
  renamingId.value = ''
  if (!title || title === note.title) return
  try {
    await notes.rename(note.id, title)
  } catch (err) {
    ui.notify(err?.message || '重命名失败', 'error')
  }
}

async function removeNote(note) {
  const ok = await confirm({
    title: `删除「${note.title}」？`,
    body: '这条笔记会从账号里永久删除，下载过的 .md 文件不受影响。',
    confirmText: '删除笔记',
    danger: true,
  })
  if (!ok) return
  await notes.remove(note.id)
  if (activeNoteId.value === note.id) {
    const next = notes.sorted[0]
    router.replace(next ? `/notes/${next.id}` : '/notes')
  }
}

function startNew() {
  if (!props.inline) ui.openLedger(false)
  conversation.startNew()
  router.push('/inquiry')
}

async function collapse() {
  ui.ledgerExpanded = false
  await nextTick()
  document.querySelector('#ledger-toggle')?.focus()
}

async function remove(session) {
  const ok = await confirm({
    title: `删除「${sessionTitle(session)}」？`,
    body: '这一条会话的提问与回答会一并删除，且无法恢复。知识库文档与长期记忆不受影响。',
    confirmText: '删除会话',
    danger: true,
  })
  if (!ok) return
  const removed = await conversation.remove(session.id)
  if (removed && router.currentRoute.value.name === 'inquiry' && router.currentRoute.value.params.sessionId === session.id) {
    router.push('/inquiry')
  }
}

function onKeydown(event) {
  if ((!props.inline && !ui.ledgerOpen) || event.defaultPrevented) return
  if (!props.inline && event.key === 'Tab' && ledgerRef.value?.contains(document.activeElement)) {
    const controls = [...ledgerRef.value.querySelectorAll('button:not(:disabled), input:not(:disabled), [tabindex="0"]')]
    if (controls.length && event.shiftKey && document.activeElement === controls[0]) {
      event.preventDefault()
      controls[controls.length - 1].focus()
    } else if (controls.length && !event.shiftKey && document.activeElement === controls[controls.length - 1]) {
      event.preventDefault()
      controls[0].focus()
    }
    return
  }
  if (event.target.closest?.('input, textarea, select, button, [contenteditable="true"]')) return
  if (props.inline && !listRef.value?.contains(event.target)) return
  if (tab.value !== 'sessions') return
  const total = flatSessions.value.length
  if (!total) return
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    cursor.value = (cursor.value + 1) % total
    scrollToCursor()
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    cursor.value = cursor.value <= 0 ? total - 1 : cursor.value - 1
    scrollToCursor()
  } else if (event.key === 'Enter') {
    event.preventDefault()
    const target = flatSessions.value[cursor.value]
    if (target) openLedgerFor(target)
  }
}

async function scrollToCursor() {
  await nextTick()
  const node = listRef.value?.querySelector('[data-cursor="true"]')
  node?.scrollIntoView({ block: 'nearest' })
  node?.focus({ preventScroll: true })
}

watch(
  () => props.inline || ui.ledgerOpen,
  (open) => {
    if (open) window.addEventListener('keydown', onKeydown)
    else window.removeEventListener('keydown', onKeydown)
  },
  { immediate: true },
)

onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body" :disabled="props.inline">
    <Transition name="fade">
      <div v-if="!props.inline && ui.ledgerOpen" class="scrim" @click="ui.openLedger(false)" />
    </Transition>
    <Transition name="ledger-slide">
      <aside
        ref="ledgerRef"
        v-if="props.inline || ui.ledgerOpen"
        id="session-ledger"
        class="ledger"
        :class="{ 'ledger--inline': props.inline }"
        :role="props.inline ? 'complementary' : 'dialog'"
        :aria-modal="props.inline ? undefined : 'true'"
        aria-label="会话档案"
      >
        <div class="ledger-tools">
          <div class="ledger-tabs" role="tablist" aria-label="档案类型">
            <button
              type="button"
              role="tab"
              class="ledger-tab"
              :class="{ 'is-on': tab === 'sessions' }"
              :aria-selected="tab === 'sessions'"
              @click="tab = 'sessions'"
            >
              会话
            </button>
            <button
              type="button"
              role="tab"
              class="ledger-tab"
              :class="{ 'is-on': tab === 'notes' }"
              :aria-selected="tab === 'notes'"
              @click="tab = 'notes'"
            >
              笔记
              <span v-if="notes.sorted.length" class="mono tab-count">{{ notes.sorted.length }}</span>
            </button>
          </div>
          <div class="ledger-tools-head">
            <label class="search-box">
              <Icon name="search" :size="15" />
              <input
                ref="searchRef"
                v-model="keyword"
                type="search"
                :placeholder="searchHint"
                :aria-label="searchHint"
                autocomplete="off"
              />
              <span v-if="tab === 'sessions' && filtered.length" class="mono result-count">{{ filtered.length }}</span>
              <span v-else-if="tab === 'notes' && filteredNotes.length" class="mono result-count">{{ filteredNotes.length }}</span>
            </label>
            <button
              type="button"
              class="icon-btn ledger-collapse"
              :aria-label="props.inline ? '折叠会话栏' : '关闭会话档案'"
              :title="props.inline ? '折叠会话栏' : '关闭会话档案'"
              @click="props.inline ? collapse() : ui.openLedger(false)"
            >
              <Icon :name="props.inline ? 'chevronLeft' : 'close'" :size="16" />
            </button>
          </div>
          <button v-if="tab === 'sessions'" type="button" class="btn btn--solid btn--sm ledger-new" @click="startNew">
            <Icon name="plus" :size="13" />
            新会话
          </button>
        </div>

        <div v-if="tab === 'notes'" ref="listRef" class="ledger-body">
          <p v-if="notes.status === 'loading' && !notes.sorted.length" class="ledger-hint mono">正在读取笔记…</p>
          <div v-else-if="notes.status === 'error'" class="empty">
            <p class="empty-title">笔记取不回来</p>
            <p class="empty-body">{{ notes.error }}</p>
            <button type="button" class="btn btn--sm" @click="notes.fetchNotes()">重试</button>
          </div>
          <div v-else-if="!filteredNotes.length" class="empty">
            <p class="empty-title">{{ keyword ? '没有匹配的笔记' : '还没有笔记' }}</p>
            <p class="empty-body">
              {{ keyword ? '换一个关键词，或清空搜索。' : '在回答下方点「保存为笔记」，就会收进这里。' }}
            </p>
            <button v-if="keyword" type="button" class="btn btn--sm" @click="keyword = ''">清空搜索</button>
          </div>
          <ul v-else class="session-list">
            <li v-for="note in filteredNotes" :key="note.id">
              <div v-if="renamingId === note.id" class="session-row note-row is-renaming">
                <input
                  v-model="renameDraft"
                  class="rename-input"
                  aria-label="重命名笔记"
                  @keydown.enter.prevent="commitRename(note)"
                  @keydown.esc.prevent="renamingId = ''"
                  @blur="commitRename(note)"
                />
              </div>
              <div
                v-else
                class="session-row note-row"
                :class="{ 'is-active': note.id === activeNoteId }"
                role="button"
                tabindex="0"
                @click="openNote(note)"
                @keydown.enter.prevent="openNote(note)"
              >
                <span class="row-main">
                  <span class="row-title">{{ note.title }}</span>
                  <span class="row-meta mono">{{ relativeTime(note.updated_at) }}</span>
                </span>
                <span class="row-actions">
                  <button type="button" class="icon-btn icon-btn--sm" aria-label="重命名" title="重命名" @click.stop="startRename(note)">
                    <Icon name="edit" :size="13" />
                  </button>
                  <button type="button" class="icon-btn icon-btn--sm" aria-label="删除笔记" title="删除笔记" @click.stop="removeNote(note)">
                    <Icon name="trash" :size="13" />
                  </button>
                </span>
              </div>
            </li>
          </ul>
        </div>

        <div v-else ref="listRef" class="ledger-body" @pointermove="cursor = -1">
          <p v-if="conversation.sessionsStatus === 'loading'" class="ledger-hint mono">正在读取档案…</p>
          <div v-else-if="conversation.sessionsStatus === 'error'" class="empty">
            <p class="empty-title">档案柜打不开</p>
            <p class="empty-body">{{ conversation.sessionsError }}</p>
            <button type="button" class="btn btn--sm" @click="conversation.fetchSessions()">重试</button>
          </div>
          <div v-else-if="!filtered.length" class="empty">
            <p class="empty-title">{{ keyword ? '没有匹配的会话' : '还没有任何会话' }}</p>
            <p class="empty-body">
              {{ keyword ? '换一个关键词，或清空搜索查看全部档案。' : '问学里的第一次提问会自动建立一个会话。' }}
            </p>
            <button v-if="keyword" type="button" class="btn btn--sm" @click="keyword = ''">清空搜索</button>
          </div>

          <template v-else>
            <section v-for="group in groups" :key="group.key" class="ledger-group">
              <p class="group-label mono">{{ group.key }}</p>
              <ul class="session-list">
                <li v-for="session in group.items" :key="session.id">
                  <div
                    class="session-row"
                    :class="{ 'is-active': session.id === conversation.activeId }"
                    :data-cursor="flatSessions[cursor]?.id === session.id"
                    role="button"
                    tabindex="0"
                    @click="openLedgerFor(session)"
                    @keydown.enter.prevent="openLedgerFor(session)"
                  >
                    <span class="row-mark" aria-hidden="true">
                      <span v-if="conversation.isRunning(session.id)" class="running-dot" />
                      <span v-else-if="ui.isUnread(session)" class="unread-dot" />
                    </span>
                    <span class="row-main">
                      <span class="row-title">{{ sessionTitle(session) }}</span>
                      <span class="row-meta mono">
                        <template v-if="conversation.isRunning(session.id)">正在生成 · </template>
                        {{ relativeTime(sessionTimestamp(session)) }}

                      </span>
                    </span>
                    <span class="row-actions">
                      <button
                        type="button"
                        class="icon-btn icon-btn--sm"
                        aria-label="删除会话"
                        @click.stop="remove(session)"
                      >
                        <Icon name="trash" :size="13" />
                      </button>
                      <Icon name="chevronRight" :size="14" class="row-arrow" />
                    </span>
                  </div>
                </li>
              </ul>
            </section>
          </template>
        </div>

        <footer class="ledger-foot">
          <span v-if="tab === 'notes'" class="mono">共 {{ notes.sorted.length }} 条笔记</span>
          <span v-else class="mono">共 {{ conversation.sessions.length }} 条会话</span>
          <span v-if="tab === 'notes'" class="mono hint">⏎ 打开 · 双击标题重命名</span>
          <span v-else class="mono hint">{{ props.inline ? '↑↓ 选择 · ⏎ 打开' : '↑↓ 选择 · ⏎ 打开 · esc 关闭' }}</span>
        </footer>
      </aside>
    </Transition>
  </Teleport>
</template>

<style scoped>
.ledger {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: var(--z-sheet);
  width: min(440px, calc(100vw - 32px));
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border-right: 1px solid var(--line-strong);
  box-shadow: 8px 0 32px rgb(0 0 0 / 0.14);
}

.ledger--inline {
  position: relative;
  inset: auto;
  width: 312px;
  min-width: 0;
  height: 100%;
  background: var(--surface);
  box-shadow: none;
  transition: opacity 240ms var(--ease-out), transform 320ms var(--ease-out);
}

:global(.ledger-slot.is-collapsed) .ledger--inline {
  opacity: 0;
  transform: translateX(-12px);
}

.ledger--inline .ledger-tabs {
  display: flex;
  gap: 2px;
  margin-bottom: 10px;
  padding: 2px;
  border-radius: var(--r-sm);
  background: var(--surface-2);
}

.ledger-tab {
  flex: 1 1 0;
  padding: 6px 10px;
  border-radius: calc(var(--r-sm) - 2px);
  font-size: var(--text-sm);
  color: var(--ink-3);
  transition: background var(--t-fast) var(--ease-out), color var(--t-fast) var(--ease-out);
}

.ledger-tab:hover {
  color: var(--ink);
}

.ledger-tab.is-on {
  background: var(--surface);
  color: var(--ink);
  box-shadow: var(--shadow-soft, 0 1px 2px rgb(0 0 0 / 0.05));
}

.tab-count {
  margin-left: 4px;
  font-size: 10px;
  color: var(--ink-4);
}

.note-row {
  align-items: center;
}

.rename-input {
  width: 100%;
  padding: 2px 0;
  border: 0;
  border-bottom: 1px solid var(--accent);
  background: none;
  font-size: var(--text-base);
  color: var(--ink);
}

.rename-input:focus {
  outline: none;
}

.ledger-tools { padding: 18px 18px 12px; }
.ledger--inline .ledger-foot { padding: 12px 18px; }
.ledger--inline .ledger-foot .hint { display: none; }

.ledger-slide-enter-active,
.ledger-slide-leave-active {
  transition: transform var(--t-slow) var(--ease-out), opacity var(--t-base) var(--ease-out);
}

.ledger-slide-enter-from,
.ledger-slide-leave-to {
  transform: translateX(-24px);
  opacity: 0;
}

.ledger-tools {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
  padding: 18px 24px 14px;
  border-bottom: 1px solid var(--line);
}

.ledger-tools-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ledger-new {
  justify-content: center;
}

.ledger-collapse {
  flex: 0 0 auto;
  color: var(--ink-4);
}

.ledger-collapse:hover {
  color: var(--ink);
}

.ledger-tools-head .search-box {
  flex: 1;
  min-width: 0;
}

.result-count {
  font-size: 11px;
  color: var(--ink-4);
}

.ledger-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 6px 14px 24px;
  overscroll-behavior: contain;
}

.ledger-hint {
  padding: 24px 12px;
  font-size: var(--text-xs);
  color: var(--ink-3);
}

.ledger-group {
  margin-top: 14px;
}

.group-label {
  padding: 6px 10px;
  font-size: 11px;
  letter-spacing: 0.2em;
  color: var(--ink-4);
}

.session-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 10px 10px 6px;
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: background var(--t-fast);
}

.session-row:hover,
.session-row[data-cursor='true'] {
  background: var(--accent-soft);
}

.session-row.is-active {
  background: var(--accent-soft);
}

.session-row.is-active .row-title {
  color: var(--ink);
  font-weight: 500;
}

.session-row.is-active::before {
  content: "";
  position: absolute;
  left: 0;
  top: 50%;
  width: 2px;
  height: 16px;
  border-radius: var(--r-full);
  background: var(--accent);
  transform: translateY(-50%);
}

.row-mark {
  width: 8px;
  display: grid;
  place-items: center;
  flex: none;
}

.unread-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--accent);
}

.running-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--ok);
  box-shadow: 0 0 0 0 color-mix(in srgb, var(--ok) 45%, transparent);
  animation: run-pulse 1.8s var(--ease-out) infinite;
}

@keyframes run-pulse {
  0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--ok) 40%, transparent); }
  70% { box-shadow: 0 0 0 5px transparent; }
  100% { box-shadow: 0 0 0 0 transparent; }
}

.row-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.row-title {
  font-family: var(--font-serif);
  font-size: 13.5px;
  letter-spacing: 0.02em;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-meta {
  font-size: 11px;
  color: var(--ink-3);
  letter-spacing: 0.04em;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transition: opacity var(--t-fast);
}

.session-row:hover .row-actions,
.session-row:focus-within .row-actions,
.session-row[data-cursor='true'] .row-actions {
  opacity: 1;
}

.row-arrow {
  color: var(--ink-4);
}

.ledger-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 24px 16px;
  border-top: 1px solid var(--line);
  font-size: 11px;
  color: var(--ink-3);
  letter-spacing: 0.06em;
}

.theme-switch {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  margin-left: auto;
  border: 1px solid var(--line);
  border-radius: 999px;
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--ink-3);
  background: transparent;
  transition: color var(--t-fast), border-color var(--t-fast);
}

.theme-switch:hover {
  color: var(--ink);
  border-color: var(--line-strong);
}

.ledger-foot .hint {
  color: var(--ink-4);
}

@media (max-width: 640px) {
  .ledger-foot {
    padding-bottom: max(16px, env(safe-area-inset-bottom));
  }

  .ledger-foot .hint {
    display: none;
  }

  .row-actions {
    opacity: 1;
  }
}
@media (prefers-reduced-motion: reduce) {
  .ledger-slide-enter-active, .ledger-slide-leave-active, .ledger--inline { transition: none; }
}
</style>
