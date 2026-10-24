import { describe, expect, it } from 'vitest'
import {
  dateBucket,
  formatBytes,
  formatDuration,
  formatNumber,
  plainText,
  relativeTime,
  shortDocTitle,
  truncate,
} from '../src/utils/format'

const NOW = new Date('2026-05-20T12:00:00+08:00')

describe('formatBytes', () => {
  it('uses binary units with one decimal for small values', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(947)).toBe('947 B')
    expect(formatBytes(1536)).toBe('1.5 KB')
    expect(formatBytes(22.8 * 1024)).toBe('22.8 KB')
  })

  it('falls back for non numeric input', () => {
    expect(formatBytes(null)).toBe('0 B')
    expect(formatBytes('abc')).toBe('—')
  })
})

describe('formatDuration', () => {
  it('renders milliseconds under one second', () => {
    expect(formatDuration(534)).toBe('534 毫秒')
    expect(formatDuration(0)).toBe('0 秒')
  })

  it('renders seconds and minutes', () => {
    expect(formatDuration(1000)).toBe('1.0 秒')
    expect(formatDuration(18400)).toBe('18 秒')
    expect(formatDuration(125000)).toBe('2 分 05 秒')
  })

  it('returns zero for missing values', () => {
    expect(formatDuration(null)).toBe('0 秒')
    expect(formatDuration(undefined)).toBe('0 秒')
  })
})

describe('formatNumber', () => {
  it('groups thousands', () => {
    expect(formatNumber(1759)).toBe('1,759')
    expect(formatNumber(54)).toBe('54')
  })
})

describe('relativeTime / dateBucket', () => {
  it('describes recent timestamps relative to now', () => {
    expect(relativeTime(new Date(NOW.getTime() - 30 * 1000), NOW)).toBe('刚刚')
    expect(relativeTime(new Date(NOW.getTime() - 5 * 60 * 1000), NOW)).toBe('5 分钟前')
    expect(relativeTime(new Date(NOW.getTime() - 3 * 3600 * 1000), NOW)).toBe('3 小时前')
    expect(relativeTime(new Date(NOW.getTime() - 4 * 86400 * 1000), NOW)).toBe('4 天前')
  })

  it('buckets by calendar day', () => {
    expect(dateBucket(new Date('2026-05-20T09:00:00+08:00'), NOW)).toBe('今天')
    expect(dateBucket(new Date('2026-05-19T09:00:00+08:00'), NOW)).toBe('昨天')
    expect(dateBucket(new Date('2026-05-18T09:00:00+08:00'), NOW)).toBe('本周')
    expect(dateBucket(new Date('2026-04-01T09:00:00+08:00'), NOW)).toBe('更早')
  })
})

describe('truncate / plainText / shortDocTitle', () => {
  it('truncates with an ellipsis only when needed', () => {
    expect(truncate('江西师范大学', 10)).toBe('江西师范大学')
    expect(truncate('江西师范大学校园知识库', 6)).toBe('江西师范大学…')
  })

  it('strips markdown noise for previews', () => {
    const source = '## 标题\n\n| 单位名称 | 办公电话 |\n| --- | --- |\n| 图书馆 | 88120630 |\n\n**加粗** [链接](https://example.com) `code`'
    const plain = plainText(source)
    expect(plain).not.toContain('#')
    expect(plain).not.toContain('|')
    expect(plain).not.toContain('**')
    expect(plain).not.toContain('https://example.com')
    expect(plain).toContain('图书馆')
    expect(plain).toContain('88120630')
  })

  it('shortens document titles for labels', () => {
    expect(shortDocTitle('江西师范大学 - 校园生活 - 官网.md')).toBe('江西师范大学 - 校园生活')
    expect(shortDocTitle('学生管理规定.doc')).toBe('学生管理规定')
    expect(shortDocTitle('江西师范大学学生表彰与奖励办法（修订）.docx')).toBe('江西师范大学学生表彰与奖励办法（修订）')
  })
})
