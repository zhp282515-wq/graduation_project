import { describe, expect, it } from 'vitest'
import { consumeSse } from '../src/api/sse'

function streamOf(chunks, { failAfter = -1 } = {}) {
  const encoder = new TextEncoder()
  let index = 0
  return new ReadableStream({
    pull(controller) {
      if (failAfter >= 0 && index > failAfter) {
        controller.error(new Error('network down'))
        return
      }
      if (index >= chunks.length) {
        if (failAfter >= 0) {
          controller.error(new Error('network down'))
          return
        }
        controller.close()
        return
      }
      controller.enqueue(encoder.encode(chunks[index]))
      index += 1
    },
  })
}

async function collect(chunks, options) {
  const events = []
  const result = await consumeSse(streamOf(chunks), (event) => events.push(event), options)
  return { events, result }
}

describe('consumeSse', () => {
  it('parses one JSON payload per frame', async () => {
    const { events, result } = await collect([
      'data: {"type":"run_started","session_id":"s1"}\n\n',
      'data: {"type":"text_delta","content":"你好"}\n\n',
      'data: {"type":"done","final_answer":{"content":"你好"}}\n\n',
    ])
    expect(events.map((event) => event.type)).toEqual(['run_started', 'text_delta', 'done'])
    expect(events[1].content).toBe('你好')
    expect(result.closed).toBe(true)
  })

  it('reassembles frames split across network chunks', async () => {
    const { events } = await collect([
      'data: {"type":"text_',
      'delta","content":"分片"}',
      '\n\ndata: {"type":"text_delta","content":"拼接"}\n\n',
    ])
    expect(events).toHaveLength(2)
    expect(events[0].content).toBe('分片')
    expect(events[1].content).toBe('拼接')
  })

  it('keeps a trailing frame that arrives without the blank line', async () => {
    const { events, result } = await collect(['data: {"type":"run_failed","message":"boom"}'])
    expect(events).toHaveLength(1)
    expect(events[0].message).toBe('boom')
    expect(result.closed).toBe(true)
  })

  it('ignores comments, empty data and heartbeats', async () => {
    const { events } = await collect([': keep-alive\n\n', 'data:\n\n', 'data: {"type":"text_delta","content":"x"}\n\n'])
    expect(events).toHaveLength(1)
  })

  it('supports multi-line data and named events', async () => {
    const { events } = await collect(['event: custom\ndata: {"a":1,\ndata: "b":2}\n\n'])
    expect(events[0]).toEqual({ a: 1, b: 2, type: 'custom' })
  })

  it('reports unparsable payloads instead of throwing', async () => {
    const { events } = await collect(['data: {oops\n\n'])
    expect(events[0].type).toBe('unparsed')
    expect(events[0].raw).toBe('{oops')
  })

  it('turns the [DONE] sentinel into stream_closed', async () => {
    const { events } = await collect(['data: [DONE]\n\n'])
    expect(events[0]).toEqual({ type: 'stream_closed' })
  })

  it('calls onDone and cancels the reader', async () => {
    let done = 0
    const { result } = await collect(['data: {"type":"done"}\n\n'], { onDone: () => (done += 1) })
    expect(done).toBe(1)
    expect(result.closed).toBe(true)
  })

  it('propagates read errors so the caller can show a retry state', async () => {
    const encoder = new TextEncoder()
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"type":"text_delta","content":"半"}'))
        setTimeout(() => controller.error(new Error('network down')), 0)
      },
    })
    const events = []
    await expect(consumeSse(stream, (event) => events.push(event))).rejects.toThrow('network down')
    expect(events).toEqual([])
  })
})
