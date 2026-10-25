<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useConversationStore } from '../../stores/conversations'
import { useUiStore } from '../../stores/ui'
import { confirm } from '../../composables/confirm'
import { dateBucket, relativeTime, sessionTimestamp } from '../../utils/format'
import { sessionTitle } from '../../utils/history'
import Icon from '../ui/Icon.vue'

const props = defineProps({
  inline: { type: Boolean, default: false },
})
const ui = useUiStore()
const conversation = useConversationStore()
const router = useRouter()

const keyword = ref('')
const listRef = ref(null)
const cursor = ref(0)

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

watch(
  () => ui.ledgerOpen,
  async (open) => {
    if (!open) return
    cursor.value = 0
    if (conversation.sessionsStatus === 'idle') conversation.fetchSessions()
    await nextTick()
  },
)

watch(keyword, () => {
  cursor.value = 0
})

function openLedgerFor(session) {
  ui.openLedger(false)
  if (conversation.activeId === session.id) {
    ui.markVisited(session.id)
    return
  }
  router.push(`/inquiry/${session.id}`)
}

function startNew() {
  ui.openLedger(false)
  conversation.startNew()
  router.push('/inquiry')
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
  if (!ui.ledgerOpen) return
  const total = flatSessions.value.length
  if (!total) return
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    cursor.value = (cursor.value + 1) % total
    scrollToCursor()
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    cursor.value = (cursor.value - 1 + total) % total
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
}

watch(
  () => ui.ledgerOpen,
  (open) => {
    if (open) window.addEventListener('keydown', onKeydown)
    else window.removeEventListener('keydown', onKeydown)
  },
)

onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body" :disabled="props.inline">
    <Transition name="fade">
      <div v-if="!props.inline && ui.ledgerOpen" class="scrim" @click="ui.openLedger(false)" />
    </Transition>
    <Transition :name="props.inline ? 'inline' : 'sheet'">
      <aside
        v-if="props.inline || ui.ledgerOpen"
        id="session-ledger"
        class="ledger"
        :class="props.inline ? 'ledger--inline' : 'sheet'"
        :role="props.inline ? 'complementary' : 'dialog'"
        :aria-modal="props.inline ? undefined : 'true'"
        aria-label="会话档案"
      >
        <header class="ledger-head">
          <div>
            <p class="eyebrow">会话档案 · SESSIONS</p>
            <h2 class="serif">所有提问都在这里</h2>
          </div>
          <div class="ledger-actions">
            <button
              type="button"
              class="icon-btn"
              :class="{ 'is-on': props.inline }"
              :aria-pressed="props.inline"
              :title="props.inline ? '取消常驻' : '常驻为左侧栏'"
              :aria-label="props.inline ? '取消常驻会话档案' : '把会话档案常驻为左侧栏'"
              @click="ui.toggleLedgerPinned()"
            >
              <Icon name="pin" :size="15" />
            </button>
            <button
              v-if="!props.inline"
              type="button"
              class="icon-btn"
              aria-label="关闭会话档案"
              @click="ui.openLedger(false)"
            >
              <Icon name="close" :size="16" />
            </button>
          </div>
        </header>

        <div class="ledger-tools">
          <label class="search-box">
            <Icon name="search" :size="15" />
            <input
              v-model="keyword"
              type="search"
              placeholder="按标题搜索会话"
              aria-label="搜索会话"
              autocomplete="off"
            />
            <span v-if="filtered.length" class="mono result-count">{{ filtered.length }}</span>
          </label>
          <button type="button" class="btn btn--solid btn--sm" @click="startNew">
            <Icon name="plus" :size="13" />
            新会话
          </button>
        </div>

        <div ref="listRef" class="ledger-body">
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
                        <template v-if="session.status === 'running'"> · 生成中</template>
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
          <span class="mono">共 {{ conversation.sessions.length }} 条会话</span>
          <button type="button" class="theme-switch mono" @click="ui.toggleTheme()">
            <Icon :name="ui.isNight ? 'sun' : 'moon'" :size="12" />
            {{ ui.isNight ? '切换到纸本' : '切换到星夜' }}
          </button>
          <span class="mono hint">{{ props.inline ? '↑↓ 选择 · ⏎ 打开' : '↑↓ 选择 · ⏎ 打开 · esc 关闭' }}</span>
        </footer>
      </aside>
    </Transition>
  </Teleport>
</template>

<style scoped>
.ledger {
  width: min(440px, 100vw);
}

.ledger-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}

/* 常驻模式：成为 shell 的第二列，不再浮层化。 */
.ledger--inline {
  position: relative;
  inset: auto;
  width: 100%;
  height: 100%;
  max-height: none;
  border-radius: 0;
  border-right: 1px solid var(--line);
  background: var(--bg);
  box-shadow: none;
  display: flex;
  flex-direction: column;
}

.ledger--inline .ledger-head {
  padding: 22px 18px 14px;
}

.ledger--inline .ledger-head h2 {
  font-size: 18px;
}

.ledger-actions .icon-btn.is-on {
  color: var(--accent);
  background: var(--accent-soft);
}

.ledger--inline .ledger-tools {
  padding: 12px 18px;
}

.ledger--inline .ledger-body {
  flex: 1;
  min-height: 0;
}

.ledger--inline .ledger-foot {
  padding: 12px 18px;
}

.ledger-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 24px 24px 16px;
  border-bottom: 1px solid var(--line);
}

.ledger-head h2 {
  margin-top: 8px;
  font-size: var(--text-lg);
  font-weight: 500;
  letter-spacing: 0.05em;
}

.ledger-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 24px;
  border-bottom: 1px solid var(--line);
}

.ledger-tools .search-box {
  flex: 1;
}

.result-count {
  font-size: 11px;
  color: var(--ink-4);
}

.ledger-body {
  flex: 1;
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
  background: var(--surface-2);
}

.session-row.is-active {
  background: var(--accent-soft);
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
  .ledger-foot .hint {
    display: none;
  }

  .row-actions {
    opacity: 1;
  }
}
</style>
