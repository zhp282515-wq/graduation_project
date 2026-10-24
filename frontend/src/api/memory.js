import { request } from './http'

/**
 * 长期记忆。后端只有列表 / 改写 / 删除三条接口（记忆由 BackgroundTasks 自动抽取，
 * 前端不负责创建），改写与删除都返回真实结果：{ ...memory } / { deleted: id }。
 */

export function listMemories(options = {}) {
  return request('/api/memories', options)
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
