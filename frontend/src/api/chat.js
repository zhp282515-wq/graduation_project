import { USER_ID } from './client.js'

export async function streamChat({ sessionId, text, images = [], reasoning = null, onEvent, signal }) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'x-user-id': USER_ID },
    body: JSON.stringify({ session_id: sessionId, text, images, reasoning }),
    signal,
  })

  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body.detail) detail = body.detail
    } catch { /* 忽略 */ }
    throw new Error(detail)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let terminal = false

  const flush = (chunk) => {
    for (const line of chunk.split('\n')) {
      if (!line.startsWith('data: ')) continue
      let event
      try {
        event = JSON.parse(line.slice(6))
      } catch (cause) {
        throw new Error('收到无法解析的对话事件', { cause })
      }
      if (terminal) throw new Error('对话结束后仍收到事件')
      if (event.type === 'done' || event.type === 'run_failed') terminal = true
      onEvent(event)
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

    // SSE 以空行分隔事件，最后一段可能不完整，留在 buffer 里
      const parts = buffer.split('\n\n')
      buffer = parts.pop()
      parts.forEach(flush)
    }
    buffer += decoder.decode()
    if (buffer.trim()) flush(buffer)
    if (!terminal) throw new Error('连接已中断，未收到对话完成结果，请稍后重试')
  } finally {
    try {
      await reader.cancel()
    } catch {
      // 网络已经报错时，取消读取也可能失败，保留原始异常。
    } finally {
      reader.releaseLock()
    }
  }
}
