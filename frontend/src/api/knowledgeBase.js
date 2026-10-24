import { request, uploadWithProgress } from './http'

/**
 * 知识库。契约见 api/main.py：
 * - 列表分页 page_size 1..50，sort 取 uploaded|name，facets 与列表同参返回；
 * - 分片分页 page_size 1..100，chunk 里带 chunk_index/chunk_id/text/section_path/page/block_type/char_count；
 * - 上传是 202 + 后台任务，前端用 /jobs/{md5} 轮询；
 * - 同步返回 { scanned, upserted, removed }。
 */

export const MAX_DOC_BYTES = 50 * 1024 * 1024
export const DOC_ACCEPT = '.md,.txt,.pdf,.doc,.docx'
const DOC_EXT = new Set(['md', 'txt', 'pdf', 'doc', 'docx'])

export function docExtension(name) {
  const index = String(name || '').lastIndexOf('.')
  return index === -1 ? '' : String(name).slice(index + 1).toLowerCase()
}

export function checkDocument(file) {
  if (!file) return '没有选择文件'
  const ext = docExtension(file.name)
  if (!DOC_EXT.has(ext)) return `不支持的文档类型：.${ext || '未知'}（仅支持 md / txt / pdf / doc / docx）`
  if (file.size > MAX_DOC_BYTES) return '文档超过 50MB，请拆分后再上传'
  if (file.size === 0) return '文件为空'
  return null
}

export function listDocuments({ q = '', type = '', page = 1, pageSize = 10, sort = 'uploaded', signal } = {}) {
  return request('/api/knowledge/documents', {
    query: { q, type, page, page_size: pageSize, sort },
    signal,
  })
}

/** 全库聚合：{ documents, chunks, ready, processing, pending, failed, bytes, latest_at, facets } */
export function getKnowledgeOverview({ signal } = {}) {
  return request('/api/knowledge/overview', { signal })
}

export function getDocumentChunks(fileMd5, { page = 1, pageSize = 20, signal } = {}) {
  return request(`/api/knowledge/documents/${encodeURIComponent(fileMd5)}/chunks`, {
    query: { page, page_size: pageSize },
    signal,
  })
}

export function getIngestJob(fileMd5, { signal } = {}) {
  return request(`/api/knowledge/jobs/${encodeURIComponent(fileMd5)}`, { signal })
}

export function syncKnowledge({ signal } = {}) {
  return request('/api/knowledge/sync', { method: 'POST', signal })
}

export function deleteDocument(fileMd5, { signal } = {}) {
  return request(`/api/knowledge/documents/${encodeURIComponent(fileMd5)}`, {
    method: 'DELETE',
    signal,
  })
}

/** 上传返回 { file_md5, file_name, status:'pending' }，随后由后台 run_ingest_job 推进状态。 */
export function uploadDocument(file, { title = '', onProgress, signal } = {}) {
  const problem = checkDocument(file)
  if (problem) return Promise.reject(new Error(problem))
  return uploadWithProgress('/api/knowledge/upload', file, {
    fields: { title },
    onProgress,
    signal,
  })
}

export function getStarMap({ force = false, signal } = {}) {
  return request('/api/knowledge/starmap', { query: { force: force ? 'true' : '' }, signal })
}

export function getStarMapPoints({ offset = 0, limit = 400, force = false, signal } = {}) {
  return request('/api/knowledge/starmap/points', {
    query: { offset, limit, force: force ? 'true' : '' },
    signal,
  })
}

export function getStarMapEdges({ limit = 900, force = false, signal } = {}) {
  return request('/api/knowledge/starmap/edges', {
    query: { limit, force: force ? 'true' : '' },
    signal,
  })
}
