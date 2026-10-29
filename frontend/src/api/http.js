/** Cookie authentication and cancellation across account boundaries. */
let csrfToken = ''
let identityEpoch = 0
const pending = new Set()
export function setCsrfToken(value) { csrfToken = value || '' }
export function invalidateRequests() {
  identityEpoch++
  for (const controller of pending) controller.abort()
  pending.clear()
}
function authExpired() {
  if (typeof window !== 'undefined' && window.dispatchEvent) window.dispatchEvent(new Event('auth-expired'))
}
function aborted() { return Object.assign(new Error('账号已切换或请求已取消'), { name: 'AbortError' }) }
export function finishResponse(response) { response?.releaseRequest?.() }

export class ApiError extends Error {
  constructor(message, { status = 0, url = '', detail = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.url = url
    this.detail = detail
  }
}

export function isAbortError(error) {
  return Boolean(error) && (error.name === 'AbortError' || error.code === 20)
}

/** 把后端 detail 归一成一句人话。 */
function readDetail(payload, fallback) {
  if (!payload) return fallback
  if (typeof payload === 'string') return payload
  if (typeof payload.detail === 'string') return payload.detail
  if (Array.isArray(payload.detail)) {
    const parts = payload.detail
      .map((item) => item?.msg ?? item?.message ?? JSON.stringify(item))
      .filter(Boolean)
    if (parts.length) return parts.join('；')
  }
  if (typeof payload.message === 'string') return payload.message
  return fallback
}

export function buildQuery(query) {
  if (!query) return ''
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    params.set(key, String(value))
  }
  const text = params.toString()
  return text ? `?${text}` : ''
}

async function parseBody(response) {
  const type = response.headers.get('content-type') || ''
  if (type.includes('application/json')) {
    try {
      return await response.json()
    } catch {
      return null
    }
  }
  try {
    return await response.text()
  } catch {
    return null
  }
}

/**
 * @param {string} path
 * @param {{
 *   method?: string, query?: Record<string, unknown>, body?: unknown,
 *   headers?: Record<string, string>, signal?: AbortSignal, raw?: boolean,
 * }} [options]
 */
export async function request(path, options = {}) {
  const { method = 'GET', query, body, headers = {}, signal, raw = false, publicRequest = false } = options
  const epoch = identityEpoch
  const controller = new AbortController()
  const cancel = () => controller.abort()
  if (signal?.aborted) throw aborted()
  signal?.addEventListener('abort', cancel, { once: true })
  pending.add(controller)
  const release = () => { pending.delete(controller); signal?.removeEventListener('abort', cancel) }
  const url = `${path}${buildQuery(query)}`
  const init = { method, signal: controller.signal, credentials: 'same-origin', headers: { ...headers } }
  if (csrfToken && !['GET', 'HEAD'].includes(method)) init.headers['X-CSRF-Token'] = csrfToken

  if (body instanceof FormData) {
    // 交给浏览器自己带 boundary，手写 Content-Type 会导致解析失败。
    init.body = body
  } else if (body !== undefined && body !== null) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }

  let response
  try {
    response = await fetch(url, init)
  } catch (error) {
    release()
    if (isAbortError(error)) throw error
    throw new ApiError('网络不可达，请检查后端服务是否在运行', { url, detail: error?.message })
  }

  if (epoch !== identityEpoch) { release(); throw aborted() }
  if (!response.ok) {
    release()
    if (response.status === 401 && !publicRequest) authExpired()
    const payload = await parseBody(response)
    const fallback = `请求失败（HTTP ${response.status}）`
    throw new ApiError(readDetail(payload, fallback), {
      status: response.status,
      url,
      detail: payload,
    })
  }

  if (raw) { response.releaseRequest = release; return response }
  try {
    const payload = response.status === 204 ? null : await parseBody(response)
    if (epoch !== identityEpoch) throw aborted()
    return payload
  } finally { release() }
}

export const http = {
  get: (path, options) => request(path, { ...options, method: 'GET' }),
  post: (path, body, options) => request(path, { ...options, method: 'POST', body }),
  put: (path, body, options) => request(path, { ...options, method: 'PUT', body }),
  del: (path, options) => request(path, { ...options, method: 'DELETE' }),
}

/**
 * 带进度的上传。知识库文档最大 50MB，图片最大 10MB，用 XHR 才有
 * `upload.onprogress`；fetch 目前拿不到上传进度。
 *
 * @returns {Promise<any>} 与 http.post 相同的 JSON 结果
 */
export function uploadWithProgress(path, file, { fields = {}, onProgress, signal } = {}) {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    for (const [key, value] of Object.entries(fields)) {
      if (value !== undefined && value !== null && value !== '') form.append(key, value)
    }
    form.append('file', file, file.name)

    const xhr = new XMLHttpRequest()
    xhr.open('POST', path, true)
    const epoch = identityEpoch
    const controller = { abort: () => xhr.abort() }
    pending.add(controller)
    xhr.withCredentials = true
    if (csrfToken) xhr.setRequestHeader('X-CSRF-Token', csrfToken)
    xhr.responseType = 'text'

    const abort = () => xhr.abort()
    if (signal) {
      if (signal.aborted) {
        pending.delete(controller)
        reject(Object.assign(new Error('已取消'), { name: 'AbortError' }))
        return
      }
      signal.addEventListener('abort', abort, { once: true })
    }

    const cleanup = () => {
      pending.delete(controller)
      if (signal) signal.removeEventListener('abort', abort)
    }

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || !onProgress) return
      onProgress({
        loaded: event.loaded,
        total: event.total,
        ratio: event.total ? event.loaded / event.total : 0,
      })
    }

    xhr.onerror = () => {
      cleanup()
      reject(new ApiError('上传中断：网络异常', { status: 0, url: path }))
    }

    xhr.onabort = () => {
      cleanup()
      reject(Object.assign(new Error('上传已取消'), { name: 'AbortError' }))
    }

    xhr.onload = () => {
      cleanup()
      if (epoch !== identityEpoch) { reject(aborted()); return }
      if (xhr.status === 401) authExpired()
      let payload = null
      try {
        payload = xhr.responseText ? JSON.parse(xhr.responseText) : null
      } catch {
        payload = xhr.responseText
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload)
        return
      }
      reject(
        new ApiError(readDetail(payload, `上传失败（HTTP ${xhr.status}）`), {
          status: xhr.status,
          url: path,
          detail: payload,
        }),
      )
    }

    xhr.send(form)
  })
}
