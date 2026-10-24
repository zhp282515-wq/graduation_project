import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'
import { getStarMap, getStarMapEdges, getStarMapPoints } from '../api/knowledgeBase'
import { useUiStore } from './ui'

/** 星群配色：与纸本 / 星夜两套主题都能共存的低饱和色相。 */
export const DOC_HUES = [212, 168, 38, 288, 8, 122, 248, 322, 190, 62]

const PAGE_SIZE = 400

function hueFor(index) {
  return DOC_HUES[index % DOC_HUES.length]
}

export const useAtlasStore = defineStore('atlas', () => {
  const ui = useUiStore()

  const status = ref('idle') // idle | loading | ready | error
  const error = ref('')
  const meta = ref(null)
  const documents = ref([])
  const points = shallowRef([])
  const edges = shallowRef([])
  const progress = ref({ loaded: 0, total: 0 })

  const query = ref('')
  const docFilter = ref('')
  const typeFilter = ref('')
  // 900 条跨文档语义线在远景会盖住星体，默认关灯，由用户自己打开。
const showSemanticEdges = ref(false)
  const showChains = ref(true)

  const selectedId = ref('')
  const hoveredId = ref('')
  const focusRequest = ref(null) // { pointId, nonce }

  const byId = shallowRef(new Map())
  const byStarKey = shallowRef(new Map())
  const docById = computed(() => {
    const map = new Map()
    documents.value.forEach((doc, index) => {
      map.set(doc.file_md5, { ...doc, index, hue: hueFor(index) })
    })
    return map
  })

  const selected = computed(() => (selectedId.value ? byId.value.get(selectedId.value) || null : null))
  const selectedDoc = computed(() =>
    selected.value ? docById.value.get(selected.value.file_md5) || null : null,
  )

  const algorithm = computed(() => meta.value?.algorithm || null)
  const totalChunks = computed(() => points.value.length)
  const loaded = computed(() => status.value === 'ready')

  const typeOptions = computed(() => {
    const counts = new Map()
    for (const doc of documents.value) {
      const key = doc.file_type || 'other'
      counts.set(key, (counts.get(key) || 0) + 1)
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([key, count]) => ({ key, count }))
  })

  const filteredIds = computed(() => {
    const needle = query.value.trim().toLowerCase()
    if (!needle && !docFilter.value && !typeFilter.value) return null
    const ids = new Set()
    for (const point of points.value) {
      if (docFilter.value && point.file_md5 !== docFilter.value) continue
      if (typeFilter.value) {
        const doc = docById.value.get(point.file_md5)
        if ((doc?.file_type || 'other') !== typeFilter.value) continue
      }
      if (needle) {
        const doc = docById.value.get(point.file_md5)
        const haystack = `${point.text}\n${point.section_path}\n${doc?.file_name || ''}`.toLowerCase()
        if (!haystack.includes(needle)) continue
      }
      ids.add(point.id)
    }
    return ids
  })

  const matchCount = computed(() =>
    filteredIds.value ? filteredIds.value.size : points.value.length,
  )

  const searchResults = computed(() => {
    const needle = query.value.trim()
    if (!needle) return []
    const ids = filteredIds.value
    if (!ids) return []
    const out = []
    for (const point of points.value) {
      if (!ids.has(point.id)) continue
      out.push(point)
      if (out.length >= 40) break
    }
    return out
  })

  const edgesResolved = computed(() =>
    edges.value
      .map((edge) => {
        const a = byStarKey.value.get(edge.a)
        const b = byStarKey.value.get(edge.b)
        return a && b ? { ...edge, from: a, to: b } : null
      })
      .filter(Boolean),
  )

  const chainPairs = computed(() => {
    const pairs = []
    for (const doc of documents.value) {
      const list = points.value.filter((point) => point.file_md5 === doc.file_md5)
      for (let i = 1; i < list.length; i += 1) {
        pairs.push([list[i - 1], list[i]])
      }
    }
    return pairs
  })

  function indexPoints(list) {
    const idMap = new Map()
    const keyMap = new Map()
    for (const point of list) {
      idMap.set(point.id, point)
      keyMap.set(`${point.file_md5}:${point.chunk_index}`, point)
    }
    byId.value = idMap
    byStarKey.value = keyMap
  }

  async function load({ force = false } = {}) {
    if (status.value === 'loading') return
    status.value = 'loading'
    error.value = ''
    progress.value = { loaded: 0, total: 0 }
    try {
      const summary = await getStarMap({ force })
      meta.value = summary
      documents.value = Array.isArray(summary?.documents) ? summary.documents : []
      const total = Number(summary?.total_chunks) || 0
      progress.value = { loaded: 0, total }

      const collected = []
      let offset = 0
      let guard = 0
      while (guard < 200) {
        guard += 1
        const page = await getStarMapPoints({ offset, limit: PAGE_SIZE, force })
        const items = Array.isArray(page?.items) ? page.items : []
        collected.push(...items)
        progress.value = { loaded: collected.length, total: total || collected.length }
        if (page?.next_offset === null || page?.next_offset === undefined) break
        offset = page.next_offset
      }

      // 后端按文档名 + chunk_index 排序返回，这里再按 (文档顺序, 分片序号) 落一次，
      // 让「星链」与列表顺序稳定可预期。
      const orderIndex = new Map(documents.value.map((doc, index) => [doc.file_md5, index]))
      collected.sort((a, b) => {
        const left = orderIndex.get(a.file_md5) ?? 0
        const right = orderIndex.get(b.file_md5) ?? 0
        if (left !== right) return left - right
        return a.chunk_index - b.chunk_index
      })
      points.value = collected
      indexPoints(collected)

      try {
        const edgePayload = await getStarMapEdges({ force })
        edges.value = Array.isArray(edgePayload?.items) ? edgePayload.items : []
      } catch (edgeError) {
        // 连边失败不算整张星图失败：星体与文档归属仍然完整可用。
        edges.value = []
      }

      status.value = 'ready'
    } catch (err) {
      status.value = 'error'
      if (err?.status === 404) {
        error.value = '星图接口未就绪：后端仍在运行旧版本，重启服务后再试。'
      } else if (err?.status === 503) {
        error.value = '知识库尚未就绪，星图暂时没有可读取的分片。'
      } else {
        error.value = err?.message || '知识星图加载失败'
      }
      ui.notify(error.value, 'err')
    }
  }

  function reload() {
    return load({ force: true })
  }

  function select(id, { focus = false } = {}) {
    if (!id) {
      selectedId.value = ''
      return
    }
    if (!byId.value.has(id)) return
    selectedId.value = id
    if (focus) requestFocus(id)
  }

  function clearSelection() {
    selectedId.value = ''
  }

  function requestFocus(pointId) {
    focusRequest.value = { pointId, nonce: Date.now() }
  }

  function selectByStarKey(key, options = {}) {
    const point = byStarKey.value.get(key)
    if (!point) return false
    select(point.id, options)
    return true
  }

  function setQuery(value) {
    query.value = value
  }

  function setDocFilter(value) {
    docFilter.value = value
  }

  function setTypeFilter(value) {
    typeFilter.value = value
  }

  function clearFilters() {
    query.value = ''
    docFilter.value = ''
    typeFilter.value = ''
  }

  function reset() {
    status.value = 'idle'
    error.value = ''
    meta.value = null
    documents.value = []
    points.value = []
    edges.value = []
    byId.value = new Map()
    byStarKey.value = new Map()
    selectedId.value = ''
    progress.value = { loaded: 0, total: 0 }
  }

  return {
    status,
    error,
    meta,
    documents,
    points,
    edges,
    progress,
    query,
    docFilter,
    typeFilter,
    showSemanticEdges,
    showChains,
    selectedId,
    hoveredId,
    focusRequest,
    byId,
    byStarKey,
    docById,
    selected,
    selectedDoc,
    algorithm,
    totalChunks,
    loaded,
    typeOptions,
    filteredIds,
    matchCount,
    searchResults,
    edgesResolved,
    chainPairs,
    load,
    reload,
    select,
    clearSelection,
    requestFocus,
    selectByStarKey,
    setQuery,
    setDocFilter,
    setTypeFilter,
    clearFilters,
    reset,
  }
})
