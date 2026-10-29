import { request } from './http'

/**
 * 长期记忆。列表 / 新建 / 改写 / 删除都按当前登录账号隔离：新建只传内容，
 * user_id 由后端从会话里取；改写与删除命中别人的一律 404。
 */

export function listMemories(options = {}) {
  return request('/api/memories', options)
}

export function createMemory(content, options = {}) {
  return request('/api/memories', { method: 'POST', body: { content }, ...options })
}

export function updateMemory(id, content, options = {}) {
  return request(`/api/memories/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: { content },
    ...options,
  })
}

export function deleteMemory(id, options = {}) {
  return request(`/api/memories/${encodeURIComponent(id)}`, { method: 'DELETE', ...options })
}
