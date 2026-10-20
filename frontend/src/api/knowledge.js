import { apiFetch, USER_ID } from './client'

export const listKnowledgeDocuments = ({ q = '', type = '', page = 1, pageSize = 10, sort = 'uploaded' } = {}) => {
  const p = new URLSearchParams({ q, page, page_size: pageSize, sort })
  if (type) p.set('type', type)
  return apiFetch(`/api/knowledge/documents?${p}`)
}

export const listKnowledgeChunks = (md5, { page = 1, pageSize = 20 } = {}) =>
  apiFetch(`/api/knowledge/documents/${md5}/chunks?page=${page}&page_size=${pageSize}`)

export const deleteKnowledgeDocument = (md5) =>
  apiFetch(`/api/knowledge/documents/${md5}`, { method: 'DELETE' })

export const getKnowledgeJob = (md5) => apiFetch(`/api/knowledge/jobs/${md5}`)

export const syncKnowledge = () => apiFetch('/api/knowledge/sync', { method: 'POST' })

/**
 * 上传文档。用 XHR 而不是 fetch：fetch 拿不到上传进度。
 * 不设 Content-Type —— 浏览器会自动加 multipart 边界。
 */
export function uploadKnowledgeDocument(file, { title, onProgress } = {}) {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    form.append('file', file)
    if (title) form.append('title', title)

    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/knowledge/upload')
    xhr.setRequestHeader('x-user-id', USER_ID)

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(e.loaded, e.total)
    }
    xhr.onload = () => {
      let body = null
      try { body = JSON.parse(xhr.responseText) } catch { /* 非 JSON 响应 */ }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body)
      } else {
        reject(new Error(body?.detail ? String(body.detail) : `HTTP ${xhr.status}`))
      }
    }
    xhr.onerror = () => reject(new Error('网络错误'))
    xhr.send(form)
  })
}
