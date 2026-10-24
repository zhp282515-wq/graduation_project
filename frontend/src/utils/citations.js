/**
 * 引用快照的整理。
 *
 * 数据来源只有一个：后端 session/sources.py 的 normalize_sources()。
 * - knowledge: { id, kind:'knowledge', title, file_md5, chunk_id, chunk_index,
 *               file_type, section_path, page, text, url }
 * - web:       { id, kind:'web', title, url, text }
 *
 * 前端绝不臆造引用：拿不到 id 的条目直接丢弃，展示不出处的东西没有意义。
 */

const TYPE_LABEL = { md: 'Markdown', doc: 'Word 97', docx: 'Word', pdf: 'PDF', txt: '文本' }

export function normalizeSources(list) {
  if (!Array.isArray(list)) return []
  const seen = new Set()
  const items = []
  for (const raw of list) {
    if (!raw || typeof raw !== 'object') continue
    const kind = raw.kind || (raw.file_md5 ? 'knowledge' : raw.url ? 'web' : '')
    const id = raw.id || (kind === 'knowledge' ? `knowledge:${raw.file_md5}:${raw.chunk_index}` : '')
    if (!id || seen.has(id)) continue
    seen.add(id)
    items.push({
      id,
      kind,
      title: raw.title || raw.file_name || raw.url || '未命名来源',
      fileMd5: raw.file_md5 || '',
      chunkId: raw.chunk_id || '',
      chunkIndex: Number.isFinite(raw.chunk_index) ? raw.chunk_index : null,
      fileType: raw.file_type || '',
      sectionPath: raw.section_path || '',
      page: Number.isFinite(raw.page) && raw.page > 0 ? raw.page : null,
      text: raw.text || '',
      url: raw.url || '',
    })
  }
  return items
}

export function typeLabel(fileType) {
  return TYPE_LABEL[String(fileType || '').toLowerCase()] || String(fileType || '文档')
}

export function sourceKindLabel(source) {
  return source.kind === 'web' ? '网页' : '知识库'
}

/** 详情抽屉的副标题：文档类型 + 第几页 + 分片序号。 */
export function sourceMeta(source) {
  const parts = []
  if (source.kind === 'web') {
    try {
      parts.push(new URL(source.url).hostname.replace(/^www\./, ''))
    } catch {
      parts.push('外部网页')
    }
  } else {
    parts.push(typeLabel(source.fileType))
    if (source.page) parts.push(`第 ${source.page} 页`)
    if (source.chunkIndex !== null && source.chunkIndex !== undefined) {
      parts.push(`分片 #${source.chunkIndex}`)
    }
  }
  return parts.join(' · ')
}

/** 按文档归并，用于「本轮引用」的分组展示。 */
export function groupSources(sources) {
  const groups = new Map()
  for (const source of sources) {
    const key = source.kind === 'knowledge' ? source.fileMd5 || source.id : source.url || source.id
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        kind: source.kind,
        title: source.title,
        fileMd5: source.fileMd5,
        fileType: source.fileType,
        url: source.url,
        items: [],
      })
    }
    groups.get(key).items.push(source)
  }
  return [...groups.values()]
}

/** 会话列表右侧的计数徽标上用的短标签。 */
export function shortTitle(source, limit = 28) {
  const title = source.title || ''
  return title.length > limit ? `${title.slice(0, limit)}…` : title
}
