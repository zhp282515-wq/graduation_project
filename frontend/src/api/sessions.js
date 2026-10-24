import { http, request } from './http'

/**
 * 会话与消息。后端契约见 api/main.py 与 session/service.py：
 * - 列表 / 创建 / 删除 / 历史都不需要 body；
 * - 历史按 id 升序，消息内含 sources（后端规范化的引用快照）与 reply_to_message_id；
 * - 重新生成的目标是 **assistant** 消息 id，后端按 reply_to_message_id 找回原问题。
 */

export function listSessions(options = {}) {
  return request('/api/sessions', options)
}

export function createSession(options = {}) {
  return request('/api/sessions', { method: 'POST', ...options })
}

export function deleteSession(sessionId, options = {}) {
  return request(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
    ...options,
  })
}

export function getMessages(sessionId, options = {}) {
  return request(`/api/sessions/${encodeURIComponent(sessionId)}/messages`, options)
}

export { http }
