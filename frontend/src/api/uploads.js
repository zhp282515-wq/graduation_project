import { uploadWithProgress } from './http'

/** 图片上限 10MB，与 api/main.py 的 /api/upload 校验一致。 */
export const MAX_IMAGE_BYTES = 10 * 1024 * 1024
export const IMAGE_ACCEPT = 'image/jpeg,image/png,image/gif,image/webp'
const IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp'])

export function checkImage(file) {
  if (!file) return '没有选择文件'
  if (!IMAGE_TYPES.has(file.type)) return `不支持的图片格式：${file.type || file.name}`
  if (file.size > MAX_IMAGE_BYTES) return '图片超过 10MB，请压缩后再上传'
  if (file.size === 0) return '图片是空文件'
  return null
}

/**
 * 上传后返回 { name, path, url }：
 * - path 形如 `data/uploads/<uuid><ext>`，是 /api/chat 里 images 字段要传的值；
 * - url 形如 `/uploads/<name>`，用于本地预览。
 */
export function uploadImage(file, { onProgress, signal } = {}) {
  const problem = checkImage(file)
  if (problem) return Promise.reject(new Error(problem))
  return uploadWithProgress('/api/upload', file, { onProgress, signal })
}
