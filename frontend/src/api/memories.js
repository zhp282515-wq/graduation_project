import { apiFetch } from './client'

export const listMemories = () => apiFetch('/api/memories')

export const updateMemory = (id, content) =>
  apiFetch(`/api/memories/${id}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  })

export const deleteMemory = (id) =>
  apiFetch(`/api/memories/${id}`, { method: 'DELETE' })
