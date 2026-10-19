<script setup>
import { ref, reactive, computed, onMounted, nextTick } from 'vue'
import BrandLogo from './components/BrandLogo.vue'
import ParticleDrift from './components/ParticleDrift.vue'
import { listSessions, createSession, getMessages, deleteSession } from './api/sessions'
import { streamChat } from './api/chat.js'
import { uploadImage } from './api/client'
import { renderMarkdown } from './utils/markdown'
import 'highlight.js/styles/github.css'

const inputText = ref('')
const sessions = ref([])
const currentSessionId = ref(null)
const messageListRef = ref(null)

/**
 * 每个会话独立的消息状态。
 * 流式生成时把内容写进这里的对象，切换会话只是换显示来源，
 * 请求不会中断，后台那一轮继续写入，切回来时内容已经在。
 */
const cache = reactive(new Map())
const controllers = new Map()

function stateOf(sid) {
  if (!cache.has(sid)) {
    cache.set(sid, reactive({ messages: [], streaming: false }))
  }
  return cache.get(sid)
}

const currentState = computed(() =>
  currentSessionId.value ? cache.get(currentSessionId.value) ?? null : null
)
const messages = computed(() => currentState.value?.messages ?? [])
const sending = computed(() => currentState.value?.streaming ?? false)

/* ===== 会话搜索 ===== */
const searchText = ref('')

const filteredSessions = computed(() => {
  const q = searchText.value.trim().toLowerCase()
  if (!q) return sessions.value
  return sessions.value.filter((s) => s.title.toLowerCase().includes(q))
})

/** 会话时间：今天显示时分，昨天显示「昨天」，更早显示月-日 */
function formatSessionTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const diffDays = Math.floor((startOfToday - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000)

  if (diffDays <= 0) {
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  }
  if (diffDays === 1) return '昨天'
  if (diffDays < 7) return `${diffDays}天前`
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

/* ===== 按时间分组 ===== */
const GROUP_ORDER = ['today', 'yesterday', 'week', 'month']
const GROUP_LABEL = { today: '今天', yesterday: '昨天', week: '7天内', month: '30天内' }

function bucketOf(iso) {
  const d = new Date(iso)
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const dayDiff = Math.floor((startOfToday - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000)

  if (dayDiff <= 0) return 'today'
  if (dayDiff === 1) return 'yesterday'
  if (dayDiff < 7) return 'week'
  if (dayDiff < 30) return 'month'
  return `ym-${d.getFullYear()}-${d.getMonth() + 1}`
}

const groupedSessions = computed(() => {
  const list = filteredSessions.value
  if (!list.length) return []

  const buckets = new Map()
  for (const s of list) {
    const key = bucketOf(s.updated_at)
    if (!buckets.has(key)) buckets.set(key, [])
    buckets.get(key).push(s)
  }

  const groups = []
  for (const key of GROUP_ORDER) {
    if (buckets.has(key)) {
      groups.push({ key, label: GROUP_LABEL[key], sessions: buckets.get(key) })
    }
  }

  // 年-月分组按时间倒序
  const ymKeys = [...buckets.keys()]
    .filter((k) => k.startsWith('ym-'))
    .sort((a, b) => {
      const [ay, am] = a.slice(3).split('-').map(Number)
      const [by, bm] = b.slice(3).split('-').map(Number)
      return by - ay || bm - am
    })
  for (const key of ymKeys) {
    const [y, m] = key.slice(3).split('-')
    groups.push({ key, label: `${y}年${m}月`, sessions: buckets.get(key) })
  }

  return groups
})

function isStreaming(sid) {
  return cache.get(sid)?.streaming ?? false
}

function scrollToBottom() {
  nextTick(() => {
    const el = messageListRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function refreshSessions() {
  try {
    sessions.value = await listSessions()
  } catch (e) {
    console.error('加载会话列表失败:', e)
    toast(`加载会话失败：${e.message}`, 'error')
  }
}

async function newSession() {
  try {
    const s = await createSession()
    currentSessionId.value = s.id
    stateOf(s.id)            // 复用空会话时保留其已有状态
    await refreshSessions()
  } catch (e) {
    console.error('新建会话失败:', e)
    toast(`新建会话失败：${e.message}`, 'error')
  }
}

async function selectSession(id) {
  if (id === currentSessionId.value) return
  currentSessionId.value = id

  // 已有本地状态（含正在生成的）直接用，避免覆盖
  if (cache.has(id)) {
    scrollToBottom()
    return
  }

  try {
    const history = await getMessages(id)
    stateOf(id).messages = history.map((m) => ({
      role: m.role,
      content: m.content,
      images: m.images ?? undefined,
    }))
    scrollToBottom()
  } catch (e) {
    console.error('加载消息失败:', e)
    toast(`加载消息失败：${e.message}`, 'error')
  }
}

async function send() {
  const text = inputText.value.trim()
  const readyImages = pickedFiles.value.filter((f) => f.status === 'done')
  if ((!text && !readyImages.length) || sending.value || uploading.value) return

  // 没有会话时自动创建一个，让用户可以直接开始提问
  if (!currentSessionId.value) {
    try {
      const s = await createSession()
      currentSessionId.value = s.id
      stateOf(s.id)
      await refreshSessions()
    } catch (e) {
      console.error('创建会话失败:', e)
      toast(`创建会话失败：${e.message}`, 'error')
      return
    }
  }

  const sid = currentSessionId.value
  const st = stateOf(sid)
  if (st.streaming) return

  const imagePaths = readyImages.map((f) => f.path)
  const imageUrls = readyImages.map((f) => f.url)

  inputText.value = ''
  pickedFiles.value = []
  st.streaming = true

  st.messages.push({ role: 'user', content: text, images: imageUrls })
  const reply = reactive({ role: 'assistant', content: '', streaming: true })
  st.messages.push(reply)
  scrollToBottom()

  const controller = new AbortController()
  controllers.set(sid, controller)

  try {
    await streamChat({
      sessionId: sid,
      text,
      images: imagePaths,
      signal: controller.signal,
      onEvent(event) {
        switch (event.type) {
          case 'text_delta':
            reply.content += event.content || ''
            if (currentSessionId.value === sid) scrollToBottom()
            break
          case 'tool_started':
            reply.toolName = event.name
            break
          case 'tool_finished':
            reply.toolName = null
            break
          case 'done':
            reply.streaming = false
            break
          case 'run_failed':
            reply.streaming = false
            reply.error = event.message
            break
        }
      },
    })
  } catch (e) {
    if (e.name === 'AbortError') {
      reply.streaming = false
    } else {
      reply.streaming = false
      reply.error = e.message
    }
  } finally {
    st.streaming = false
    controllers.delete(sid)
    // 首条消息会自动改标题，刷新列表
    await refreshSessions()
  }
}

function askSuggestion(q) {
  inputText.value = q
  send()
}

/* ===== 站内轻提示 ===== */
const toasts = ref([])
let toastSeq = 0

function toast(message, type = 'info', duration = 3000) {
  const id = ++toastSeq
  toasts.value.push({ id, message, type })
  setTimeout(() => {
    const i = toasts.value.findIndex((t) => t.id === id)
    if (i !== -1) toasts.value.splice(i, 1)
  }, duration)
}

/* ===== 站内二次确认弹窗 ===== */
const confirmState = reactive({
  open: false,
  title: '',
  message: '',
  confirmText: '确定',
  danger: false,
  onConfirm: null,
})

function askConfirm({ title, message, confirmText = '确定', danger = false, onConfirm }) {
  confirmState.title = title
  confirmState.message = message
  confirmState.confirmText = confirmText
  confirmState.danger = danger
  confirmState.onConfirm = onConfirm
  confirmState.open = true
}

function closeConfirm() {
  confirmState.open = false
  confirmState.onConfirm = null
}

async function runConfirm() {
  const fn = confirmState.onConfirm
  closeConfirm()
  if (fn) await fn()
}

async function removeSession(session) {
  askConfirm({
    title: '删除会话',
    message: `确定删除会话「${session.title}」吗？此操作不可恢复。`,
    confirmText: '删除',
    danger: true,
    onConfirm: async () => {
      try {
        // 该会话正在生成时，先断开它的请求
        controllers.get(session.id)?.abort()
        controllers.delete(session.id)

        await deleteSession(session.id)
        cache.delete(session.id)

        if (currentSessionId.value === session.id) {
          currentSessionId.value = null
        }
        await refreshSessions()

        if (!currentSessionId.value && sessions.value.length) {
          await selectSession(sessions.value[0].id)
        }
      } catch (e) {
        toast(`删除失败：${e.message}`, 'error')
      }
    },
  })
}

onMounted(refreshSessions)

// 校园常用站点，统一在新标签页打开
const quickLinks = [
  { name: '学校官网', url: 'https://www.jxnu.edu.cn/' },
  { name: '教务在线', url: 'https://jwc.jxnu.edu.cn/' },
  { name: '图书馆', url: 'http://tsg.jxnu.edu.cn/' },
  { name: '本科招生就业网', url: 'http://zsjy.jxnu.edu.cn/' },
  { name: '研究生院', url: 'https://yz.jxnu.edu.cn/', title: '研究生院 / 研究生招生网' },
  { name: '学生处', url: 'https://xgw.jxnu.edu.cn/', title: '学生处（学工部）' },
]

// 三块面板的显示/隐藏状态
const visible = ref({ sessions: true, quick: true, flow: true })

const fileInput = ref(null)
const pickedFiles = ref([])   // { id, name, size, url, path, status: 'uploading'|'done'|'error' }
const uploading = ref(false)
const previewImage = ref(null)

const canSend = computed(
  () => !sending.value && !uploading.value &&
    (inputText.value.trim() !== '' || pickedFiles.value.some((f) => f.status === 'done'))
)

function openPicker() {
  fileInput.value?.click()
}

async function onFilesPicked(e) {
  const files = Array.from(e.target.files ?? [])
  e.target.value = ''
  if (!files.length) return

  for (const file of files) {
    const item = reactive({
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      name: file.name,
      size: file.size,
      url: URL.createObjectURL(file),   // 本地预览，上传完成后换成服务端地址
      path: null,
      status: 'uploading',
    })
    pickedFiles.value.push(item)
    uploading.value = true

    try {
      const res = await uploadImage(file)
      item.path = res.path
      item.url = res.url
      item.status = 'done'
    } catch (err) {
      item.status = 'error'
      item.error = err.message
      toast(`图片上传失败：${err.message}`, 'error')
    } finally {
      uploading.value = pickedFiles.value.some((f) => f.status === 'uploading')
    }
  }
}

function removePicked(item) {
  const i = pickedFiles.value.findIndex((f) => f.id === item.id)
  if (i !== -1) {
    URL.revokeObjectURL(item.url)
    pickedFiles.value.splice(i, 1)
  }
}
</script>

<template>
  <div class="app">
    <ParticleDrift
      class="app-bg"
      background="transparent"
      base-color="#e8f2ff"
      accent-color="#9ecbff"
      :density="220"
      :dot-size="6"
      :speed="22"
      :link-distance="200"
      :link-thickness="1"
      :hover="320"
    />
    <div class="ui">
      <header class="topbar panel" v-glass-tilt>
        <div class="brand">
          <BrandLogo part="emblem" :height="54" />
          <BrandLogo part="name" :height="30" />
        </div>
        <nav class="tabs">
          <button class="tab glass-btn active" v-glass-tilt>问答</button>
          <button class="tab glass-btn" v-glass-tilt>知识库</button>
        </nav>
        <div class="meta">
          <div class="avatar" />
        </div>
      </header>

      <div
        class="layout"
        :class="{ 'no-sidebar': !visible.sessions, 'no-right': !visible.quick && !visible.flow }"
      >
        <aside class="sidebar panel" v-glass-tilt :class="{ 'is-hidden': !visible.sessions }">
          <div class="panel-head">
            <h3 class="panel-title">会话管理</h3>
            <button
              class="hide-btn"
              type="button"
              title="隐藏会话管理"
              aria-label="隐藏会话管理"
              @click="visible.sessions = false"
            >
              <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"
                   fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round">
                <path d="M15 18l-6-6 6-6"/>
              </svg>
            </button>
          </div>

          <button class="new-session glass-btn" v-glass-tilt type="button" @click="newSession">
            <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"
                 fill="none" stroke="currentColor" stroke-width="2.2"
                 stroke-linecap="round">
              <path d="M12 5v14M5 12h14"/>
            </svg>
            新会话
          </button>
          <div class="search-box">
            <svg class="search-icon" viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"
                 fill="none" stroke="currentColor" stroke-width="2"
                 stroke-linecap="round" stroke-linejoin="round">
              <circle cx="11" cy="11" r="7"/>
              <path d="M20 20l-3.5-3.5"/>
            </svg>
            <input
              v-model="searchText"
              class="search-input"
              type="text"
              placeholder="搜索会话..."
              aria-label="搜索会话"
            />
            <button
              v-if="searchText"
              class="search-clear"
              type="button"
              aria-label="清除搜索"
              @click="searchText = ''"
            >
              <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"
                   fill="none" stroke="currentColor" stroke-width="2.2"
                   stroke-linecap="round">
                <path d="M6 6l12 12M18 6L6 18"/>
              </svg>
            </button>
          </div>
          <div class="session-list">
            <template v-for="group in groupedSessions" :key="group.key">
              <div class="session-group-label">{{ group.label }}</div>
              <div
                v-for="s in group.sessions"
                :key="s.id"
                class="session-item glass-btn"
                v-glass-tilt
                :class="{ active: s.id === currentSessionId }"
                @click="selectSession(s.id)"
              >
                <span class="dot" :class="{ busy: isStreaming(s.id) }" />
                <span class="session-main">
                  <span class="session-title">{{ s.title }}</span>
                  <span class="session-time">{{ formatSessionTime(s.updated_at) }}</span>
                </span>
                <button
                  class="session-del"
                  type="button"
                  title="删除会话"
                  aria-label="删除会话"
                  @click.stop="removeSession(s)"
                >
                  <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"
                       fill="none" stroke="currentColor" stroke-width="2"
                       stroke-linecap="round" stroke-linejoin="round">
                    <path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>
                  </svg>
                </button>
              </div>
            </template>
            <div v-if="!sessions.length" class="session-empty">还没有会话</div>
            <div v-else-if="!filteredSessions.length" class="session-empty">
              没有匹配「{{ searchText }}」的会话
            </div>
          </div>
        </aside>

        <main class="main panel" v-glass-tilt>
          <div v-if="!messages.length" class="hero">
            <div>
              <h1>你好，<br />我是你的校园 AI 助手</h1>
              <p>基于江西师范大学知识库，为你提供准确、专业、贴心的校园问答服务。</p>
            </div>
          </div>

          <div v-if="!messages.length" class="suggest">
            <h3>猜你想问</h3>
            <div class="suggest-grid">
              <div
                v-for="q in ['图书馆开放时间', '校园地图怎么走', '食堂推荐', '学术资源查询']"
                :key="q"
                class="suggest-item glass-btn"
                v-glass-tilt
                @click="askSuggestion(q)"
              >
                {{ q }}
              </div>
            </div>
          </div>

          <div v-else ref="messageListRef" class="message-list">
            <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
              <div class="msg-bubble">
                <div v-if="m.toolName" class="msg-tool">正在使用 {{ m.toolName }}</div>
                <div v-if="m.images?.length" class="msg-images">
                  <img
                    v-for="(src, k) in m.images"
                    :key="k"
                    :src="src"
                    alt="上传的图片"
                    @click="previewImage = src"
                  />
                </div>
                <!-- AI 回复渲染 Markdown；用户消息只是纯文本 -->
                <div
                  v-if="m.role === 'assistant'"
                  class="msg-content md"
                  v-html="renderMarkdown(m.content)"
                />
                <div v-else-if="m.content" class="msg-content">{{ m.content }}</div>
                <span v-if="m.streaming && !m.content" class="msg-dots">
                  <i /><i /><i />
                </span>
                <div v-if="m.error" class="msg-error">{{ m.error }}</div>
              </div>
            </div>
          </div>

          <!-- 待发送图片 + 输入框作为整体吸底，缩略图始终在输入框正上方 -->
          <div class="composer-dock">
            <div v-if="pickedFiles.length" class="attach-preview">
              <div
                v-for="f in pickedFiles"
                :key="f.id"
                class="preview-item"
                :class="f.status"
                :title="f.error || f.name"
              >
                <img :src="f.url" :alt="f.name" />
                <div v-if="f.status === 'uploading'" class="preview-badge">上传中</div>
                <div v-else-if="f.status === 'error'" class="preview-badge err">失败</div>
                <button
                  class="preview-del"
                  type="button"
                  aria-label="移除图片"
                  @click="removePicked(f)"
                >×</button>
              </div>
            </div>

            <div class="composer-row">
            <button
              class="attach glass-btn"
              v-glass-tilt
              type="button"
              title="上传图片或文件"
              aria-label="上传图片或文件"
              @click="openPicker"
            >
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none"
                   stroke="currentColor" stroke-width="1.8"
                   stroke-linecap="round" stroke-linejoin="round">
                <path d="M21.4 11.05l-8.5 8.5a5.5 5.5 0 1 1-7.78-7.78l8.5-8.5a3.7 3.7 0 1 1 5.23 5.23l-8.5 8.5a1.85 1.85 0 1 1-2.62-2.62l7.8-7.8"/>
              </svg>
            </button>
            <input
              ref="fileInput"
              class="file-input"
              type="file"
              multiple
              accept="image/jpeg,image/png,image/gif,image/webp"
              @change="onFilesPicked"
            />
            <div class="composer">
              <input
                class="text-input"
                v-model="inputText"
                placeholder="请输入你想问的问题..."
                :disabled="sending"
                @keyup.enter="send"
              />
            </div>
            <button
              class="send glass-btn"
              v-glass-tilt
              type="button"
              title="发送"
              aria-label="发送"
              :disabled="!canSend"
              @click="send"
            >
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none"
                   stroke="currentColor" stroke-width="1.8"
                   stroke-linecap="round" stroke-linejoin="round">
                <path d="M4.5 12h15M13 5.5l6.5 6.5-6.5 6.5"/>
              </svg>
            </button>
            </div>
          </div>
        </main>

        <aside class="right">
          <section class="card panel quick-card" v-glass-tilt :class="{ 'is-hidden': !visible.quick }">
            <div class="panel-head">
              <h3 class="panel-title">快捷入口</h3>
              <button
                class="hide-btn"
                type="button"
                title="隐藏快捷入口"
                aria-label="隐藏快捷入口"
                @click="visible.quick = false"
              >
                <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"
                     fill="none" stroke="currentColor" stroke-width="2"
                     stroke-linecap="round" stroke-linejoin="round">
                  <path d="M9 18l6-6-6-6"/>
                </svg>
              </button>
            </div>
            <div class="quick-grid">
              <a
                v-for="site in quickLinks"
                :key="site.url"
                class="quick-item glass-btn"
                v-glass-tilt
                :href="site.url"
                :title="site.title || site.name"
                target="_blank"
                rel="noopener noreferrer"
              >
                {{ site.name }}
                <svg class="ext" viewBox="0 0 24 24" width="11" height="11" aria-hidden="true"
                     fill="none" stroke="currentColor" stroke-width="2"
                     stroke-linecap="round" stroke-linejoin="round">
                  <path d="M14 4h6v6M20 4l-9 9M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>
                </svg>
              </a>
            </div>
          </section>

          <section class="card panel flow-card" v-glass-tilt :class="{ 'is-hidden': !visible.flow }">
            <div class="panel-head">
              <h3 class="panel-title">工作流</h3>
              <button
                class="hide-btn"
                type="button"
                title="隐藏工作流"
                aria-label="隐藏工作流"
                @click="visible.flow = false"
              >
                <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"
                     fill="none" stroke="currentColor" stroke-width="2"
                     stroke-linecap="round" stroke-linejoin="round">
                  <path d="M9 18l6-6-6-6"/>
                </svg>
              </button>
            </div>
            <div class="flow">
              <div v-for="f in ['资料检索', '信息分析', '生成回答', '引用来源']" :key="f" class="flow-item glass-btn" v-glass-tilt>{{ f }}</div>
            </div>
          </section>
        </aside>
      </div>

      <!-- 隐藏后的恢复入口（在 .ui 之外，避免被层叠上下文遮挡） -->
      <button
        v-if="!visible.sessions"
        class="restore-tab left glass-btn"
        type="button"
        title="显示会话管理"
        @click="visible.sessions = true"
      >
        <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"
             fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round">
          <path d="M4 6h16M4 12h10M4 18h16"/>
        </svg>
        <span>会话</span>
      </button>

      <div v-if="!visible.quick || !visible.flow" class="restore-dock">
        <button
          v-if="!visible.quick"
          class="restore-tab glass-btn"
          type="button"
          title="显示快捷入口"
          @click="visible.quick = true"
        >
          <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"
               fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="7" height="7" rx="1.5"/>
            <rect x="14" y="3" width="7" height="7" rx="1.5"/>
            <rect x="3" y="14" width="7" height="7" rx="1.5"/>
            <rect x="14" y="14" width="7" height="7" rx="1.5"/>
          </svg>
          <span>快捷</span>
        </button>
        <button
          v-if="!visible.flow"
          class="restore-tab glass-btn"
          type="button"
          title="显示工作流"
          @click="visible.flow = true"
        >
          <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"
               fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            <circle cx="6" cy="6" r="2.2"/><circle cx="6" cy="18" r="2.2"/>
            <path d="M6 8.2v7.6M11 6h9M11 18h9"/>
          </svg>
          <span>工作流</span>
        </button>
      </div>
    </div>

    <!-- 站内二次确认弹窗 -->
    <Teleport to="body">
      <Transition name="confirm">
        <div v-if="confirmState.open" class="confirm-mask" @click.self="closeConfirm">
          <div class="confirm-box" role="dialog" aria-modal="true">
            <h3 class="confirm-title">{{ confirmState.title }}</h3>
            <p class="confirm-message">{{ confirmState.message }}</p>
            <div class="confirm-actions">
              <button class="confirm-btn ghost" type="button" @click="closeConfirm">取消</button>
              <button
                class="confirm-btn"
                :class="confirmState.danger ? 'danger' : 'primary'"
                type="button"
                @click="runConfirm"
              >
                {{ confirmState.confirmText }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 图片放大预览 -->
    <Teleport to="body">
      <Transition name="confirm">
        <div v-if="previewImage" class="lightbox" @click="previewImage = null">
          <img :src="previewImage" alt="预览" />
        </div>
      </Transition>
    </Teleport>

    <!-- 站内轻提示 -->
    <Teleport to="body">
      <TransitionGroup name="toast" tag="div" class="toast-stack">
        <div
          v-for="t in toasts"
          :key="t.id"
          class="toast-item"
          :class="t.type"
          role="alert"
        >
          {{ t.message }}
        </div>
      </TransitionGroup>
    </Teleport>
  </div>
</template>

<style>
* { box-sizing: border-box; }

html, body, #app {
  margin: 0;
  height: 100%;
  overflow: hidden;
  font-family: "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
}

/* ===== 主题变量 ===== */
:root {
  --text-primary: #eaf3ff;
  --text-secondary: #c3d9f2;
  --text-muted: #93b0d0;
  --text-strong: #ffffff;
  --bg-overlay: rgba(0, 0, 0, 0);
  --panel-tint: rgba(255, 255, 255, 1);
  --panel-saturate: 165%;
  --panel-blur: 22px;
  --glass-btn-bg: rgba(255, 255, 255, 0.07);
  --glass-btn-hover: rgba(255, 255, 255, 0.02);
  --glass-btn-active: rgba(215, 230, 248, 0.38);
  --shadow-soft: rgba(20, 55, 105, 0.20);
  --shadow-mid: rgba(20, 55, 105, 0.12);
  --inner-highlight: rgba(255, 255, 255, 0.85);
  --scrollbar: rgba(255, 255, 255, 0.35);
}


.app {
  position: relative;
  isolation: isolate;
  height: 100vh;
  background: #030509;
}

/* 粒子背景铺满整屏，位于内容之下。
   组件内联样式会写 position:relative，这里必须用 !important 覆盖。 */
.app-bg {
  position: fixed !important;
  inset: 0 !important;
  width: 100vw !important;
  height: 100vh !important;
  z-index: 0;
  pointer-events: none;
}



.ui {
  position: relative;
  z-index: 1;          /* 必须高于 .app::after 的遮罩层 */
  color: var(--text-primary);
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 18px 24px 24px;
}

.panel::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  z-index: 0;
  opacity: 0;
  transition: opacity 0.32s ease;
  background: radial-gradient(
    var(--glow-size, 320px) circle at var(--mx, 50%) var(--my, 50%),
    rgba(255, 255, 255, 0.09),
    rgba(255, 255, 255, 0.03) 45%,
    transparent 72%
  );
}
.panel > * { position: relative; z-index: 1; }
.panel:hover::before { opacity: 1; }
@media (hover: none) {
  .panel::before { display: none; }
}

.panel {
  border-radius: 26px;
  position: relative;
  /* 静态玻璃：模糊背后的背景图 + 乳白染色 + 内高光模拟玻璃厚度 */
  background:
    linear-gradient(
      150deg,
      rgba(255, 255, 255, 0.17) 0%,
      rgba(255, 255, 255, 0.08) 45%,
      rgba(255, 255, 255, 0.13) 100%
    );
  backdrop-filter: blur(6px) saturate(140%);
  -webkit-backdrop-filter: blur(6px) saturate(140%);
  border: 1px solid rgba(255, 255, 255, 0.30);
  box-shadow:
    0 12px 40px rgba(0, 0, 0, 0.35),
    0 2px 8px rgba(0, 0, 0, 0.22),
    inset 0 1px 0 rgba(255, 255, 255, 0.55),
    inset 0 -1px 0 rgba(255, 255, 255, 0.18);
  transition: background 0.4s ease, border-color 0.4s ease, box-shadow 0.4s ease;
}

/* 深色玻璃：深蓝黑半透明底 + 低饱和，保持通透但不发白 */

/* 顶栏单独调淡一点，避免压住校徽 */
.topbar.panel {
  background:
    linear-gradient(150deg,
      rgba(255, 255, 255, 0.07) 0%,
      rgba(255, 255, 255, 0.015) 55%,
      rgba(255, 255, 255, 0.04) 100%);
  backdrop-filter: blur(18px) saturate(150%);
  -webkit-backdrop-filter: blur(18px) saturate(150%);
}

.topbar {
  flex: none;
  height: 84px;
  padding: 0 28px;
  /* 三列等分：中间那组按钮始终落在容器正中，
     不受左右两侧宽度差影响 */
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
}

.brand {
  justify-self: start;
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}


.tabs {
  justify-self: center;
  display: flex;
  gap: 8px;
}
.tab {
  border: 0; cursor: pointer;
  padding: 9px 26px; border-radius: 999px;
  background: rgba(255, 255, 255, 0.30);
  color: var(--text-secondary); font-size: 15px;
  transition: background 0.2s;
}
.tab.active { background: rgba(255, 255, 255, 0.18); color: var(--text-strong); }

.meta {
  justify-self: end;
  display: flex;
  align-items: center;
  gap: 18px;
  font-size: 13px;
  color: var(--text-secondary);
}
.avatar { width: 38px; height: 38px; border-radius: 50%; background: rgba(255,255,255,0.6); }

/* 明暗切换按钮：与头像同尺寸的圆形玻璃钮 */


.layout {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 290px minmax(0, 1fr) 370px;
  /* 单行、行高固定为容器高度：任何面板显隐都不改变其它面板的高度 */
  grid-template-rows: minmax(0, 1fr);
  align-items: stretch;
  gap: 22px;
  transition:
    grid-template-columns 0.38s cubic-bezier(0.4, 0, 0.2, 1),
    column-gap 0.38s cubic-bezier(0.4, 0, 0.2, 1);
}
/* 列宽收到 0，gap 同步收掉，避免留下 22px 空档 */
.layout.no-sidebar { grid-template-columns: 0 minmax(0, 1fr) 370px; }
.layout.no-right   { grid-template-columns: 290px minmax(0, 1fr) 0; }
/* 右列内部两块都收起时，整列宽度也平滑归零 */
.layout.no-right > .right {
  opacity: 0;
  filter: blur(8px);
  transform: translateX(40px) scale(0.95);
  pointer-events: none;
}
.layout.no-sidebar.no-right { grid-template-columns: 0 minmax(0, 1fr) 0; }
.layout.no-sidebar, .layout.no-right { column-gap: 0; }

.sidebar, .main, .card { padding: 24px; overflow: hidden; }


.sidebar {
  transition:
    opacity 0.28s ease,
    transform 0.4s cubic-bezier(0.4, 0, 0.2, 1),
    filter 0.34s ease,
    padding 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 左栏收起：向左滑出 + 模糊溶解 + 轻微缩小 */
.sidebar.is-hidden {
  opacity: 0;
  transform: translateX(-40px) scale(0.95);
  filter: blur(8px);
  pointer-events: none;
  padding-left: 0;
  padding-right: 0;
  border-width: 0;
  overflow: hidden;
}

/* 右栏两块各自向右滑出 */
.right > .card {
  transition:
    opacity 0.28s ease,
    transform 0.4s cubic-bezier(0.4, 0, 0.2, 1),
    filter 0.34s ease,
    padding 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
.right > .card.is-hidden {
  opacity: 0;
  transform: translateX(40px) scale(0.95);
  filter: blur(8px);
  pointer-events: none;
  /* 完全不占位：行高归零由 .right 的 grid-template-rows 负责 */
  visibility: hidden;
}

/* 行高随显隐收缩，另一块平滑接管 */
.right {
  transition:
    grid-template-rows 0.42s cubic-bezier(0.4, 0, 0.2, 1),
    gap 0.42s cubic-bezier(0.4, 0, 0.2, 1);
}
.right:has(> .quick-card.is-hidden) > .quick-card,
.right:has(> .flow-card.is-hidden) > .flow-card {
  display: none;
}

.right:has(> .quick-card.is-hidden) { grid-template-rows: minmax(0, 1fr); gap: 0; }
.right:has(> .flow-card.is-hidden)  { grid-template-rows: auto; gap: 0; }
.right:has(> .quick-card.is-hidden):has(> .flow-card.is-hidden) {
  grid-template-rows: minmax(0, 1fr);
  gap: 0;
}

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 0;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.hide-btn {
  flex: none;
  width: 28px; height: 28px;
  display: grid; place-items: center;
  border: 0; border-radius: 8px;
  background: rgba(255, 255, 255, 0.07);
  color: var(--text-secondary);
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease, transform 0.16s ease;
}
.hide-btn:hover { background: rgba(255, 255, 255, 0.16); color: var(--text-primary); }
.hide-btn:active { transform: scale(0.9); }
.hide-btn:focus-visible {
  outline: 2px solid rgba(40, 110, 200, 0.75);
  outline-offset: 2px;
}

.new-session {
  flex: none;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  /* 与 .session-item 完全一致：padding 12/14、圆角 12 */
  padding: 12px 14px;
  border: 0;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.07);
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
  white-space: nowrap;
}

.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.30);
  border: 1px solid transparent;
  transition: background 0.2s ease, border-color 0.2s ease;
}
.search-box:focus-within {
  background: rgba(255, 255, 255, 0.42);
  border-color: rgba(40, 110, 200, 0.35);
}
.search-icon { flex: none; color: var(--text-muted); }
.search-input {
  flex: 1;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text-primary);
  font-size: 14px;
}
.search-input::placeholder { color: var(--text-muted); }
.search-clear {
  flex: none;
  width: 18px; height: 18px;
  display: grid; place-items: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: rgba(30, 70, 130, 0.18);
  color: var(--text-secondary);
  cursor: pointer;
  transition: background 0.18s ease;
}
.search-clear:hover { background: rgba(30, 70, 130, 0.30); }

/* 深色主题 */

.session-list { display: flex; flex-direction: column; gap: 8px; overflow: auto; }
.session-item {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 14px; border-radius: 12px;
  background: rgba(255, 255, 255, 0.07);
  font-size: 14px;
}

.session-group-label {
  margin: 10px 0 2px;
  padding-left: 4px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.5px;
  color: var(--text-muted);
  opacity: 0.85;
}
.session-group-label:first-child { margin-top: 2px; }

.session-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-time {
  font-size: 11px;
  color: var(--text-muted);
  opacity: 0.85;
  font-variant-numeric: tabular-nums;
}

/* 删除按钮默认隐藏，悬停/键盘聚焦时淡入 */
.session-del {
  flex: none;
  width: 24px; height: 24px;
  display: grid; place-items: center;
  border: 0; border-radius: 7px;
  background: transparent;
  color: var(--text-muted);
  opacity: 0;
  transform: scale(0.85);
  transition: opacity 0.2s ease, transform 0.2s ease, background 0.2s ease, color 0.2s ease;
}

.session-item:hover .session-del,
.session-del:focus-visible {
  opacity: 1;
  transform: scale(1);
}

.session-del:hover {
  background: rgba(210, 70, 70, 0.16);
  color: #b83838;
}
.session-del:active { transform: scale(0.9); }
.session-del:focus-visible {
  outline: 2px solid rgba(40, 110, 200, 0.75);
  outline-offset: 1px;
}

/* 触屏没有悬停，直接显示 */
@media (hover: none) {
  .session-del { opacity: 1; transform: none; }
}

.dot { width: 7px; height: 7px; border-radius: 50%; background: #8fd0ff; }

.main { display: flex; flex-direction: column; gap: 22px; }

/* ===== 消息列表 ===== */
.message-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-right: 6px;
  scroll-behavior: smooth;
}
.message-list::-webkit-scrollbar { width: 6px; }
.message-list::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.35);
  border-radius: 999px;
}

.msg { display: flex; }
.msg.user { justify-content: flex-end; }
.msg.assistant { justify-content: flex-start; }

.msg-bubble {
  max-width: 78%;
  padding: 13px 18px;
  border-radius: 16px;
  background: rgba(70, 130, 205, 0.55);
  border: 1px solid rgba(255, 255, 255, 0.35);
  box-shadow: 0 2px 10px rgba(20, 55, 105, 0.10);
  color: var(--text-primary);
  font-size: 16px;
  line-height: 1.75;
}
.msg.user .msg-bubble {
  background: rgba(42, 99, 176, 0.88);
  border-color: rgba(255, 255, 255, 0.25);
  color: #fff;
}

/* AI 回复：无气泡纯文本 */
.msg.assistant .msg-bubble {
  max-width: 100%;
  padding: 0;
  background: none;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  border: 0;
  box-shadow: none;
  border-radius: 0;
  color: var(--text-primary);
}

.msg-content { white-space: pre-wrap; word-break: break-word; }

/* ===== Markdown 渲染样式 ===== */
.msg-content.md { white-space: normal; }

.msg-content.md > :first-child { margin-top: 0; }
.msg-content.md > :last-child { margin-bottom: 0; }

.msg-content.md h1,
.msg-content.md h2,
.msg-content.md h3,
.msg-content.md h4 {
  margin: 16px 0 8px;
  line-height: 1.4;
  font-weight: 600;
  color: var(--text-strong);
}
.msg-content.md h1 { font-size: 1.35em; }
.msg-content.md h2 { font-size: 1.2em; }
.msg-content.md h3 { font-size: 1.08em; }
.msg-content.md h4 { font-size: 1em; }

.msg-content.md p { margin: 0 0 10px; }

.msg-content.md ul,
.msg-content.md ol {
  margin: 8px 0 10px;
  padding-left: 22px;
}
.msg-content.md li { margin: 4px 0; }
.msg-content.md li > p { margin: 0; }

.msg-content.md a {
  color: #1a5cb0;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.msg-content.md strong { font-weight: 600; }

.msg-content.md code {
  padding: 2px 6px;
  border-radius: 5px;
  background: rgba(30, 70, 130, 0.10);
  font-family: "JetBrains Mono", Consolas, monospace;
  font-size: 0.9em;
}

.msg-content.md pre {
  margin: 10px 0;
  padding: 12px 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.55);
  border: 1px solid rgba(30, 70, 130, 0.12);
  overflow-x: auto;
}
.msg-content.md pre code {
  padding: 0;
  background: none;
  font-size: 13px;
  line-height: 1.6;
}

.msg-content.md blockquote {
  margin: 10px 0;
  padding: 8px 14px;
  border-left: 3px solid rgba(30, 90, 170, 0.45);
  background: rgba(255, 255, 255, 0.28);
  border-radius: 0 8px 8px 0;
  color: var(--text-secondary);
}

.msg-content.md table {
  width: 100%;
  margin: 10px 0;
  border-collapse: collapse;
  font-size: 14px;
}
.msg-content.md th,
.msg-content.md td {
  padding: 8px 12px;
  border: 1px solid rgba(30, 70, 130, 0.16);
  text-align: left;
}
.msg-content.md th {
  background: rgba(255, 255, 255, 0.4);
  font-weight: 600;
}

.msg-content.md hr {
  margin: 16px 0;
  border: 0;
  border-top: 1px solid rgba(30, 70, 130, 0.18);
}

.msg-tool {
  display: inline-block;
  margin-bottom: 8px;
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.5);
  color: var(--text-secondary);
  font-size: 12px;
}

.msg-error {
  margin-top: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(220, 80, 80, 0.14);
  color: #a33;
  font-size: 13px;
}

/* 等待首个 token 的三个点 */
.msg-dots { display: inline-flex; gap: 4px; padding: 4px 0; }
.msg-dots i {
  width: 6px; height: 6px; border-radius: 50%;
  background: #4a7dbd;
  animation: dot-bounce 1.1s infinite ease-in-out;
}
.msg-dots i:nth-child(2) { animation-delay: 0.15s; }
.msg-dots i:nth-child(3) { animation-delay: 0.3s; }

@keyframes dot-bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.45; }
  30% { transform: translateY(-4px); opacity: 1; }
}

.session-empty {
  padding: 20px 8px;
  text-align: center;
  font-size: 13px;
  color: var(--text-muted);
}

.session-item.active {
  background: rgba(255, 255, 255, 0.30);
  font-weight: 600;
}

.suggest-item { cursor: pointer; }

.send:disabled,
.attach:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.send:disabled:hover { transform: none; }

.hero { display: flex; gap: 22px; align-items: center; }
.hero h1 { margin: 0 0 10px; font-size: 27px; line-height: 1.45; font-weight: 600; }
.hero p { margin: 0; font-size: 14px; color: var(--text-secondary); }

.suggest h3 { margin: 0 0 14px; font-size: 16px; font-weight: 600; }
.suggest-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.suggest-item {
  padding: 15px 18px; border-radius: 14px;
  background: rgba(255, 255, 255, 0.30);
  font-size: 14px;
}

/* 上传按钮 + 输入框并列的整行 */
/* 缩略图 + 输入行整体吸底 */
.composer-dock {
  margin-top: auto;
  flex: none;
}

.composer-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* 输入框容器：不再包住上传按钮 */
.composer {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 22px;
  min-height: 52px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.10);
}

.file-input { display: none; }

/* 上传按钮：独立圆形玻璃按钮，位于输入框左侧 */
.attach {
  width: 52px;
  height: 52px;
  flex: none;
  display: grid;
  place-items: center;
  border: 1px solid rgba(255, 255, 255, 0.35);
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.14);
  color: var(--text-secondary);
  transition: background 0.2s ease, color 0.2s ease;
}
.attach:hover { color: var(--text-primary); }

.attach-chips {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.attach-chip {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 5px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.20);
  color: var(--text-secondary);
  font-size: 12px;
}

.composer .text-input {
  flex: 1; min-width: 0;
  border: 0; outline: 0; background: transparent;
  color: var(--text-primary); font-size: 15px;
}
.composer .text-input::placeholder { color: var(--text-muted); }
/* 发送按钮：与上传按钮同款独立圆形玻璃按钮 */
.send {
  width: 52px;
  height: 52px;
  flex: none;
  display: grid;
  place-items: center;
  border: 1px solid rgba(255, 255, 255, 0.35);
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.14);
  color: var(--text-secondary);
  transition: background 0.2s ease, color 0.2s ease;
}
.send:hover { color: var(--text-primary); }

.right {
  /* 不能加 will-change / isolation / transform：它们会成为 backdrop root，
     让子卡片的 backdrop-filter 取不到页面背景，模糊失效 */
  transition:
    opacity 0.28s ease,
    transform 0.4s cubic-bezier(0.4, 0, 0.2, 1),
    filter 0.34s ease;
  display: grid;
  /* 快捷入口按内容高度，工作流吃掉剩余高度 → 底部与侧栏/主区对齐 */
  grid-template-rows: auto minmax(0, 1fr);
  gap: 22px;
  min-height: 0;
  transition:
    grid-template-rows 0.42s cubic-bezier(0.4, 0, 0.2, 1),
    gap 0.42s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 单块槽位：自身上下收起 + 淡出 + 模糊溶解 */
.quick-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.quick-item {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 16px 10px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.30);
  text-align: center;
  font-size: 13px;
  line-height: 1.35;
  color: var(--text-primary);
  text-decoration: none;
  white-space: nowrap;
}
.quick-item .ext {
  flex: none;
  opacity: 0.45;
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.quick-item:hover .ext {
  opacity: 0.9;
  transform: translate(1px, -1px);
}

.flow { display: flex; flex-direction: column; gap: 14px; }
.flow-item {
  padding: 14px 16px; border-radius: 12px;
  background: rgba(255, 255, 255, 0.07);
  font-size: 14px;
}

/* 隐藏后的恢复入口 */
.restore-tab.glass-btn {
  position: fixed;
  z-index: 100;
  pointer-events: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 14px;
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.34);
  backdrop-filter: blur(14px) saturate(160%);
  -webkit-backdrop-filter: blur(14px) saturate(160%);
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
  box-shadow: 0 6px 20px rgba(20, 55, 105, 0.2);
  animation: restore-in 0.28s cubic-bezier(0.22, 1, 0.36, 1);
}
.restore-tab.left {
  left: 0;
  top: 50%;
  z-index: 50;
  transform: translateY(-50%);
  border-radius: 0 999px 999px 0;
  padding-left: 12px;
}
.restore-tab.left:hover { transform: translateY(-50%) translateX(2px); }

.restore-dock {
  position: fixed;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  z-index: 100;
  pointer-events: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.restore-dock .restore-tab.glass-btn {
  position: relative;
  pointer-events: auto;
  border-radius: 999px 0 0 999px;
  padding-right: 12px;
}

@keyframes restore-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* ============================================================
   液态玻璃交互层
   - 悬停：指针跟随的径向高光 + 轻微上浮
   - 按压：内陷 + 高光收紧（苹果那种"按进果冻里"的手感）
   ============================================================ */
.glass-btn {
  position: relative;
  isolation: isolate;
  cursor: pointer;
  /* 按钮背景已足够均匀，不需要再叠 backdrop-filter：
     它在圆角元素上会分块采样，产生横向接缝，而且悬停重绘时接缝会移动。 */
  -webkit-tap-highlight-color: transparent;
  transition:
    transform 0.24s cubic-bezier(0.22, 1, 0.36, 1),
    box-shadow 0.24s cubic-bezier(0.22, 1, 0.36, 1),
    background-color 0.24s ease;
}

/* 指针跟随高光：位置由 --mx / --my 驱动 */
.glass-btn::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  z-index: 1;
  opacity: 0;
  transition: opacity 0.28s ease;
  /* screen 混合：亮处提亮，暗色按钮不会被洗成灰 */
  mix-blend-mode: screen;
  background: radial-gradient(
    140px circle at var(--mx, 50%) var(--my, 50%),
    rgba(255, 255, 255, 0.62),
    rgba(255, 255, 255, 0.20) 40%,
    transparent 64%
  );
}

/* 上缘镜面反射：模拟玻璃厚度 */
.glass-btn::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  z-index: 2;
  opacity: 0;
  transition: opacity 0.28s ease;
  mix-blend-mode: screen;
  background: linear-gradient(
    180deg,
    rgba(255, 255, 255, 0.40) 0%,
    rgba(255, 255, 255, 0.08) 20%,
    transparent 45%,
    transparent 100%
  );
}

.glass-btn > * { position: relative; z-index: 3; }

@media (hover: hover) {
  .glass-btn:hover {
    transform: translateY(-2px);
    /* 变透明：底下的玻璃折射透出来，是液态玻璃最关键的反馈 */
    background-color: rgba(255, 255, 255, 0.02);
    box-shadow:
      0 8px 22px rgba(25, 70, 130, 0.22),
      0 2px 6px rgba(25, 70, 130, 0.14),
      inset 0 1px 0 rgba(255, 255, 255, 0.75),
      inset 0 -1px 0 rgba(30, 70, 130, 0.10);
  }

  .glass-btn:hover::before { opacity: 1; }
  .glass-btn:hover::after { opacity: 1; }
}

.glass-btn:active {
  transform: translateY(0) scale(0.975);
  /* 浅色元素提亮/压暗都看不太出来，改用「内阴影 + 轻微压暗」制造凹陷感 */
  background-color: rgba(215, 230, 248, 0.38);
  box-shadow:
    0 1px 2px rgba(25, 70, 130, 0.16),
    inset 0 2px 6px rgba(20, 55, 105, 0.28),
    inset 0 -1px 0 rgba(255, 255, 255, 0.5);
  transition-duration: 0.08s;
}

.glass-btn:active::before {
  opacity: 1;
  background: radial-gradient(
    90px circle at var(--mx, 50%) var(--my, 50%),
    rgba(255, 255, 255, 0.70),
    rgba(255, 255, 255, 0.20) 45%,
    transparent 70%
  );
}

.glass-btn:focus-visible {
  outline: 2px solid rgba(40, 110, 200, 0.75);
  outline-offset: 2px;
}

/* ===== 生成中的会话指示 ===== */
.dot.busy {
  background: #2f7fd8;
  animation: dot-pulse 1.2s ease-in-out infinite;
}
@keyframes dot-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.35; transform: scale(0.75); }
}

/* ===== 站内二次确认弹窗 ===== */
.confirm-mask {
  position: fixed;
  inset: 0;
  z-index: 999;
  display: grid;
  place-items: center;
  background: rgba(10, 30, 60, 0.28);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}

.confirm-box {
  width: min(400px, calc(100vw - 48px));
  padding: 26px 26px 20px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(26px) saturate(160%);
  -webkit-backdrop-filter: blur(26px) saturate(160%);
  border: 1px solid rgba(255, 255, 255, 0.75);
  box-shadow:
    0 24px 60px rgba(15, 45, 90, 0.28),
    inset 0 1px 0 rgba(255, 255, 255, 0.9);
  color: var(--text-primary);
}

.confirm-title {
  margin: 0 0 10px;
  font-size: 17px;
  font-weight: 600;
}

.confirm-message {
  margin: 0 0 22px;
  font-size: 14px;
  line-height: 1.65;
  color: #3a5f90;
  word-break: break-word;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.confirm-btn {
  min-width: 84px;
  padding: 9px 18px;
  border-radius: 10px;
  border: 0;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease, transform 0.12s ease, box-shadow 0.2s ease;
}
.confirm-btn:active { transform: scale(0.97); }
.confirm-btn:focus-visible {
  outline: 2px solid rgba(40, 110, 200, 0.75);
  outline-offset: 2px;
}

.confirm-btn.ghost {
  background: rgba(255, 255, 255, 0.65);
  color: var(--text-secondary);
  border: 1px solid rgba(30, 70, 130, 0.18);
}
.confirm-btn.ghost:hover { background: rgba(255, 255, 255, 0.9); }

.confirm-btn.danger {
  background: linear-gradient(180deg, #d9534f, #c0392b);
  color: #fff;
  box-shadow: 0 6px 16px rgba(190, 50, 45, 0.28);
}
.confirm-btn.danger:hover {
  background: linear-gradient(180deg, #e0605c, #cb4234);
}

.confirm-btn.primary {
  background: linear-gradient(180deg, #2a63b0, #1a4a8c);
  color: #fff;
  box-shadow: 0 6px 16px rgba(30, 80, 160, 0.28);
}

/* 弹窗进出场 */
.confirm-enter-active,
.confirm-leave-active { transition: opacity 0.2s ease; }
.confirm-enter-active .confirm-box,
.confirm-leave-active .confirm-box {
  transition: transform 0.26s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.2s ease;
}
.confirm-enter-from,
.confirm-leave-to { opacity: 0; }
.confirm-enter-from .confirm-box,
.confirm-leave-to .confirm-box {
  opacity: 0;
  transform: translateY(10px) scale(0.96);
}

/* ===== 站内轻提示 ===== */
.toast-stack {
  position: fixed;
  top: 24px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1000;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  pointer-events: none;
}

.toast-item {
  max-width: min(520px, calc(100vw - 60px));
  padding: 11px 20px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
  border: 1px solid rgba(255, 255, 255, 0.7);
  box-shadow: 0 10px 30px rgba(15, 45, 90, 0.22);
  color: var(--text-primary);
  font-size: 14px;
  line-height: 1.5;
  word-break: break-word;
}
.toast-item.error {
  background: rgba(255, 236, 235, 0.92);
  border-color: rgba(200, 70, 65, 0.35);
  color: #a32d28;
}
.toast-item.success {
  background: rgba(232, 248, 238, 0.92);
  border-color: rgba(45, 150, 95, 0.3);
  color: #1c6b45;
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.24s ease, transform 0.3s cubic-bezier(0.22, 1, 0.36, 1);
}
.toast-enter-from {
  opacity: 0;
  transform: translateY(-10px) scale(0.96);
}
.toast-leave-to {
  opacity: 0;
  transform: translateY(-6px) scale(0.98);
}


/* ============================================================
   深色主题：内部元素反向提亮
   深色面板本身很暗，浅色小卡片会变成刺眼的亮点，
   所以统一换成低透明白 + 更亮的文字，保证对比度。
   ============================================================ */
/* 深色主题：气泡回到深蓝玻璃 */

/* 深色下按钮的按压/悬停反馈 */

/* 弹窗与提示 */


/* ===== 待发送图片预览 ===== */
.attach-preview {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 10px;
}

.preview-item {
  position: relative;
  width: 84px;
  height: 84px;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.4);
  box-shadow: 0 4px 14px rgba(20, 55, 105, 0.18);
  background: rgba(255, 255, 255, 0.25);
}
.preview-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.preview-item.uploading img { opacity: 0.5; }
.preview-item.error { border-color: rgba(200, 70, 65, 0.6); }

.preview-badge {
  position: absolute;
  inset: auto 0 0 0;
  padding: 3px 0;
  background: rgba(15, 40, 80, 0.72);
  color: #fff;
  font-size: 11px;
  text-align: center;
}
.preview-badge.err { background: rgba(170, 45, 40, 0.85); }

.preview-del {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 20px;
  height: 20px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: rgba(15, 35, 65, 0.68);
  color: #fff;
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.18s ease, background 0.18s ease;
}
.preview-item:hover .preview-del { opacity: 1; }
.preview-del:hover { background: rgba(190, 55, 50, 0.9); }

/* ===== 消息里的图片 ===== */
.msg-images {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.msg-images img {
  max-width: 180px;
  max-height: 180px;
  border-radius: 10px;
  object-fit: cover;
  cursor: zoom-in;
  border: 1px solid rgba(255, 255, 255, 0.35);
  transition: transform 0.2s ease;
}
.msg-images img:hover { transform: scale(1.02); }

/* ===== 图片灯箱 ===== */
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 900;
  display: grid;
  place-items: center;
  background: rgba(5, 12, 24, 0.82);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  cursor: zoom-out;
}
.lightbox img {
  max-width: 90vw;
  max-height: 90vh;
  border-radius: 12px;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.55);
}

</style>
