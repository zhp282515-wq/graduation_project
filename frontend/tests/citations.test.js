import { describe, expect, it } from 'vitest'
import { groupSources, normalizeSources, shortTitle, sourceKindLabel, sourceMeta, typeLabel } from '../src/utils/citations'

const knowledge = (over = {}) => ({
  id: 'knowledge:md5a:3',
  kind: 'knowledge',
  title: '江西师范大学学生表彰与奖励办法（修订）',
  file_md5: 'md5a',
  chunk_id: 'chunk-1',
  chunk_index: 3,
  file_type: 'docx',
  section_path: '第三章 > 奖学金',
  page: 2,
  text: '国家奖学金 8000 元/年',
  url: '',
  ...over,
})

describe('normalizeSources', () => {
  it('keeps the documented knowledge source shape', () => {
    const [item] = normalizeSources([knowledge()])
    expect(item).toMatchObject({
      id: 'knowledge:md5a:3',
      kind: 'knowledge',
      title: '江西师范大学学生表彰与奖励办法（修订）',
      fileMd5: 'md5a',
      chunkId: 'chunk-1',
      chunkIndex: 3,
      fileType: 'docx',
      sectionPath: '第三章 > 奖学金',
      page: 2,
    })
  })

  it('drops entries without identity and de-duplicates by id', () => {
    const items = normalizeSources([
      knowledge(),
      knowledge({ title: '重复的同一分片' }),
      { title: '没有 id' },
      null,
      'not-an-object',
    ])
    expect(items).toHaveLength(1)
  })

  it('rebuilds a stable id when the backend omitted it', () => {
    const [item] = normalizeSources([{ kind: 'knowledge', file_md5: 'm', chunk_index: 7, title: 'x' }])
    expect(item.id).toBe('knowledge:m:7')
  })

  it('keeps web sources with their url', () => {
    const [item] = normalizeSources([{ id: 'web:abc', kind: 'web', title: '校园网', url: 'https://www.jxnu.edu.cn/a', text: '正文' }])
    expect(item.kind).toBe('web')
    expect(item.url).toContain('jxnu.edu.cn')
    expect(item.chunkIndex).toBeNull()
  })

  it('rejects pages that are not positive integers', () => {
    const [item] = normalizeSources([knowledge({ page: 0 })])
    expect(item.page).toBeNull()
  })
})

describe('labels', () => {
  it('maps file types to human labels', () => {
    expect(typeLabel('md')).toBe('Markdown')
    expect(typeLabel('pdf')).toBe('PDF')
    expect(typeLabel('docx')).toBe('Word')
    expect(typeLabel('unknown')).toBe('unknown')
    expect(typeLabel('')).toBe('文档')
  })

  it('describes where a source came from', () => {
    expect(sourceKindLabel({ kind: 'knowledge' })).toBe('知识库')
    expect(sourceKindLabel({ kind: 'web' })).toBe('网页')
  })

  it('builds the sheet subtitle from real metadata only', () => {
    expect(sourceMeta(normalizeSources([knowledge()])[0])).toBe('Word · 第 2 页 · 分片 #3')
    expect(sourceMeta(normalizeSources([{ id: 'web:1', kind: 'web', url: 'https://www.jxnu.edu.cn/x' }])[0])).toBe('jxnu.edu.cn')
    expect(shortTitle({ title: '一二三四五六七八九十' }, 5)).toBe('一二三四五…')
  })
})

describe('groupSources', () => {
  it('groups knowledge chunks by document', () => {
    const sources = normalizeSources([
      knowledge(),
      knowledge({ id: 'knowledge:md5a:9', chunk_index: 9 }),
      knowledge({ id: 'knowledge:md5b:1', file_md5: 'md5b', chunk_index: 1, title: '另一篇' }),
    ])
    const groups = groupSources(sources)
    expect(groups).toHaveLength(2)
    expect(groups[0].items).toHaveLength(2)
    expect(groups[1].title).toBe('另一篇')
  })

  it('groups web sources by url', () => {
    const sources = normalizeSources([
      { id: 'web:a', kind: 'web', url: 'https://a.example/1', title: 'A' },
      { id: 'web:b', kind: 'web', url: 'https://a.example/2', title: 'A2' },
    ])
    expect(groupSources(sources)).toHaveLength(2)
  })
})
