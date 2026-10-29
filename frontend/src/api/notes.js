import { request } from './http'

/** 已保存笔记：与长期记忆同构，但笔记由用户主动创建，四条接口齐全。 */

export function listNotes(options = {}) {
  return request('/api/notes', options)
}

export function getNote(id, options = {}) {
  return request(`/api/notes/${encodeURIComponent(id)}`, options)
}

export function createNote({ title, content, sourceSessionId = null }, options = {}) {
  return request('/api/notes', {
    method: 'POST',
    body: { title, content, source_session_id: sourceSessionId },
    ...options,
  })
}

export function updateNote(id, { title, content }, options = {}) {
  return request(`/api/notes/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: { title, content },
    ...options,
  })
}

export function deleteNote(id, options = {}) {
  return request(`/api/notes/${encodeURIComponent(id)}`, { method: 'DELETE', ...options })
}
