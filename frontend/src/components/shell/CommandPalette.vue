<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useConversationStore } from '../../stores/conversations'
import { useLibraryStore } from '../../stores/library'
import { useUiStore } from '../../stores/ui'
import { relativeTime, sessionTimestamp } from '../../utils/format'
import { sessionTitle } from '../../utils/history'
import { CAMPUS_LINKS } from '../../config/campusLinks'
import Icon from '../ui/Icon.vue'

const ui = useUiStore()
const conversation = useConversationStore()
const library = useLibraryStore()
const router = useRouter()

const keyword = ref('')
const cursor = ref(0)
const inputRef = ref(null)

const staticCommands = computed(() => [
  {
    id: 'new-session',
    group: '动作',
    label: '开始一段新的问学',
    hint: '清空当前对话，进入扉页',
    icon: 'plus',
    run: () => {
      conversation.startNew()
      router.push('/inquiry')
    },
  },
  {
    id: 'go-atlas',
    group: '空间',
    label: '去星野看知识分片',
    hint: '四 · ATLAS',
    icon: 'atlas',
    run: () => router.push('/atlas'),
  },
  {
    id: 'go-archive',
    group: '空间',
    label: '打开典藏',
    hint: '二 · ARCHIVE',
    icon: 'archive',
    run: () => router.push('/archive'),
  },
  {
    id: 'go-memory',
    group: '空间',
    label: '查看长期记忆',
    hint: '三 · MEMORY',
    icon: 'memory',
    run: () => router.push('/memory'),
  },
  {
    id: 'toggle-theme',
    group: '动作',
    label: ui.theme === 'night' ? '切换到纸本' : '切换到星夜',
    hint: '外观',
    icon: ui.theme === 'night' ? 'sun' : 'moon',
    run: () => ui.toggleTheme(),
  },
  {
    id: 'sync-kb',
    group: '知识库',
    label: '同步上传目录',
    hint: '扫描并补齐文档登记',
    icon: 'sync',
    run: async () => {
      router.push('/archive')
      await library.runSync()
    },
  },
  ...CAMPUS_LINKS.map((link) => ({
    id: `campus-${link.id}`,
    group: '校园入口',
    label: link.label,
    hint: link.title,
    icon: 'external',
    run: () => window.open(link.href, '_blank', 'noopener,noreferrer'),
  })),
])

const commands = computed(() => {
  const needle = keyword.value.trim().toLowerCase()
  const list = staticCommands.value.filter((item) =>
    !needle || `${item.label} ${item.hint} ${item.group}`.toLowerCase().includes(needle),
  )
  const sessions = conversation.sortedSessions
    .filter((session) => !needle || sessionTitle(session).toLowerCase().includes(needle))
    .slice(0, 6)
    .map((session) => ({
      id: `session-${session.id}`,
      group: '最近会话',
      label: sessionTitle(session),
      hint: relativeTime(sessionTimestamp(session)),
      icon: 'message',
      run: () => {
        router.push(`/inquiry/${session.id}`)
      },
    }))
  return [...list.slice(0, 4), ...sessions, ...list.slice(4)]
})

watch(
  () => ui.paletteOpen,
  async (open) => {
    if (!open) return
    keyword.value = ''
    cursor.value = 0
    if (!conversation.sessions.length) conversation.fetchSessions({ silent: true })
    await nextTick()
    inputRef.value?.focus()
  },
)

watch(keyword, () => {
  cursor.value = 0
})

function close() {
  ui.openPalette(false)
}

function runItem(item) {
  if (!item) return
  close()
  item.run()
}

function onKeydown(event) {
  if (!ui.paletteOpen) return
  const total = commands.value.length
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
  } else if (event.key === 'ArrowDown' && total) {
    event.preventDefault()
    cursor.value = (cursor.value + 1) % total
  } else if (event.key === 'ArrowUp' && total) {
    event.preventDefault()
    cursor.value = (cursor.value - 1 + total)
  } else if (event.key === 'Enter') {
    event.preventDefault()
    runItem(commands.value[cursor.value])
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="ui.paletteOpen" class="palette-layer" @click.self="close">
        <div
          class="palette"
          role="dialog"
          aria-modal="true"
          aria-label="命令面板"
          @keydown="onKeydown"
        >
          <div class="palette-input">
            <Icon name="search" :size="16" />
            <input
              ref="inputRef"
              v-model="keyword"
              type="text"
              placeholder="搜索会话、切换空间、执行动作…"
              aria-label="命令与搜索"
              autocomplete="off"
              spellcheck="false"
            />
            <span class="kbd">esc</span>
          </div>

          <ul v-if="commands.length" class="palette-list">
            <li v-for="(item, index) in commands" :key="item.id">
              <button
                type="button"
                class="palette-item"
                :class="{ 'is-cursor': index === cursor }"
                @click="runItem(item)"
                @mouseenter="cursor = index"
              >
                <Icon :name="item.icon" :size="15" class="item-icon" />
                <span class="item-main">
                  <span class="item-label">{{ item.label }}</span>
                  <span class="item-hint mono">{{ item.group }} · {{ item.hint }}</span>
                </span>
                <Icon v-if="index === cursor" name="arrowRight" :size="14" class="item-arrow" />
              </button>
            </li>
          </ul>
          <p v-else class="palette-empty">没有匹配的命令或会话。</p>

          <footer class="palette-foot mono">
            <span>↑↓ 移动</span>
            <span>⏎ 执行</span>
            <span>esc 关闭</span>
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.palette-layer {
  position: fixed;
  inset: 0;
  z-index: var(--z-sheet);
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: min(14vh, 140px) 18px 18px;
  background: color-mix(in srgb, var(--bg-deep) 58%, transparent);
  backdrop-filter: blur(5px);
}

.palette {
  width: min(620px, 100%);
  border: 1px solid var(--line-strong);
  border-radius: var(--r-md);
  background: var(--surface);
  box-shadow: var(--shadow-sheet);
  overflow: hidden;
}

.palette-input {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 15px 18px;
  border-bottom: 1px solid var(--line);
  color: var(--ink-3);
}

.palette-input input {
  flex: 1;
  min-width: 0;
  border: 0;
  background: transparent;
  outline: none;
  font-size: var(--text-md);
  color: var(--ink);
}

.palette-input input::placeholder {
  color: var(--ink-4);
}

.palette-list {
  list-style: none;
  margin: 0;
  padding: 6px;
  max-height: min(52vh, 420px);
  overflow-y: auto;
}

.palette-item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 10px 12px;
  border-radius: var(--r-sm);
  text-align: left;
  color: var(--ink-2);
  transition: background var(--t-fast), color var(--t-fast);
}

.palette-item.is-cursor {
  background: var(--accent-soft);
  color: var(--ink);
}

.item-icon {
  color: var(--ink-3);
}

.palette-item.is-cursor .item-icon {
  color: var(--accent);
}

.item-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.item-label {
  font-size: var(--text-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-hint {
  font-size: var(--text-2xs);
  color: var(--ink-4);
  letter-spacing: 0.04em;
}

.item-arrow {
  color: var(--accent);
}

.palette-empty {
  padding: 26px 18px;
  font-size: var(--text-sm);
  color: var(--ink-3);
  text-align: center;
}

.palette-foot {
  display: flex;
  gap: 16px;
  padding: 10px 18px;
  border-top: 1px solid var(--line);
  background: var(--surface-2);
  font-size: var(--text-2xs);
  letter-spacing: 0.08em;
  color: var(--ink-4);
}

@media (max-width: 640px) {
  .palette-layer {
    padding: 8vh 12px 12px;
  }
}
</style>
