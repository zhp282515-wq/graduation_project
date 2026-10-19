// 登录功能做好之前，先写死一个用户
export const USER_ID = 'user_001'

export async function apiFetch(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      'x-user-id': USER_ID,
      'Content-Type': 'application/json',
      ...options.headers,
    },
  })

  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* 响应体不是 JSON，保持原样 */ }
    throw new Error(detail)
  }
  return res.json()
}

/** 上传图片。不能用 apiFetch：multipart 的 Content-Type 必须由浏览器自动生成边界。 */
export async function uploadImage(file) {
  const form = new FormData()
  form.append('file', file)

  const res = await fetch('/api/upload', {
    method: 'POST',
    headers: { 'x-user-id': USER_ID },
    body: form,
  })

  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch { /* 忽略 */ }
    throw new Error(detail)
  }
  return res.json()
}