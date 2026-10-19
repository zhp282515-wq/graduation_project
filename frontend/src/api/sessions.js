import { apiFetch } from './client'

export const listSessions = () => apiFetch('/api/sessions')

export const createSession = () =>
  apiFetch('/api/sessions', { method: 'POST' })

export const getMessages = (sessionId) =>
  apiFetch(`/api/sessions/${sessionId}/messages`)

export const deleteSession = (sessionId) =>
  apiFetch(`/api/sessions/${sessionId}`, { method: 'DELETE' })