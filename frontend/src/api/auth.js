import { request } from './http'

export const getIdentity = () => request('/api/auth/me', { publicRequest: true })
export const signIn = (body) => request('/api/auth/login', { method: 'POST', body, publicRequest: true })
export const signUp = (body) => request('/api/auth/register', { method: 'POST', body, publicRequest: true })
export const signOut = () => request('/api/auth/logout', { method: 'POST' })
export const changePassword = (body) => request('/api/auth/password', { method: 'POST', body })
