/**
 * SSE 解析。
 *
 * 后端的每个事件都是一行 `data: {json}`，json 里带 type 字段，事件之间用空行分隔；
 * 流里没有 `event:` 名字，也没有 [DONE] 哨兵，终止由 `done` / `run_failed` 事件表达。
 * 这里仍然按完整 SSE 规范解析（支持 event:/多行 data/注释），因为解析器一旦
 * 假定"每行一个 JSON"，遇到网络分片就只能在错误里挣扎。
 */

function frameHandler(onEvent) {
  return (frame) => {
    if (!frame.trim()) return
    const dataLines = []
    let eventName = ''
    for (const rawLine of frame.split('\n')) {
      const line = rawLine.replace(/\r$/, '')
      if (!line || line.startsWith(':')) continue
      const colon = line.indexOf(':')
      const field = colon === -1 ? line : line.slice(0, colon)
      let value = colon === -1 ? '' : line.slice(colon + 1)
      if (value.startsWith(' ')) value = value.slice(1)
      if (field === 'data') dataLines.push(value)
      else if (field === 'event') eventName = value.trim()
    }
    if (!dataLines.length) return
    const data = dataLines.join('\n')
    if (!data.trim()) return
    if (data === '[DONE]') {
      onEvent({ type: 'stream_closed' })
      return
    }
    let payload
    try {
      payload = JSON.parse(data)
    } catch (error) {
      onEvent({ type: 'unparsed', raw: data, error })
      return
    }
    if (payload && typeof payload === 'object' && !payload.type && eventName) {
      payload.type = eventName
    }
    onEvent(payload)
  }
}

/**
 * @param {ReadableStream<Uint8Array>} stream
 * @param {(event: Record<string, any>) => void} onEvent
 * @param {{ onDone?: () => void }} [options]
 */
export async function consumeSse(stream, onEvent, options = {}) {
  const handle = frameHandler(onEvent)
  const reader = stream.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let closed = false

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let index
      while ((index = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, index)
        buffer = buffer.slice(index + 2)
        handle(frame)
      }
    }
    buffer += decoder.decode()
    if (buffer.trim()) handle(buffer)
    closed = true
    options.onDone?.()
  } finally {
    try {
      await reader.cancel()
    } catch {
      // 连接已经出错时 cancel 也可能失败，保留原始异常。
    } finally {
      reader.releaseLock()
    }
  }

  return { closed }
}
