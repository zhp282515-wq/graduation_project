import { request, finishResponse } from './http'
import { consumeSse } from './sse'

/**
 * 对话流。后端把 SSE 直接写在 POST /api/chat 的响应体里，事件类型：
 * run_started / reasoning_delta / text_delta / tool_call /
 * tool_started / tool_finished / done / run_failed。
 */
export async function streamChat({
  sessionId,
  text,
  images = [],
  reasoning = null,
  signal,
  onEvent,
}) {
  const response = await request('/api/chat', {
    method: 'POST',
    body: { session_id: sessionId, text, images, reasoning },
    signal,
    raw: true,
  })
  if (!response.body) throw new Error('浏览器不支持流式响应')
  try { await consumeSse(response.body, onEvent) } finally { finishResponse(response) }
}

/**
 * 重新生成。messageId 必须是 **assistant** 消息 id：后端用 reply_to_message_id
 * 找回原问题，再以 prefix 历史重跑；无法关联时返回 422。
 */
export async function regenerateChat({ sessionId, messageId, signal, onEvent }) {
  const path = `/api/sessions/${encodeURIComponent(sessionId)}/messages/${encodeURIComponent(
    messageId,
  )}/regenerate`
  const response = await request(path, { method: 'POST', signal, raw: true })
  if (!response.body) throw new Error('浏览器不支持流式响应')
  try { await consumeSse(response.body, onEvent) } finally { finishResponse(response) }
}
