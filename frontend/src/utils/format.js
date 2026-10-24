const pad = (value) => String(value).padStart(2, '0')

export function toDate(value) {
  if (!value) return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  const text = String(value)
  // 后端返回的是不带时区的本地时间（datetime.now().isoformat()），
  // 直接交给 Date 会被当作浏览器本地时间，这正是我们想要的。
  const date = new Date(text)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatClock(value) {
  const date = toDate(value)
  if (!date) return ''
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function formatStamp(value) {
  const date = toDate(value)
  if (!date) return ''
  return `${date.getFullYear()}.${pad(date.getMonth() + 1)}.${pad(date.getDate())} ${formatClock(date)}`
}

export function formatDate(value) {
  const date = toDate(value)
  if (!date) return ''
  return `${date.getFullYear()} 年 ${date.getMonth() + 1} 月 ${date.getDate()} 日`
}

const DAY = 86400000

export function dayKey(value) {
  const date = toDate(value)
  if (!date) return ''
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export function startOfDay(date = new Date()) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
}

/** 会话列表的日期分组，返回「今天 / 昨天 / 本周 / 更早」。 */
export function dateBucket(value, now = new Date()) {
  const date = toDate(value)
  if (!date) return '更早'
  const today = startOfDay(now)
  const stamp = startOfDay(date)
  if (stamp === today) return '今天'
  if (stamp === today - DAY) return '昨天'
  if (today - stamp < 7 * DAY) return '本周'
  return '更早'
}

export function relativeTime(value, now = new Date()) {
  const date = toDate(value)
  if (!date) return ''
  const diff = now.getTime() - date.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < DAY) return `${Math.floor(diff / 3600000)} 小时前`
  const bucket = dateBucket(date, now)
  if (bucket === '昨天') return '昨天'
  if (diff < 7 * DAY) return `${Math.floor(diff / DAY)} 天前`
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日`
}

export function formatBytes(bytes) {
  const size = Number(bytes)
  if (!Number.isFinite(size)) return '—'
  if (size <= 0) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`
}

export function formatDuration(ms) {
  const value = Number(ms)
  if (!Number.isFinite(value) || value <= 0) return '0 秒'
  if (value < 1000) return `${Math.round(value)} 毫秒`
  if (value < 60000) return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)} 秒`
  const minutes = Math.floor(value / 60000)
  const seconds = Math.round((value % 60000) / 1000)
  return `${minutes} 分 ${pad(seconds)} 秒`
}

export function formatNumber(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return number.toLocaleString('zh-CN')
}

export function truncate(text, limit = 48) {
  const raw = String(text ?? '').replace(/\s+/g, ' ').trim()
  if (raw.length <= limit) return raw
  return `${raw.slice(0, limit).trimEnd()}…`
}

/** 从 Markdown 里剥掉排版符号，给会话标题、引用摘要这类地方用。 */
export function plainText(markdown, limit = 0) {
  let text = String(markdown ?? '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^>\s?/gm, '')
    .replace(/^#{1,6}\s+/gm, '')
    // 表格分隔行（|---|:--:|）没有任何信息量，先整行丢掉
    .replace(/^[\s|:-]*-{3,}[\s|:-]*$/gm, ' ')
    // 表格竖线变成空格，避免摘要里出现 | 噪声
    .replace(/\s*\|\s*/g, ' ')
    .replace(/[*_~]{1,3}/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  if (limit > 0) text = truncate(text, limit)
  return text
}

/** 万用排序：有更新时间用更新时间，没有就退回创建时间。 */
export function sessionTimestamp(session) {
  return session?.updated_at || session?.created_at || ''
}

/** 文档名去掉扩展名与常见来源后缀，用于紧凑的列表与星图标签。 */
export function shortDocTitle(name, limit = 26) {
  let value = String(name || '').trim()
  if (!value) return '未命名文档'
  value = value.replace(/\.(md|markdown|txt|pdf|docx?)$/i, '')
  value = value.replace(/\s*[-—–_]\s*官网\s*$/u, '')
  if (value.length > limit) value = `${value.slice(0, limit)}…`
  return value
}