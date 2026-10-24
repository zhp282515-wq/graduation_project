import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAtlasStore } from '../src/stores/atlas'

function point(id, md5, chunkIndex, text, extra = {}) {
  return {
    id,
    file_md5: md5,
    chunk_index: chunkIndex,
    x: chunkIndex,
    y: 0,
    z: 0,
    text,
    preview: text.slice(0, 20),
    section_path: `第 ${chunkIndex} 节`,
    block_type: 'text',
    page: null,
    chars: text.length,
    size: 1,
    ...extra,
  }
}

const DOCS = [
  { file_md5: 'md5a', file_name: '校园生活', file_type: 'md', chunk_count: 3, center: [0, 0, 0], radius: 10 },
  { file_md5: 'md5b', file_name: '学生管理规定', file_type: 'pdf', chunk_count: 2, center: [20, 0, 0], radius: 8 },
]

const POINTS = [
  point('p1', 'md5a', 0, '图书馆开放时间 周一至周日'),
  point('p2', 'md5a', 1, '食堂推荐 一食堂二楼'),
  point('p3', 'md5a', 2, '校医院 门诊时间'),
  point('p4', 'md5b', 0, '本科生可借 10 册图书'),
  point('p5', 'md5b', 1, '考试纪律与处分'),
]

describe('atlas store', () => {
  let atlas

  beforeEach(() => {
    setActivePinia(createPinia())
    atlas = useAtlasStore()
    atlas.documents = DOCS
    atlas.points = POINTS
    atlas.status = 'ready'
  })

  it('derives document lookup with stable hues', () => {
    expect(atlas.docById.size).toBe(2)
    expect(atlas.docById.get('md5a').hue).toBeTypeOf('number')
    expect(atlas.docById.get('md5a').index).toBe(0)
    expect(atlas.totalChunks).toBe(5)
    expect(atlas.loaded).toBe(true)
  })

  it('keeps full precision point identity, not sampled summaries', () => {
    const ids = atlas.points.map((item) => item.id)
    expect(new Set(ids).size).toBe(POINTS.length)
  })

  it('returns null when no filter is active so every star can render', () => {
    expect(atlas.filteredIds).toBeNull()
    expect(atlas.matchCount).toBe(5)
  })

  it('matches full text, section and document name on search', () => {
    atlas.setQuery('图书')
    expect([...atlas.filteredIds]).toEqual(['p1', 'p4'])
    expect(atlas.matchCount).toBe(2)
    expect(atlas.searchResults.map((item) => item.id)).toEqual(['p1', 'p4'])

    atlas.setQuery('学生管理规定')
    expect([...atlas.filteredIds]).toEqual(['p4', 'p5'])
  })

  it('combines document, type and keyword filters', () => {
    atlas.setDocFilter('md5a')
    expect(atlas.matchCount).toBe(3)

    atlas.setTypeFilter('pdf')
    expect(atlas.matchCount).toBe(0)

    atlas.clearFilters()
    atlas.setTypeFilter('pdf')
    expect([...atlas.filteredIds]).toEqual(['p4', 'p5'])
  })

  it('caps the visible search result list without dropping matches', () => {
    const many = Array.from({ length: 60 }, (_, i) => point(`m${i}`, 'md5a', i, `奖学金 条目 ${i}`))
    atlas.points = many
    atlas.setQuery('奖学金')
    expect(atlas.matchCount).toBe(60)
    expect(atlas.searchResults).toHaveLength(40)
  })

  it('builds real chunk-order chains per document', () => {
    const pairs = atlas.chainPairs
    expect(pairs.map(([a, b]) => `${a.id}->${b.id}`)).toEqual(['p1->p2', 'p2->p3', 'p4->p5'])
  })

  it('resolves semantic edges only when both ends exist', () => {
    atlas.byStarKey = new Map([
      ['md5a:0', POINTS[0]],
      ['md5b:0', POINTS[3]],
    ])
    atlas.edges = [
      { a: 'md5a:0', b: 'md5b:0', score: 0.81 },
      { a: 'md5a:0', b: 'missing:9', score: 0.9 },
    ]
    expect(atlas.edgesResolved).toHaveLength(1)
    expect(atlas.edgesResolved[0].from.id).toBe('p1')
  })

  it('exposes type facets sorted by frequency', () => {
    expect(atlas.typeOptions).toEqual([
      { key: 'md', count: 1 },
      { key: 'pdf', count: 1 },
    ])
  })

  it('clears data on reset and filters through clearFilters', () => {
    atlas.setQuery('图书')
    atlas.setDocFilter('md5a')
    atlas.select('p1')
    atlas.reset()
    expect(atlas.status).toBe('idle')
    expect(atlas.points).toEqual([])
    expect(atlas.documents).toEqual([])
    expect(atlas.selectedId).toBe('')

    atlas.clearFilters()
    expect(atlas.query).toBe('')
    expect(atlas.docFilter).toBe('')
    expect(atlas.typeFilter).toBe('')
  })
})
