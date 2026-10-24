import { normalizeSources } from './citations'

/**
 * 历史消息 → 问答对。
 *
 * 后端只落两类行（session/repository.py）：
 * - user：正文 + images（形如 data/uploads/xxx.png 的相对路径）
 * - assistant：正文 + sources + token_usage + reply_to_message_id → 指回对应的 user 行
 * 失败的轮次不会落库，因此成对关系只能靠 reply_to_message_id 与插入顺序重建。
 */

export function imageUrl(path) {
  const text = String(path || '')
  if (!text) return ''
  if (/^(https?:|data:|\/uploads\/)/.test(text)) return text
  const name = text.split('/').pop()
  return name ? `/uploads/${name}` : ''
}

function readImages(value) {
  if (!Array.isArray(value)) return []
  return value.filter((item) => typeof item === 'string' && item.trim())
}

function readTokenTotal(usage) {
  if (!usage || typeof usage !== 'object') return null
  const total = usage.total_tokens ?? usage.total
  if (Number.isFinite(total)) return Number(total)
  const parts = ['prompt_tokens', 'completion_tokens']
    .map((key) => Number(usage[key]))
    .filter((value) => Number.isFinite(value))
  return parts.length ? parts.reduce((sum, value) => sum + value, 0) : null
}

export function buildTurns(messages) {
  const turns = []
  const pending = new Map()
  let index = 0

  for (const message of Array.isArray(messages) ? messages : []) {
    if (!message || !message.role) continue
    if (message.role === 'user') {
      index += 1
      const turn = {
        key: `turn-${message.id ?? index}`,
        index,
        userId: message.id ?? null,
        userText: message.content || '',
        images: readImages(message.images).map(imageUrl),
        createdAt: message.created_at || '',
        assistant: null,
      }
      turns.push(turn)
      if (message.id !== undefined && message.id !== null) pending.set(message.id, turn)
      continue
    }
    if (message.role !== 'assistant') continue

    const target =
      pending.get(message.reply_to_message_id) ||
      [...turns].reverse().find((turn) => !turn.assistant) ||
      null
    const assistant = {
      id: message.id ?? null,
      text: message.content || '',
      sources: normalizeSources(message.sources),
      tokenTotal: readTokenTotal(message.token_usage),
      createdAt: message.created_at || '',
      canRegenerate: Boolean(message.reply_to_message_id),
    }
    if (target && !target.assistant) {
      target.assistant = assistant
    } else {
      // 找不到提问的孤儿回复也要显示，不能悄悄吞掉真实历史。
      index += 1
      turns.push({
        key: `turn-${message.id ?? index}`,
        index,
        userId: null,
        userText: '',
        images: [],
        createdAt: '',
        assistant,
      })
    }
  }

  return turns
}

/** 会话标题：后端已截到 30 字，这里只兜底空标题。 */
export function sessionTitle(session) {
  const title = String(session?.title || '').trim()
  return title || '新会话'
}
