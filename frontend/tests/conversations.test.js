import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useConversationStore } from '../src/stores/conversations'
import { createSession, getMessages, listSessions } from '../src/api/sessions'
import { regenerateChat, streamChat } from '../src/api/conversation'

vi.mock('../src/api/sessions', () => ({
  createSession: vi.fn(), deleteSession: vi.fn(), getMessages: vi.fn(), listSessions: vi.fn(),
}))
vi.mock('../src/api/conversation', () => ({ streamChat: vi.fn(), regenerateChat: vi.fn() }))

describe('conversation run isolation', () => {
  let store
  let streams
  let jobs

  function holdStream(options) {
    return new Promise((resolve, reject) => {
      streams.push({ ...options, emit: options.onEvent, resolve, reject })
    })
  }

  async function send(text = '问题') {
    const promise = store.send({ text, reasoning: true })
    jobs.push(promise)
    await Promise.resolve()
    return { promise, stream: streams.at(-1), turn: store.turns.at(-1) }
  }

  function regenerate(turn) {
    const promise = store.regenerate(turn.key)
    jobs.push(promise)
    return { promise, stream: streams.at(-1), turn }
  }

  async function complete(job, id, reasoning, text = '回答') {
    job.stream.emit({ type: 'reasoning_delta', content: reasoning })
    job.stream.emit({ type: 'text_delta', content: text })
    job.stream.emit({ type: 'done', final_answer: { content: text, message_id: id, total_tokens: 20, finish_reason: 'stop' } })
    job.stream.resolve()
    await job.promise
  }

  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('window', {
      ...window,
      setInterval: vi.fn(() => 1), clearInterval: vi.fn(),
      setTimeout: vi.fn(() => 1), clearTimeout: vi.fn(),
    })
    setActivePinia(createPinia())
    store = useConversationStore()
    store.activeId = 's'
    store.historyStatus = 'ready'
    streams = []
    jobs = []
    listSessions.mockResolvedValue([{ id: 's', title: '多轮测试' }, { id: 'b', title: '另一会话' }])
    getMessages.mockResolvedValue([])
    streamChat.mockImplementation(holdStream)
    regenerateChat.mockImplementation(holdStream)
  })

  afterEach(async () => {
    store.reset()
    streams.forEach((stream) => stream.resolve())
    await Promise.allSettled(jobs)
    vi.unstubAllGlobals()
  })

  it('freezes each completed turn while a new turn reasons and streams', async () => {
    const first = await send('第一问')
    const firstRun = store.run
    first.stream.emit({ type: 'tool_call', name: 'weather', tool_call_id: 'weather-1', arguments: { city: '南昌' } })
    first.stream.emit({ type: 'tool_finished', name: 'weather', tool_call_id: 'weather-1', status: 'completed', elapsed_ms: 10 })
    await complete(first, 2, '第一轮思考', '第一轮回答')
    expect(first.turn.live).toBe(false)
    expect(first.turn.trace.reasoning).toBe('第一轮思考')
    const snapshot = JSON.stringify(first.turn)

    const second = await send('第二问')
    expect(store.run).not.toBe(firstRun)
    expect(store.liveTurn.key).toBe(second.turn.key)
    expect(store.turns.filter((turn) => turn.live)).toHaveLength(1)
    second.stream.emit({ type: 'reasoning_delta', content: '第二轮思考' })
    second.stream.emit({ type: 'text_delta', content: '第二轮正在输出' })
    second.stream.emit({ type: 'tool_call', name: 'weather', tool_call_id: 'weather-2', arguments: {} })
    expect(JSON.stringify(first.turn)).toBe(snapshot)
    expect(first.turn.assistant.streaming).toBe(false)
    expect(first.turn.trace.steps[0].id).toBe('weather-1')
    expect(store.run.steps[0].id).toBe('weather-2')
    await complete(second, 4, '补充思考', '第二轮回答')
    expect(second.turn.trace.reasoning).toBe('第二轮思考补充思考')
    expect(first.turn.trace.reasoning).toBe('第一轮思考')
    expect(store.liveTurn).toBeNull()
  })

  it('keeps separate reasoning when two sessions generate concurrently', async () => {
    const a = await send('会话 A')
    a.stream.emit({ type: 'reasoning_delta', content: 'A 的思考' })
    await store.openSession('b')
    const b = await send('会话 B')
    b.stream.emit({ type: 'reasoning_delta', content: 'B 的思考' })
    a.stream.emit({ type: 'reasoning_delta', content: '继续 A' })
    expect(store.run.reasoning).toBe('B 的思考')
    expect(store.isRunning('s')).toBe(true)
    expect(store.isRunning('b')).toBe(true)
    await complete(a, 2, '结束 A')
    expect(a.turn.trace.reasoning).toBe('A 的思考继续 A结束 A')
    expect(store.busy).toBe(true)
    expect(b.turn.assistant.streaming).toBe(true)
    await complete(b, 4, '结束 B')
    expect(b.turn.trace.reasoning).toBe('B 的思考结束 B')
  })

  it('ignores late events and cleanup from a stopped request after retry', async () => {
    const old = await send('停止的提问')
    old.stream.emit({ type: 'reasoning_delta', content: '停止前的思考' })
    store.stop()
    expect(old.turn.trace.reasoning).toBe('停止前的思考')
    const current = await send('新的提问')
    current.stream.emit({ type: 'reasoning_delta', content: '新思考' })
    old.stream.emit({ type: 'reasoning_delta', content: '旧流残留' })
    old.stream.emit({ type: 'text_delta', content: '旧回答' })
    old.stream.emit({ type: 'done', final_answer: { content: '旧回答', message_id: 10 } })
    old.stream.resolve()
    await old.promise
    expect(store.run.reasoning).toBe('新思考')
    expect(store.busy).toBe(true)
    expect(current.turn.assistant.streaming).toBe(true)
    expect(old.turn.trace.reasoning).toBe('停止前的思考')
    expect(old.turn.assistant.text).toBe('')
    store.stop()
    expect(current.stream.signal.aborted).toBe(true)
    current.stream.resolve()
    await current.promise
  })

  it('does not let events after done change a completed answer', async () => {
    const job = await send()
    job.stream.emit({ type: 'reasoning_delta', content: '本轮思考' })
    job.stream.emit({ type: 'done', final_answer: { content: '最终回答', message_id: 2 } })
    job.stream.emit({ type: 'text_delta', content: '不该追加' })
    job.stream.emit({ type: 'reasoning_delta', content: '不该共享' })
    job.stream.resolve()
    await job.promise
    expect(job.turn.assistant.text).toBe('最终回答')
    expect(job.turn.trace.reasoning).toBe('本轮思考')
  })

  it('regenerates only its target turn and preserves later turns', async () => {
    const first = await send('第一问')
    await complete(first, 2, '旧思考', '旧回答')
    const second = await send('第二问')
    await complete(second, 4, '第二轮思考', '第二轮回答')
    const snapshot = JSON.stringify(second.turn)
    const replacement = regenerate(first.turn)
    replacement.stream.emit({ type: 'run_started', operation: 'regenerate', message_id: 2 })
    replacement.stream.emit({ type: 'reasoning_delta', content: '重新思考' })
    expect(store.run.targetKey).toBe(first.turn.key)
    expect(store.liveTurn.key).toBe(first.turn.key)
    expect(JSON.stringify(second.turn)).toBe(snapshot)
    await complete(replacement, 2, '完成', '新的回答')
    expect(first.turn.trace.reasoning).toBe('重新思考完成')
    expect(JSON.stringify(second.turn)).toBe(snapshot)
  })

  it('restores each saved trace when returning to session history', async () => {
    const first = await send('第一问')
    await complete(first, 2, '第一轮思考')
    const second = await send('第二问')
    await complete(second, 4, '第二轮思考')
    await store.openSession('b')
    getMessages.mockResolvedValue([
      { id: 1, role: 'user', content: '第一问' },
      { id: 2, role: 'assistant', content: '回答', reply_to_message_id: 1 },
      { id: 3, role: 'user', content: '第二问' },
      { id: 4, role: 'assistant', content: '回答', reply_to_message_id: 3 },
    ])
    await store.openSession('s')
    expect(store.turns.map((turn) => turn.trace.reasoning)).toEqual(['第一轮思考', '第二轮思考'])
    expect(store.turns.every((turn) => !turn.live)).toBe(true)
  })

  it('keeps regeneration attached when history reloads during streaming', async () => {
    getMessages.mockResolvedValue([
      { id: 1, role: 'user', content: '历史问题' },
      { id: 2, role: 'assistant', content: '旧回答', reply_to_message_id: 1 },
    ])
    await store.loadHistory('s')
    const turn = store.turns[0]
    const replacement = regenerate(turn)
    replacement.stream.emit({ type: 'run_started', operation: 'regenerate', message_id: 2 })
    replacement.stream.emit({ type: 'text_delta', content: '生成中' })
    await store.loadHistory('s')
    expect(store.turns[0]).toBe(turn)
    expect(store.turns[0].assistant.text).toBe('生成中')
    await complete(replacement, 2, '新思考', '新的回答')
  })

  it('old regeneration cleanup cannot stop a newer attempt on the same turn', async () => {
    const first = await send()
    await complete(first, 2, '原思考', '原回答')
    const old = regenerate(first.turn)
    old.stream.emit({ type: 'run_started', operation: 'regenerate', message_id: 2 })
    store.stop()
    const current = regenerate(first.turn)
    current.stream.emit({ type: 'run_started', operation: 'regenerate', message_id: 2 })
    current.stream.emit({ type: 'reasoning_delta', content: '新尝试的思考' })
    current.stream.emit({ type: 'text_delta', content: '新尝试的回答' })
    old.stream.reject(new DOMException('Aborted', 'AbortError'))
    await old.promise
    expect(first.turn.assistant.text).toBe('新尝试的回答')
    expect(first.turn.assistant.streaming).toBe(true)
    expect(store.run.reasoning).toBe('新尝试的思考')
    await complete(current, 2, '完成', '新答案')
  })

  it('marks a stream that ends during reasoning as failed for that turn', async () => {
    const job = await send()
    job.stream.emit({ type: 'reasoning_delta', content: '未完成的思考' })
    job.stream.resolve()
    await job.promise
    expect(job.turn.trace.phase).toBe('failed')
    expect(job.turn.trace.reasoning).toBe('未完成的思考')
    expect(job.turn.assistant.streaming).toBe(false)
    const next = await send('重试')
    await complete(next, 4, '独立的新思考')
    expect(job.turn.trace.phase).toBe('failed')
  })

  it('cannot attach a delayed session creation to the next logged-in account', async () => {
    let resolve
    createSession.mockImplementationOnce(() => new Promise((done) => { resolve=done }))
    store.activeId=null
    const pending=store.send({text:'上一账号的问题'})
    jobs.push(pending)
    store.reset()
    resolve({id:'old-account-session'})
    await pending
    expect(store.activeId).toBeNull()
    expect(store.turns).toEqual([])
    expect(streamChat).not.toHaveBeenCalled()
  })
})
