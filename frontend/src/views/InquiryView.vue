<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useConversationStore } from '../stores/conversations'
import { useLibraryStore } from '../stores/library'
import { useUiStore } from '../stores/ui'
import Composer from '../components/chat/Composer.vue'
import TurnItem from '../components/chat/TurnItem.vue'
import SourceSheet from '../components/chat/SourceSheet.vue'
import Icon from '../components/ui/Icon.vue'
import { CAMPUS_LINKS } from '../config/campusLinks'
import { shortDocTitle } from '../utils/format'
import sealUrl from '../assets/school-seal.svg'

const route = useRoute()
const router = useRouter()
const ui = useUiStore()
const conversations = useConversationStore()
const library = useLibraryStore()

const scroller = ref(null)
const composer = ref(null)
const nearBottom = ref(true)
const showJump = ref(false)

const sheetOpen = ref(false)
const sheetSources = ref([])
const sheetInitial = ref('')

const reasoning = ref(false)

const turns = computed(() => conversations.turns)
const busy = computed(() => conversations.busy)
const live = computed(() => conversations.run)
const title = computed(() => conversations.activeSession?.title || '新的会话')
const isEmpty = computed(() => !turns.value.length && conversations.historyStatus !== 'loading')

const docs = computed(() => (library.items || []).filter((doc) => Number(doc.chunk_count) > 0))

const quickAsks = [
  '图书馆几点开门？周末开放吗？',
  '帮我查一下这周南昌的天气',
  '学生证丢了怎么补办？',
  '期末考试安排一般在哪里公布？',
]

function scrollToBottom(behavior = 'smooth') {
  const node = scroller.value
  if (!node) return
  node.scrollTo({ top: node.scrollHeight, behavior })
}

function onScroll() {
  const node = scroller.value
  if (!node) return
  const gap = node.scrollHeight - node.scrollTop - node.clientHeight
  nearBottom.value = gap < 96
  showJump.value = gap > 320
}

function follow(behavior = 'smooth') {
  if (!nearBottom.value) return
  nextTick(() => scrollToBottom(behavior))
}

async function syncRoute() {
  const id = route.params.sessionId ? String(route.params.sessionId) : null
  if (id === conversations.activeId) return
  if (id) await conversations.openSession(id)
  else conversations.startNew()
  nextTick(() => scrollToBottom('auto'))
}

watch(() => route.params.sessionId, syncRoute)

watch(
  () => conversations.activeId,
  (id) => {
    const current = route.params.sessionId ? String(route.params.sessionId) : null
    if (id && id !== current) router.replace({ name: 'inquiry', params: { sessionId: id } })
  },
)

watch(
  () => turns.value.length,
  () => {
    nearBottom.value = true
    nextTick(() => scrollToBottom('smooth'))
  },
)

watch(
  () => [live.value.text, live.value.reasoning, live.value.steps.length, live.value.phase],
  () => follow(),
)

watch(
  () => conversations.historyStatus,
  (status) => {
    if (status === 'ready') {
      nearBottom.value = true
      nextTick(() => scrollToBottom('auto'))
    }
  },
)

function handleSend(payload) {
  nearBottom.value = true
  conversations.send({ ...payload, reasoning: payload.reasoning ? true : null })
}

function handleStop() {
  conversations.stop()
}

function handleRegenerate(turnKey) {
  conversations.regenerate(turnKey)
}

function expandLedger() {
  if (!ui.ledgerWide) {
    ui.openLedger(!ui.ledgerOpen)
    return
  }
  const previousFocus = document.activeElement
  ui.ledgerExpanded = true
  nextTick(() => window.setTimeout(() => {
    if (ui.ledgerWide && ui.ledgerExpanded && route.name === 'inquiry' &&
        (document.activeElement === previousFocus || document.activeElement === document.body)) {
      document.querySelector('#session-ledger button[aria-label="折叠会话栏"]')?.focus()
    }
  }, 340))
}

/** 失败后把这一轮的问题与图片放回书写台，等价旧版的「重新填写问题」。 */
function handleRefill(turn) {
  if (!turn) return
  composer.value?.setText(turn.userText || '')
  if (turn.images?.length) composer.value?.setImages(turn.images)
  ui.notify('问题已放回书写台，确认后可重新发送', 'ok')
}

function openSource(source) {
  if (!source) return
  sheetSources.value = [source]
  sheetInitial.value = source.id || ''
  sheetOpen.value = true
}

function openSources(list) {
  if (!list?.length) return
  sheetSources.value = list
  sheetInitial.value = list[0]?.id || ''
  sheetOpen.value = true
}

// normalizeSources 输出的是 camelCase（fileMd5/chunkIndex/chunkId），这里同时兼容原始 snake_case。
function locateSource(source) {
  sheetOpen.value = false
  const md5 = source?.fileMd5 || source?.file_md5 || ''
  if (!md5) {
    ui.notify('这条出处没有关联文档指纹，无法在星图中定位', 'warn')
    return
  }
  const rawIndex = source.chunkIndex ?? source.chunk_index
  const index = Number.isFinite(Number(rawIndex)) ? Number(rawIndex) : 0
  const chunkId = source.chunkId || source.chunk_id || ''
  router.push({
    name: 'atlas',
    query: {
      focus: `${md5}:${index}`,
      ...(chunkId ? { chunk: String(chunkId) } : {}),
    },
  })
}

function openArchive(source) {
  sheetOpen.value = false
  const md5 = source?.fileMd5 || source?.file_md5 || ''
  if (!md5) {
    ui.notify('这条出处没有关联文档指纹，无法打开所属文档', 'warn')
    return
  }
  const rawIndex = source.chunkIndex ?? source.chunk_index
  router.push({
    name: 'archive',
    params: { fileMd5: md5 },
    query: Number.isFinite(Number(rawIndex)) ? { chunk: String(rawIndex) } : {},
  })
}

function askFromSource(source) {
  sheetOpen.value = false
  const title = shortDocTitle(source?.title || source?.file_name || '这段材料')
  composer.value?.setText(`关于「${title}」，请结合知识库里的原文说明：`)
}

function usePrompt(prompt) {
  composer.value?.setText(prompt)
}

function retryHistory() {
  if (conversations.activeId) conversations.loadHistory(conversations.activeId)
}

let lastSeed = ''
function consumeSeed() {
  const seed = route.query.seed ? String(route.query.seed) : ''
  if (!seed || seed === lastSeed) return
  lastSeed = seed
  nextTick(() => {
    composer.value?.setText(seed)
    router.replace({ query: {} })
  })
}

watch(() => route.query.seed, consumeSeed)

onMounted(() => {
  try {
    reasoning.value = localStorage.getItem('jxnu.reasoning') === '1'
  } catch {
    reasoning.value = false
  }
  if (conversations.sessionsStatus === 'idle') conversations.fetchSessions({ silent: true })
  if (library.status === 'idle') library.fetchDocuments({ silent: true })
  syncRoute()
  consumeSeed()
})

onBeforeUnmount(() => {
  /* 生成流不在这里中断：切换视图再回来仍应看到进行中的回答 */
})
</script>

<template>
  <div class="inquiry">
    <header class="view-head inquiry-head">
      <div class="head-brand">
        <button
          v-if="!ui.ledgerWide || !ui.ledgerExpanded"
          id="ledger-toggle"
          type="button"
          class="icon-btn ledger-toggle"
          :aria-expanded="ui.ledgerWide ? ui.ledgerExpanded : ui.ledgerOpen"
          aria-controls="session-ledger"
          aria-label="展开会话栏"
          title="展开会话栏"
          @click="expandLedger"
        >
          <Icon name="panelLeft" :size="18" />
        </button>
        <img class="head-seal" :src="sealUrl" alt="江西师范大学校徽" width="72" height="60" />
        <div class="head-main">
          <p class="eyebrow">问学 <span class="slash">/</span> INQUIRY</p>
          <h1 class="head-title">{{ title }}</h1>
        </div>
      </div>
    </header>

    <div ref="scroller" class="thread-scroll" @scroll.passive="onScroll">
      <div v-if="isEmpty" class="hero hero-empty">
        <div class="hero-center">
          <h2 class="hero-title">今天，问点什么？</h2>

          <div class="hero-quick">
            <button
              v-for="prompt in quickAsks"
              :key="prompt"
              type="button"
              class="hero-quick-item"
              @click="usePrompt(prompt)"
            >
              {{ prompt }}
            </button>
          </div>

          <p class="hero-campus">
            <span class="hero-campus-label">校园入口</span>
            <a
              v-for="link in CAMPUS_LINKS"
              :key="link.id"
              :href="link.href"
              :title="link.title"
              target="_blank"
              rel="noopener noreferrer"
            >
              {{ link.label }}
            </a>
          </p>
        </div>
      </div>

      <div v-else class="thread">
        <div class="thread-inner">
          <div v-if="conversations.historyStatus === 'loading'" class="history-skeleton">
            <span class="skeleton bar" />
            <span class="skeleton bar short" />
            <span class="skeleton block" />
          </div>

          <div v-else-if="conversations.historyStatus === 'error'" class="history-error">
            <p class="mono">历史消息没有读到</p>
            <p class="history-error-text">{{ conversations.historyError }}</p>
            <button type="button" class="btn ghost" @click="retryHistory">
              <Icon name="refresh" :size="13" />
              重试
            </button>
          </div>

          <TurnItem
            v-for="turn in turns"
            :key="turn.key"
            :turn="turn"
            :index="turn.index"
            :is-current="turn.key === live.targetKey"
            :run="live"
            @regenerate="handleRegenerate"
            @refill="handleRefill"
            @open-source="openSource"
            @open-sources="openSources"
          />
        </div>
      </div>

      <div class="thread-pad" />
    </div>

    <button v-if="showJump" type="button" class="jump mono" @click="scrollToBottom()">
      <Icon name="chevronDown" :size="12" />
      回到最新
    </button>

    <div class="dock">
      <div class="dock-inner">
        <Composer
          ref="composer"
          :busy="busy"
          :session-id="conversations.activeId || ''"
          :reasoning="reasoning"
          @send="handleSend"
          @stop="handleStop"
          @update:reasoning="reasoning = $event"
        />
        <p class="dock-note mono">
          Agent 会调用真实工具检索知识库；出处可点开核对原文
          <span class="dot-sep">·</span>
          会话与记忆保存在本地服务
        </p>
      </div>
    </div>

    <SourceSheet
      :open="sheetOpen"
      :sources="sheetSources"
      :initial-id="sheetInitial"
      @update:open="sheetOpen = $event"
      @locate="locateSource"
      @archive="openArchive"
      @ask="askFromSource"
    />
  </div>
</template>

<style scoped>
.inquiry {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  /* 走栏 92 + 栏间 26：对话列与书写台共用同一组中线参数。 */
  --thread-gutter: 92px;
  --thread-gap: 26px;
}

/* 抬头直接挂在 .inquiry 下，不像其他页面有 .view-inner 包裹，这里补回同样的安全边距。 */
.inquiry-head {
  flex: 0 0 auto;
  align-items: center;
  width: 100%;
  max-width: var(--maxw);
  margin-inline: auto;
  padding: 18px var(--gutter) 14px;
}

.head-brand {
  display: flex;
  align-items: center;
  gap: 18px;
  min-width: 0;
}

.ledger-toggle { flex: none; min-width: 36px; min-height: 36px; }

.head-seal {
  flex: none;
  width: 72px;
  height: auto;
}

:global([data-theme='night'] .head-seal) {
  filter: brightness(1.8);
}

.head-main {
  min-width: 0;
}

.head-title {
  margin: 2px 0 0;
  font-family: var(--font-serif);
  font-size: 17px;
  font-weight: 500;
  letter-spacing: 0.02em;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 44vw;
}

.thread-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  /* 两侧都预留滚动条槽位，对话栏中线才能和下方书写台完全重合。 */
  scrollbar-gutter: stable both-edges;
}

.thread {
  padding: 18px clamp(20px, 4vw, 64px) 0;
}

.thread-inner {
  /* 左侧是 92px 走栏 + 26px 间距，右侧留同样宽度，阅读列才真正落在页面中线上。 */
  max-width: calc(var(--reading-w) + (var(--thread-gutter) + var(--thread-gap)) * 2);
  margin: 0 auto;
}

.thread-pad {
  height: 32px;
}

.hero {
  max-width: var(--maxw);
  margin: 0 auto;
  padding: clamp(18px, 3vh, 30px) var(--gutter) 8px;
  animation: fade-up 620ms var(--ease-out) both;
}

.hero-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 28px;
}

.hero-mark {
  display: flex;
  align-items: baseline;
  flex: 1;
  min-width: 0;
  gap: 14px;
  color: var(--ink-3);
  font-size: 11px;
  letter-spacing: 0.12em;
}

.hero-name {
  flex: 0 0 auto;
  font-family: var(--font-serif);
  font-size: 16px;
  letter-spacing: 0.12em;
  color: var(--ink);
}

.hero-role {
  flex: 0 0 auto;
  font-size: 11px;
  letter-spacing: 0.14em;
  color: var(--ink-3);
}

.hero-mark .hair {
  flex: 1;
  height: 1px;
  margin-bottom: 3px;
  background: var(--line);
}

.hero-title {
  display: flex;
  align-items: baseline;
  gap: 22px;
  flex-wrap: wrap;
  margin: 12px 0 0;
  font-weight: 400;
}

.hero-cn {
  font-family: var(--font-serif);
  font-size: clamp(54px, 6.2vw, 78px);
  line-height: 0.98;
  letter-spacing: 0.02em;
  color: var(--ink);
}

.hero-latin {
  font-family: var(--font-display);
  font-style: italic;
  font-size: clamp(18px, 2vw, 24px);
  color: var(--ink-3);
  letter-spacing: 0.01em;
}

.hero-lede {
  max-width: 520px;
  margin: 14px 0 0;
  font-size: 13.5px;
  line-height: 1.85;
  color: var(--ink-2);
  text-wrap: pretty;
}

.hero-rule {
  display: flex;
  align-items: center;
  gap: 14px;
  margin: 22px 0 0;
  color: var(--ink-3);
  font-size: 11px;
  letter-spacing: 0.14em;
}

.rule-line {
  flex: 1;
  height: 1px;
  background: var(--line);
}

.suggest-block,
.quick-block {
  margin-top: 24px;
}

.block-label {
  margin: 0 0 10px;
  font-size: 11px;
  letter-spacing: 0.16em;
  color: var(--ink-3);
}

.suggest-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border-radius: var(--r-md);
  background: var(--line);
  border: 1px solid var(--line);
}

.suggest {
  position: relative;
  display: grid;
  gap: 5px;
  padding: 13px 14px 14px;
  text-align: left;
  background: var(--surface);
  transition: background var(--t-base), transform var(--t-base);
}

.suggest:hover {
  background: var(--surface-2);
  transform: translateY(-1px);
}

.suggest-type {
  font-size: 11px;
  letter-spacing: 0.18em;
  color: var(--accent);
}

.suggest-title {
  font-family: var(--font-serif);
  font-size: 15.5px;
  letter-spacing: 0.01em;
  color: var(--ink);
}

.suggest-prompt {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  padding-right: 20px;
  font-size: var(--text-xs);
  line-height: 1.65;
  color: var(--ink-3);
}

.suggest-arrow {
  position: absolute;
  right: 14px;
  top: 15px;
  color: var(--ink-4);
  transform: rotate(45deg);
  transition: transform var(--t-base) var(--ease-out), color var(--t-fast);
}

.suggest:hover .suggest-arrow {
  color: var(--accent);
  transform: rotate(45deg) translateX(2px);
}

.quick-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.quick {
  padding: 7px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-xs);
  font-size: var(--text-xs);
  color: var(--ink-2);
  background: transparent;
  transition: color var(--t-fast), border-color var(--t-fast), background var(--t-fast);
}

.quick:hover {
  color: var(--ink);
  border-color: var(--ink-3);
  background: var(--surface);
}

.hero-spread {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(250px, 296px);
  gap: clamp(28px, 3.4vw, 52px);
  align-items: start;
}

.hero-title { margin-top:24px; }
.hero-cn { font-size:clamp(58px,6.8vw,86px); }
.hero-lede { max-width:48ch; font-size:15px; line-height:1.9; }
.hero-side { background:var(--surface-2); border-radius:12px; }
.campus-grid { border:0; }
.campus-link { padding-inline:0; }
.campus-link:hover { background:transparent; }
.quick { font-size:13px; }
.hero-side .quick { font-size:13px; }

.hero-main {
  min-width: 0;
}

.hero-side {
  display: flex;
  flex-direction: column;
  gap: 26px;
  padding: 22px;
}

.hero-side .hero-rule {
  margin-top: 0;
}

.campus-block {
  margin-top: 0;
}

.campus-block .hero-rule {
  margin-bottom: 10px;
}

.campus-grid {
  display: flex;
  flex-direction: column;
  border: 0;
}

.campus-link {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-bottom: 1px solid var(--line);
  color: var(--ink-2);
  text-decoration: none;
  transition: background var(--t-fast), color var(--t-fast);
}

.campus-link:last-child {
  border-bottom: 0;
}

.campus-link:hover {
  background: var(--surface);
  color: var(--ink);
}

.campus-index {
  font-size: 11px;
  letter-spacing: 0.1em;
  color: var(--ink-4);
}

.campus-body {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.campus-label {
  font-family: var(--font-serif);
  font-size: 13.5px;
  letter-spacing: 0.02em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.campus-hint {
  display: none;
}

.campus-arrow {
  margin-left: auto;
  color: var(--ink-4);
  transition: transform var(--t-fast), color var(--t-fast);
}

.campus-link:hover .campus-arrow {
  color: var(--accent);
  transform: translate(1px, -1px);
}

.hero-side .quick-list {
  flex-direction: column;
  align-items: stretch;
  gap: 0;
}

.hero-side .quick {
  padding: 8px 0;
  border: 0;
  border-radius: 0;
  text-align: left;
  background: transparent;
  font-size: var(--text-xs);
  color: var(--ink-2);
  transition: color var(--t-fast), padding-left var(--t-base) var(--ease-out);
}

.hero-side .quick:hover {
  padding-left: 6px;
  color: var(--accent);
  background: transparent;
}

.hero-links {
  display: flex;
  flex-wrap: wrap;
  gap: 22px;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
}

.hero-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-xs);
  color: var(--ink-2);
  text-decoration: none;
  transition: color var(--t-fast), gap var(--t-base);
}

.hero-link:hover {
  color: var(--accent);
  gap: 11px;
}

.history-skeleton {
  display: grid;
  gap: 12px;
  padding: 40px 0;
}

.history-skeleton .bar {
  height: 12px;
  width: 62%;
}

.history-skeleton .bar.short {
  width: 40%;
}

.history-skeleton .block {
  height: 120px;
}

.history-error {
  display: grid;
  gap: 10px;
  justify-items: start;
  padding: 44px 0;
  color: var(--ink-2);
}

.history-error .mono {
  font-size: 11px;
  letter-spacing: 0.14em;
  color: var(--accent);
}

.history-error-text {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--ink-2);
}

.jump {
  position: absolute;
  left: 50%;
  bottom: 154px;
  transform: translateX(-50%);
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-xs);
  background: var(--surface);
  box-shadow: var(--shadow-soft);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 11px;
  letter-spacing: 0.08em;
  box-shadow: var(--shadow-float);
  z-index: 5;
}

.jump:hover {
  color: var(--ink);
  border-color: var(--ink-3);
}

.dock {
  flex: 0 0 auto;
  padding: 6px clamp(20px, 4vw, 64px) 16px;
  background: linear-gradient(to bottom, transparent, var(--bg) 26%);
}

.dock-inner {
  /* 与 .turn-col 同宽同轴：宽度 = --reading-w，水平居中。 */
  max-width: var(--reading-w);
  margin: 0 auto;
}

.dock-note {
  margin: 9px 0 0;
  text-align: center;
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--ink-4);
}

.dot-sep {
  margin: 0 6px;
}

@media (max-width: 1080px) {
  .head-title {
    max-width: 52vw;
  }
}

@media (max-width: 1180px) {
  .thread-inner {
    max-width: var(--reading-w);
  }

  .campus-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .campus-hint {
    display: none;
  }
}

@media (max-width: 1080px) {
  .head-title {
    max-width: 52vw;
  }
}

@media (max-width: 980px) {
  .hero-spread {
    grid-template-columns: minmax(0, 1fr);
    gap: 30px;
  }

  .hero-side {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 26px;
    padding-top: 0;
  }
}

@media (max-width: 900px) {
  .hero {
    padding-top: 26px;
  }

  .suggest-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .hero-side {
    grid-template-columns: minmax(0, 1fr);
  }

  .campus-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .jump {
    bottom: 150px;
  }
}

@media (max-width: 640px) {
  .hero-head {
    align-items: flex-start;
    gap: 14px;
  }

  .hero-name {
    font-size: 14px;
    letter-spacing: 0.08em;
  }

  .hero-role {
    display: none;
  }

  .head-brand {
    gap: 14px;
  }

  .head-seal {
    width: 60px;
  }

  .campus-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .campus-link {
    padding: 11px 12px;
  }
  .hero-cn {
    font-size: 64px;
  }

  .hero-latin {
    font-size: 18px;
  }

  .dock {
    padding: 4px 12px 12px;
  }

  .dock-note {
    display: none;
  }

  .head-title {
    max-width: 46vw;
    font-size: 15px;
  }

  .hero-side { padding:18px; }
}

/* ------------------------------------------------------------
   空态 v2：一列提问 + 一列辅助入口。
   去掉三层品牌、英文副标与重复的星野/典藏入口，细线只留两处。
   ------------------------------------------------------------ */

.head-title {
  font-size: clamp(19px, 2vw, 23px);
}

.hero {
  padding-top: clamp(26px, 4.4vh, 46px);
}

.hero-spread {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(232px, 292px);
  gap: clamp(30px, 4.4vw, 72px);
  align-items: start;
}

.hero-main {
  max-width: var(--reading-w);
}

.hero .hero-title {
  margin: 0;
  font-family: var(--font-serif);
  font-size: clamp(32px, 4.2vw, 50px);
  font-weight: 500;
  letter-spacing: -0.012em;
  line-height: 1.26;
}

.hero .hero-lede {
  margin: 18px 0 0;
  max-width: 44ch;
  color: var(--ink-2);
  font-size: var(--text-md);
  line-height: 1.95;
}

.hero-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 16px 0 0;
  color: var(--ink-3);
  font-size: var(--text-xs);
  letter-spacing: 0.06em;
}

.hero-meta .dot {
  opacity: 0.45;
}

.hero .block-label {
  margin: 0 0 12px;
  font-family: var(--font-ui);
  font-size: var(--text-xs);
  letter-spacing: 0.08em;
  color: var(--ink-3);
}

.hero .suggest-block {
  margin-top: clamp(26px, 4vh, 40px);
}

.hero .suggest-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  border: 0;
}

.hero .suggest {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 15px 16px 17px;
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  background: var(--surface);
  text-align: left;
  box-shadow: none;
  transition: border-color var(--t-fast) var(--ease-out),
    transform var(--t-base) var(--ease-out), box-shadow var(--t-base) var(--ease-out);
}

.hero .suggest:hover {
  border-color: var(--line-strong);
  background: var(--surface);
  transform: translateY(-2px);
  box-shadow: var(--shadow-card);
}

.hero .suggest:active {
  transform: translateY(0);
  transition-duration: 90ms;
}

.suggest-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.hero .suggest-type {
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--ink-3);
}

.hero .suggest-arrow {
  position: static;
  color: var(--ink-4);
  opacity: 0.6;
  transform: rotate(45deg);
  transition: opacity var(--t-fast), transform var(--t-base) var(--ease-out);
}

.hero .suggest:hover .suggest-arrow {
  opacity: 1;
  transform: rotate(45deg) translate(1px, -1px);
}

.hero .suggest-title {
  font-size: var(--text-base);
  line-height: 1.5;
  color: var(--ink);
}

.hero .suggest-prompt {
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--ink-3);
}

.hero .hero-side {
  display: flex;
  flex-direction: column;
  gap: clamp(22px, 3.2vh, 32px);
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.hero .side-block + .side-block {
  padding-top: clamp(20px, 2.8vh, 28px);
  border-top: 1px solid var(--line);
}

.hero .campus-list {
  display: flex;
  flex-direction: column;
  border: 0;
}

.hero .campus-link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  font-size: var(--text-sm);
  color: var(--ink-2);
  text-decoration: none;
  transition: color var(--t-fast) var(--ease-out);
}

.hero .campus-link + .campus-link {
  border-top: 1px solid color-mix(in srgb, var(--line) 62%, transparent);
}

.hero .campus-link:hover {
  background: transparent;
  color: var(--ink);
}

.hero .campus-arrow {
  opacity: 0.34;
  transition: opacity var(--t-fast), transform var(--t-base) var(--ease-out);
}

.hero .campus-link:hover .campus-arrow {
  opacity: 1;
  transform: translate(1px, -1px);
}

.hero .quick-list {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.hero .quick {
  padding: 9px 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  text-align: left;
  font-size: var(--text-sm);
  color: var(--ink-2);
  transition: color var(--t-fast) var(--ease-out), transform var(--t-base) var(--ease-out);
}

.hero .quick:hover {
  padding-left: 0;
  transform: translateX(3px);
  background: transparent;
  color: var(--ink);
}

@media (max-width: 980px) {
  .hero-spread {
    grid-template-columns: minmax(0, 1fr);
    gap: 34px;
  }

  .hero .hero-side {
    gap: 22px;
  }
}

@media (max-width: 640px) {
  .hero .suggest-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (prefers-reduced-motion: reduce) {
  .hero .suggest,
  .hero .quick,
  .hero .campus-arrow { transition: none; }
}

/* ------------------------------------------------------------
   空态 v3：居中一列，去掉推荐卡片与右侧栏。
   ------------------------------------------------------------ */
.thread-scroll {
  display: flex;
  flex-direction: column;
}

.thread {
  flex: 0 0 auto;
}

.hero.hero-empty {
  flex: 1 1 auto;
  display: grid;
  place-items: center;
  max-width: none;
  margin: 0;
  padding: clamp(30px, 8vh, 96px) var(--gutter) clamp(24px, 6vh, 64px);
}

.hero-center {
  display: grid;
  justify-items: center;
  gap: 18px;
  width: 100%;
  max-width: 620px;
  margin: 0 auto;
  text-align: center;
}

.hero-center .hero-title {
  margin: 0;
  font-family: var(--font-serif);
  font-size: clamp(34px, 4.4vw, 52px);
  font-weight: 500;
  line-height: 1.22;
  letter-spacing: 0.02em;
}

.hero-quick {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 6px 20px;
  max-width: 430px;
  margin-top: 10px;
}

.hero-quick-item {
  font-size: var(--text-sm);
  color: var(--ink-3);
  transition: color var(--t-fast) var(--ease-out);
}

.hero-quick-item:hover {
  color: var(--ink);
}

.hero-campus {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: center;
  gap: 4px 14px;
  width: 100%;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
  font-size: var(--text-xs);
  color: var(--ink-4);
}

.hero-campus a {
  color: var(--ink-3);
  transition: color var(--t-fast) var(--ease-out);
}

.hero-campus a:hover {
  color: var(--ink);
}

@media (max-width: 640px) {
  .hero-center {
    gap: 14px;
  }

  .hero-campus {
    margin-top: 10px;
    padding-top: 0;
    border-top: 0;
  }

  .hero-campus-label {
    display: none;
  }

  .hero-quick {
    gap: 8px 18px;
  }
}
</style>
