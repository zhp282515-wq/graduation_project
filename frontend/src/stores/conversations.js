import { defineStore } from 'pinia'
import { computed, reactive, ref, watch } from 'vue'
import { createSession, deleteSession as removeSession, getMessages, listSessions } from '../api/sessions'
import { regenerateChat, streamChat } from '../api/conversation'
import { buildTurns, imageUrl } from '../utils/history'
import { normalizeSources } from '../utils/citations'
import { isAbortError } from '../api/http'
import { useUiStore } from './ui'

let runTicker = null
let liveSeed = 0

/** 没有会话时（还没说第一句话）也允许有一条进行中的流，用这个 key 占位。 */
const DRAFT_KEY = '__draft__'

function emptyRun() {
  return {
    active: false,
    phase: 'idle', // idle | connecting | thinking | answering | stopping | failed | aborted | settled
    startedAt: 0,
    endedAt: 0,
    elapsedMs: 0,
    operation: 'send',
    targetKey: '',
    messageId: null,
    reasoning: '',
    text: '',
    steps: [],
    sources: [],
    error: '',
    errorType: '',
    tokenTotal: null,
    finishReason: '',
    saved: false,
    sessionId: null,
    turn: null,
  }
}

export const useConversationStore = defineStore('conversation', () => {
  const ui = useUiStore()
  let generation = 0

  const sessions = ref([])
  const sessionsStatus = ref('idle')
  const sessionsError = ref('')

  const activeId = ref(null)
  const turns = ref([])
  const historyStatus = ref('idle')
  const historyError = ref('')

  /**
   * 每个会话各有一条运行状态。旧版允许「A 会话生成中，切到 B 会话继续提问」，
   * 所以这里不能只有一条全局 run：runs 以 sessionId 为键，run 只是当前视图。
   */
  const runs = reactive({})
  const controllers = new Map()
  // 接口历史不包含工具轨迹；在当前页面生命周期内，按会话和回答 id 保留各轮快照。
  const completedTraces = new Map()

  function runKey(sessionId) {
    return sessionId || DRAFT_KEY
  }

  function runFor(sessionId) {
    const key = runKey(sessionId)
    if (!runs[key]) runs[key] = emptyRun()
    return runs[key]
  }

  runFor(null)

  const run = computed(() => runs[runKey(activeId.value)] || runFor(activeId.value))

  watch(activeId, (id) => {
    runFor(id)
  })

  const sortedSessions = computed(() =>
    [...sessions.value].sort((a, b) => {
      const left = new Date(a.updated_at || a.created_at || 0).getTime()
      const right = new Date(b.updated_at || b.created_at || 0).getTime()
      return right - left
    }),
  )

  const activeSession = computed(
    () => sortedSessions.value.find((session) => session.id === activeId.value) || null,
  )

  const busy = computed(() => Boolean(run.value?.active))

  const liveTurn = computed(() =>
    run.value.active ? turns.value.find((turn) => turn.key === run.value.targetKey) || null : null,
  )

  /** 哪些会话正在后台生成——会话档案里给它们加个呼吸点。 */
  const runningIds = computed(() =>
    Object.entries(runs)
      .filter(([, state]) => state.active && state.sessionId)
      .map(([, state]) => state.sessionId),
  )

  function isRunning(sessionId) {
    if (!sessionId) return false
    return Boolean(runs[runKey(sessionId)]?.active)
  }

  async function fetchSessions({ silent = false } = {}) {
    if (!silent) {
      sessionsStatus.value = 'loading'
      sessionsError.value = ''
    }
    try {
      const data = await listSessions()
      sessions.value = Array.isArray(data) ? data : []
      sessionsStatus.value = 'ready'
      return sessions.value
    } catch (error) {
      if (isAbortError(error)) return []
      sessionsStatus.value = 'error'
      sessionsError.value = error?.message || '会话列表加载失败'
      if (!silent) ui.notify(sessionsError.value, 'err')
      return []
    }
  }

  function stopTicker() {
    if (runTicker) {
      window.clearInterval(runTicker)
      runTicker = null
    }
  }

  function startTicker() {
    if (runTicker) return
    runTicker = window.setInterval(() => {
      let alive = false
      for (const state of Object.values(runs)) {
        if (!state.active) continue
        alive = true
        state.elapsedMs = Date.now() - state.startedAt
      }
      if (!alive) stopTicker()
    }, 240)
  }

  function resetRun(state) {
    Object.assign(state, emptyRun())
  }

  async function loadHistory(sessionId) {
    if (!sessionId) {
      turns.value = []
      historyStatus.value = 'idle'
      return
    }
    historyStatus.value = 'loading'
    historyError.value = ''
    try {
      const messages = await getMessages(sessionId)
      if (activeId.value !== sessionId) return
      const built = buildTurns(messages)
      const state = runs[runKey(sessionId)]
      const traces = completedTraces.get(sessionId)
      for (const turn of built) {
        const trace = traces?.get(turn.assistant?.id)
        if (trace) turn.trace = trace
      }
      if (state?.active && state.turn) {
        const currentIndex = built.findIndex((turn) =>
          turn.key === state.targetKey ||
          (state.turn.userId != null && turn.userId === state.turn.userId) ||
          (state.messageId != null && turn.assistant?.id === state.messageId),
        )
        // 服务端已经先落了 user 消息，这里用正在流式的那一轮替换掉「等待回应」的占位，避免同一问题出现两次。
        const tail = built[built.length - 1]
        const sameQuestion =
          tail &&
          !tail.assistant?.text &&
          (tail.userText || '') === (state.turn.userText || '')
        const turn = state.turn
        if (currentIndex >= 0) {
          turn.index = built[currentIndex].index
          built.splice(currentIndex, 1, turn)
        } else {
          if (sameQuestion) built.pop()
          turn.index = built.length + 1
          built.push(turn)
        }
      }
      turns.value = built
      historyStatus.value = 'ready'
    } catch (error) {
      historyStatus.value = 'error'
      historyError.value = error?.message || '历史消息加载失败'
    }
  }

  async function openSession(sessionId) {
    if (!sessionId) {
      await startNew()
      return
    }
    if (activeId.value === sessionId && historyStatus.value === 'ready') {
      ui.markVisited(sessionId)
      return
    }
    activeId.value = sessionId
    runFor(sessionId)
    ui.markVisited(sessionId)
    turns.value = []
    await loadHistory(sessionId)
  }

  async function startNew() {
    // 不在这里创建服务端会话：用户还没说话就落一条空会话，会把列表塞满。
    // 也不打断正在后台生成的会话——旧版允许离开当前会话继续跑。
    activeId.value = null
    turns.value = []
    historyStatus.value = 'idle'
    historyError.value = ''
    resetRun(runFor(null))
  }

  async function ensureSession() {
    const epoch = generation
    if (activeId.value) return activeId.value
    const created = await createSession()
    if (epoch !== generation) throw Object.assign(new Error('账号已切换'), { name: 'AbortError' })
    const id = created?.id || created?.session_id
    if (!id) throw new Error('创建会话失败：后端没有返回会话 id')
    activeId.value = id
    runFor(id)
    ui.markVisited(id)
    await fetchSessions({ silent: true })
    return id
  }

  function attachLiveTurn(state, { text, images }) {
    liveSeed += 1
    const turn = {
      key: `live-${liveSeed}`,
      index: turns.value.length + 1,
      userId: null,
      userText: text,
      images: images.map(imageUrl),
      createdAt: new Date().toISOString(),
      live: true,
      assistant: {
        id: null,
        text: '',
        sources: [],
        tokenTotal: null,
        createdAt: '',
        canRegenerate: false,
        streaming: true,
      },
    }
    turns.value = [...turns.value, turn]
    state.turn = turn
    state.targetKey = turn.key
    return turn
  }

  function findTurn(key) {
    return turns.value.find((turn) => turn.key === key) || null
  }

  function assistantOf(state) {
    if (state.turn?.assistant) return state.turn.assistant
    return findTurn(state.targetKey)?.assistant || null
  }

  function ownsTurn(state) {
    const current = runs[runKey(state.sessionId)]
    return current === state || current?.turn !== state.turn
  }

  function saveTurnTrace(state) {
    if (!state.turn || !ownsTurn(state)) return
    state.turn.live = false
    state.turn.trace = {
      reasoning: state.reasoning,
      steps: state.steps.map((step) => ({ ...step, sources: [...step.sources] })),
      phase: state.phase,
      error: state.error,
      finishReason: state.finishReason,
      elapsedMs: state.elapsedMs,
    }
    const assistant = assistantOf(state)
    if (state.saved && assistant?.id != null && runs[runKey(state.sessionId)] === state) {
      if (!completedTraces.has(state.sessionId)) completedTraces.set(state.sessionId, new Map())
      completedTraces.get(state.sessionId).set(assistant.id, state.turn.trace)
    }
  }

  function stepFor(state, toolCallId, name) {
    let step = state.steps.find(
      (item) =>
        (toolCallId && item.id === toolCallId) ||
        (!toolCallId && item.name === name && item.status === 'pending'),
    )
    if (!step) {
      step = reactive({
        id: toolCallId || `step-${state.steps.length + 1}`,
        name: name || 'tool',
        args: '',
        status: 'pending',
        elapsedMs: null,
        sources: [],
        startedAt: 0,
      })
      state.steps.push(step)
    }
    return step
  }

  function mergeSources(target, incoming) {
    const normalized = normalizeSources(incoming)
    if (!normalized.length) return target
    const map = new Map(target.map((item) => [item.id, item]))
    for (const item of normalized) map.set(item.id, item)
    return [...map.values()]
  }

  function handleEvent(event, state) {
    // 停止、重试或切换轮次后，旧连接残留的数据不能写入新的运行状态。
    if (runs[runKey(state.sessionId)] !== state || !state.active || state.saved ||
      state.phase === 'failed' || state.phase === 'aborted') return
    const type = event?.type
    if (type === 'run_started') {
      state.phase = 'thinking'
      state.operation = event.operation || 'send'
      if (typeof event.started_at === 'string') {
        const stamp = new Date(event.started_at).getTime()
        if (Number.isFinite(stamp)) state.startedAt = stamp
      }
      if (event.operation === 'regenerate' && event.message_id) {
        state.messageId = event.message_id
        const assistant = assistantOf(state)
        if (assistant) {
          assistant.previousText = assistant.text
          assistant.text = ''
          assistant.streaming = true
        }
      }
      return
    }

    if (type === 'reasoning_delta') {
      state.reasoning += event.content || ''
      if (state.phase === 'connecting') state.phase = 'thinking'
      return
    }

    if (type === 'text_delta') {
      state.text += event.content || ''
      state.phase = 'answering'
      const assistant = assistantOf(state)
      if (assistant) {
        assistant.text = state.text
        assistant.streaming = true
      }
      return
    }

    if (type === 'tool_call') {
      const step = stepFor(state, event.tool_call_id, event.name)
      step.args = typeof event.arguments === 'string' ? event.arguments : JSON.stringify(event.arguments ?? '')
      if (state.phase === 'connecting') state.phase = 'thinking'
      return
    }

    if (type === 'tool_started') {
      const step = stepFor(state, event.tool_call_id, event.name)
      step.status = 'running'
      step.startedAt = Date.now()
      return
    }

    if (type === 'tool_finished') {
      const step = stepFor(state, event.tool_call_id, event.name)
      step.status = event.status || 'completed'
      step.elapsedMs = Number.isFinite(event.elapsed_ms) ? event.elapsed_ms : null
      step.sources = normalizeSources(event.sources)
      state.sources = mergeSources(state.sources, event.sources)
      const assistant = assistantOf(state)
      if (assistant) assistant.sources = state.sources
      return
    }

    if (type === 'done') {
      const final = event.final_answer || {}
      const content = typeof final.content === 'string' ? final.content : state.text
      const sources = normalizeSources(final.sources || state.sources)
      const assistant = assistantOf(state)
      if (assistant) {
        assistant.text = content
        assistant.sources = sources
        assistant.id = final.message_id ?? null
        assistant.tokenTotal = Number.isFinite(final.total_tokens) ? final.total_tokens : assistant.tokenTotal
        assistant.createdAt = new Date().toISOString()
        assistant.canRegenerate = Boolean(final.message_id)
        assistant.streaming = false
        delete assistant.previousText
      }
      state.text = content
      state.sources = sources
      state.tokenTotal = Number.isFinite(final.total_tokens) ? final.total_tokens : state.tokenTotal
      state.finishReason = final.finish_reason || ''
      state.phase = 'settled'
      state.saved = true
      state.endedAt = Date.now()
      return
    }

    if (type === 'run_failed') {
      state.error = event.message || '本轮执行失败'
      state.errorType = event.error_type || ''
      state.phase = 'failed'
      state.endedAt = Date.now()
    }
  }

  function beginRun(sessionId, operation) {
    const state = reactive(emptyRun())
    runs[runKey(sessionId)] = state
    state.sessionId = sessionId
    state.active = true
    state.phase = 'connecting'
    state.startedAt = Date.now()
    state.operation = operation
    startTicker()
    const controller = new AbortController()
    controllers.set(runKey(sessionId), controller)
    return { state, controller }
  }

  async function settleRun(state, sessionId) {
    state.active = false
    state.elapsedMs = state.endedAt ? state.endedAt - state.startedAt : Date.now() - state.startedAt
    state.endedAt = state.endedAt || Date.now()
    const assistant = assistantOf(state)
    if (assistant && ownsTurn(state)) assistant.streaming = false
    saveTurnTrace(state)
    if (runs[runKey(sessionId)] === state) controllers.delete(runKey(sessionId))
    if (!Object.values(runs).some((item) => item.active)) stopTicker()
    if (runs[runKey(sessionId)] === state) await fetchSessions({ silent: true })
  }

  async function send({ text, images = [], reasoning = null, autoRename = true }) {
    const epoch = generation
    const trimmed = String(text || '').trim()
    if (!trimmed && !images.length) return
    if (busy.value) return

    let sessionId
    try {
      sessionId = await ensureSession()
    } catch (error) {
      if (!isAbortError(error)) ui.notify(error?.message || '创建会话失败', 'err')
      return
    }

    if (epoch !== generation || runFor(sessionId).active) return
    const { state, controller } = beginRun(sessionId, 'send')
    const turn = attachLiveTurn(state, { text: trimmed, images })
    state.targetKey = turn.key

    try {
      await streamChat({
        sessionId,
        text: trimmed,
        images,
        reasoning,
        signal: controller.signal,
        onEvent: (event) => handleEvent(event, state),
      })
      if (!state.saved && state.phase !== 'failed' && state.phase !== 'aborted') {
        state.phase = 'failed'
        state.error = '连接已中断，未收到本轮完成结果，请稍后重试'
      }
    } catch (error) {
      if (controller.signal.aborted || isAbortError(error)) {
        state.phase = 'aborted'
        state.error = '已停止生成，这一段回答没有保存'
      } else {
        state.phase = 'failed'
        state.error = error?.message || '本轮执行失败'
        if (error?.status === 409) state.error = '这个会话正在生成另一条回答，请稍候'
        if (error?.status === 404) state.error = '会话不存在，可能已被删除'
      }
    } finally {
      await settleRun(state, sessionId)
      if (state.phase === 'failed' && activeId.value === sessionId) ui.notify(state.error, 'err')
      if (autoRename && runs[runKey(sessionId)] === state) ui.markVisited(sessionId)
    }
  }

  async function regenerate(turnKey) {
    const sessionId = activeId.value
    const turn = findTurn(turnKey)
    const assistant = turn?.assistant
    if (!assistant?.id) {
      ui.notify('这条回答还没有保存，无法重新生成', 'warn')
      return
    }
    if (!sessionId) return
    if (runFor(sessionId).active) return

    const previousAnswer = { ...assistant }
    const { state, controller } = beginRun(sessionId, 'regenerate')
    state.targetKey = turnKey
    state.turn = turn
    state.messageId = assistant.id
    turn.live = true

    try {
      await regenerateChat({
        sessionId,
        messageId: assistant.id,
        signal: controller.signal,
        onEvent: (event) => handleEvent(event, state),
      })
      if (!state.saved && state.phase !== 'failed' && state.phase !== 'aborted') {
        state.phase = 'failed'
        state.error = '连接已中断，未收到本轮完成结果，请稍后重试'
      }
    } catch (error) {
      if (controller.signal.aborted || isAbortError(error)) {
        state.phase = 'aborted'
        state.error = '已停止生成'
      } else {
        state.phase = 'failed'
        state.error = error?.message || '重新生成失败'
        if (error?.status === 422) state.error = '这条回复无法关联原问题，不能重新生成'
      }
    } finally {
      if (!state.saved && turn.assistant && ownsTurn(state)) {
        Object.assign(turn.assistant, previousAnswer)
        delete turn.assistant.previousText
      }
      await settleRun(state, sessionId)
      if (state.phase === 'failed' && activeId.value === sessionId) ui.notify(state.error, 'err')
    }
  }

  function abortRun({ silent = false, sessionId = activeId.value } = {}) {
    const key = runKey(sessionId)
    const controller = controllers.get(key)
    if (controller) {
      try {
        controller.abort()
      } catch {
        /* noop */
      }
      controllers.delete(key)
    }
    const state = runs[key]
    if (state?.active) {
      state.active = false
      state.phase = 'aborted'
      state.endedAt = Date.now()
      state.elapsedMs = state.endedAt - state.startedAt
      const assistant = assistantOf(state)
      if (assistant) assistant.streaming = false
      saveTurnTrace(state)
      if (!silent) ui.notify('已停止生成', 'info')
    }
    if (!Object.values(runs).some((item) => item.active)) stopTicker()
  }

  function stop() {
    const state = run.value
    if (!state?.active) return
    state.phase = 'stopping'
    abortRun()
  }

  async function remove(id) {
    try {
      await removeSession(id)
      completedTraces.delete(id)
      sessions.value = sessions.value.filter((session) => session.id !== id)
      if (activeId.value === id) await startNew()
      ui.notify('会话已删除', 'ok')
      return true
    } catch (error) {
      if (error?.status === 409) ui.notify('会话正在生成中，暂时不能删除', 'warn')
      else ui.notify(error?.message || '删除会话失败', 'err')
      return false
    }
  }

  function reset() {
    generation++
    for (const key of Object.keys(runs)) abortRun({ silent: true, sessionId: key === DRAFT_KEY ? null : key })
    for (const key of Object.keys(runs)) delete runs[key]
    completedTraces.clear()
    sessions.value = []
    sessionsStatus.value = 'idle'
    sessionsError.value = ''
    activeId.value = null
    turns.value = []
    historyStatus.value = 'idle'
    resetRun(runFor(null))
  }

  return {
    sessions,
    sortedSessions,
    sessionsStatus,
    sessionsError,
    activeId,
    activeSession,
    turns,
    historyStatus,
    historyError,
    run,
    busy,
    liveTurn,
    runningIds,
    isRunning,
    fetchSessions,
    openSession,
    startNew,
    send,
    regenerate,
    stop,
    abortRun,
    remove,
    loadHistory,
    reset,
  }
})
