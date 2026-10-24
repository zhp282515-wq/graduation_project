import { describe, expect, it } from 'vitest'
import { buildTurns, imageUrl, sessionTitle } from '../src/utils/history'

const user = (id, content, extra = {}) => ({
  id,
  role: 'user',
  content,
  created_at: '2026-05-20T10:00:00',
  ...extra,
})

const assistant = (id, content, extra = {}) => ({
  id,
  role: 'assistant',
  content,
  created_at: '2026-05-20T10:00:20',
  ...extra,
})

describe('buildTurns', () => {
  it('pairs answers through reply_to_message_id', () => {
    const turns = buildTurns([
      user(1, '图书馆开放时间'),
      assistant(2, '周一至周日 8:00-22:00', { reply_to_message_id: 1 }),
      user(3, '那借阅规则呢？'),
      assistant(4, '本科生可借 10 册', { reply_to_message_id: 3 }),
    ])

    expect(turns).toHaveLength(2)
    expect(turns[0].userText).toBe('图书馆开放时间')
    expect(turns[0].assistant.text).toContain('8:00-22:00')
    expect(turns[0].assistant.canRegenerate).toBe(true)
    expect(turns[1].assistant.text).toContain('10 册')
  })

  it('keeps a failed turn (user message without answer) as a turn', () => {
    const turns = buildTurns([user(1, '问题一'), assistant(2, '回答一', { reply_to_message_id: 1 }), user(3, '问题二')])
    expect(turns).toHaveLength(2)
    expect(turns[1].assistant).toBeNull()
    expect(turns[1].userText).toBe('问题二')
  })

  it('does not swallow orphan assistant messages', () => {
    const turns = buildTurns([assistant(99, '没有对应提问的回复', { reply_to_message_id: 42 })])
    expect(turns).toHaveLength(1)
    expect(turns[0].userText).toBe('')
    expect(turns[0].assistant.text).toBe('没有对应提问的回复')
  })

  it('maps stored image paths to the public upload route', () => {
    const turns = buildTurns([user(1, '看图', { images: ['data/uploads/abc123.png', '/uploads/def.png', ''] })])
    expect(turns[0].images).toEqual(['/uploads/abc123.png', '/uploads/def.png'])
  })

  it('reads token usage from either shape', () => {
    const turns = buildTurns([
      user(1, 'q'),
      assistant(2, 'a', { reply_to_message_id: 1, token_usage: { total_tokens: 24851 } }),
      user(3, 'q2'),
      assistant(4, 'a2', { reply_to_message_id: 3, token_usage: { prompt_tokens: 10, completion_tokens: 5 } }),
    ])
    expect(turns[0].assistant.tokenTotal).toBe(24851)
    expect(turns[1].assistant.tokenTotal).toBe(15)
  })

  it('normalizes sources and drops entries without an id', () => {
    const turns = buildTurns([
      user(1, 'q'),
      assistant(2, 'a', {
        reply_to_message_id: 1,
        sources: [
          { id: 'knowledge:md5:3', kind: 'knowledge', title: '学生手册', file_md5: 'md5', chunk_index: 3 },
          { title: '没有 id 的条目' },
        ],
      }),
    ])
    expect(turns[0].assistant.sources).toHaveLength(1)
    expect(turns[0].assistant.sources[0].title).toBe('学生手册')
  })

  it('tolerates empty input', () => {
    expect(buildTurns(null)).toEqual([])
    expect(buildTurns([])).toEqual([])
    expect(buildTurns([{ role: 'system', content: 'ignored' }])).toEqual([])
  })
})

describe('imageUrl', () => {
  it('passes absolute urls through and rewrites relative ones', () => {
    expect(imageUrl('https://a.example/x.png')).toBe('https://a.example/x.png')
    expect(imageUrl('data:image/png;base64,AAA')).toContain('data:image')
    expect(imageUrl('/uploads/x.png')).toBe('/uploads/x.png')
    expect(imageUrl('data/uploads/x.png')).toBe('/uploads/x.png')
    expect(imageUrl('')).toBe('')
  })
})

describe('sessionTitle', () => {
  it('falls back to the default title', () => {
    expect(sessionTitle({ title: '学校有哪些奖学金' })).toBe('学校有哪些奖学金')
    expect(sessionTitle({ title: '   ' })).toBe('新会话')
    expect(sessionTitle(null)).toBe('新会话')
  })
})
