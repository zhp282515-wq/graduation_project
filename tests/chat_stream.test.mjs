import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'
import { streamChat } from '../frontend/src/api/chat.js'

const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })

function serve(chunks) {
  globalThis.fetch = async () => new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk)
      controller.close()
    },
  }), { status: 200 })
}

function text(source) {
  serve([new TextEncoder().encode(source)])
}

function run(onEvent = () => {}) {
  return streamChat({ sessionId: 's', text: '问题', onEvent })
}

test('parses split UTF-8 and fragmented SSE frames', async () => {
  const data = new TextEncoder().encode('data: {"type":"text_delta","content":"你好"}\n\ndata: {"type":"done"}\n\n')
  serve(Array.from(data, byte => new Uint8Array([byte])))
  const events = []
  await run(event => events.push(event))
  assert.deepEqual(events, [{ type: 'text_delta', content: '你好' }, { type: 'done' }])
})

test('rejects EOF without a terminal event', async () => {
  text('data: {"type":"text_delta","content":"半截"}\n\n')
  await assert.rejects(run(), /未收到对话完成结果/)
})

test('run_failed is a valid terminal event', async () => {
  text('data: {"type":"run_failed","message":"失败"}\n\n')
  const events = []
  await run(event => events.push(event))
  assert.equal(events[0].type, 'run_failed')
})

test('malformed JSON fails explicitly', async () => {
  text('data: broken\n\n')
  await assert.rejects(run(), /无法解析的对话事件/)
})

test('callback errors propagate with original identity', async () => {
  text('data: {"type":"done"}\n\n')
  const error = new Error('UI handler failed')
  await assert.rejects(run(() => { throw error }), candidate => candidate === error)
})

test('duplicate terminals are rejected', async () => {
  text('data: {"type":"done"}\n\ndata: {"type":"run_failed"}\n\n')
  await assert.rejects(run(), /结束后仍收到事件/)
})

test('HTTP 409 preserves busy message', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: '正在生成，请结束后重试' }), { status: 409 })
  await assert.rejects(run(), /正在生成，请结束后重试/)
})

test('network read errors are not masked by cancel errors', async () => {
  const error = new Error('network read failure')
  globalThis.fetch = async () => new Response(new ReadableStream({ start(controller) { controller.error(error) } }))
  await assert.rejects(run(), candidate => candidate === error)
})
