import { http } from './http'

export const feedbackCategories = {
  answer: '回答质量', knowledge: '知识库内容', bug: '功能异常', suggestion: '使用建议', other: '其他',
}
export const dislikeReasons = {
  inaccurate: '不准确', unresolved: '没解决问题', verbose: '太啰嗦', other: '其他',
}

export function rateAnswer(answer, vote) {
  return http.put(`/api/sessions/${encodeURIComponent(answer.sessionId)}/messages/${answer.id}/rating`, {
    revision: answer.revision, vote,
  })
}

export function submissionId() {
  // Web Crypto randomness also works on a campus LAN using plain HTTP.
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 15) | 64
  bytes[8] = (bytes[8] & 63) | 128
  const hex = Array.from(bytes, (n) => n.toString(16).padStart(2, '0')).join('')
  return [hex.slice(0,8), hex.slice(8,12), hex.slice(12,16), hex.slice(16,20), hex.slice(20)].join('-')
}
