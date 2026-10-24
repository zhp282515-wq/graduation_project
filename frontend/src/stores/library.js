import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'
import {
  deleteDocument,
  getDocumentChunks,
  getIngestJob,
  getKnowledgeOverview,
  listDocuments,
  syncKnowledge,
  uploadDocument,
} from '../api/knowledgeBase'
import { useUiStore } from './ui'

const STAGE_LABEL = {
  pending: '排队中',
  parsing: '解析文档',
  embedding: '生成向量',
  inserting: '写入索引',
  ready: '已入库',
  failed: '处理失败',
}

let uploadSeed = 0
const pollers = new Map()

export function stageLabel(status, stage) {
  if (status === 'ready') return '已入库'
  if (status === 'failed') return '处理失败'
  return STAGE_LABEL[stage] || '处理中'
}

export const useLibraryStore = defineStore('library', () => {
  const ui = useUiStore()

  const query = ref('')
  const type = ref('')
  const page = ref(1)
  const pageSize = ref(10)
  const sort = ref('uploaded')

  const items = ref([])
  const total = ref(0)
  const facets = ref({ all: 0, md: 0, doc: 0, docx: 0, pdf: 0, txt: 0 })
  const overview = ref(null)
  const status = ref('idle')
  const error = ref('')
  const syncing = ref(false)
  const lastSyncedAt = ref(0)

  const activeMd5 = ref('')
  const document = ref(null)
  const chunks = ref([])
  const chunkTotal = ref(0)
  const chunkPage = ref(1)
  const chunkPageSize = ref(20)
  const chunkStatus = ref('idle')
  const chunkError = ref('')

  const uploads = ref([])

  const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
  const chunkPageCount = computed(() => Math.max(1, Math.ceil(chunkTotal.value / chunkPageSize.value)))
  const activeItem = computed(
    () => items.value.find((item) => item.file_md5 === activeMd5.value) || document.value || null,
  )
  const hasUploadsInFlight = computed(() =>
    uploads.value.some((item) => item.state === 'uploading' || item.state === 'processing'),
  )

  const FACETS = [
    { key: '', label: '全部' },
    { key: 'md', label: 'Markdown' },
    { key: 'doc', label: 'DOC' },
    { key: 'docx', label: 'DOCX' },
    { key: 'pdf', label: 'PDF' },
    { key: 'txt', label: '文本' },
  ]

  /** 全库总量：抬头与扉页显示的“54 篇 / 1,759 片”必须来自聚合接口，而不是当前页求和。 */
  async function fetchOverview() {
    try {
      overview.value = await getKnowledgeOverview()
    } catch {
      // 总览只是装饰性统计，失败时保留上一次的值，不打断列表加载。
    }
  }

  async function fetchDocuments({ silent = false } = {}) {
    if (!silent) status.value = 'loading'
    error.value = ''
    try {
      const [data] = await Promise.all([
        listDocuments({
          q: query.value,
          type: type.value,
          page: page.value,
          pageSize: pageSize.value,
          sort: sort.value,
        }),
        overview.value ? null : fetchOverview(),
      ])
      items.value = Array.isArray(data?.items) ? data.items : []
      total.value = Number(data?.total) || 0
      facets.value = data?.facets || facets.value
      status.value = 'ready'
      // 页码越界（例如删掉了最后一页最后一条）时自动回到最后一页。
      if (page.value > pageCount.value) {
        page.value = pageCount.value
        await fetchDocuments({ silent: true })
      }
    } catch (err) {
      status.value = 'error'
      error.value = err?.message || '文档列表加载失败'
      if (!silent) ui.notify(error.value, 'err')
    }
  }

  function setQuery(value) {
    query.value = value
    page.value = 1
  }

  function setType(value) {
    type.value = value
    page.value = 1
  }

  function setSort(value) {
    sort.value = value === 'name' ? 'name' : 'uploaded'
    page.value = 1
  }

  function setPage(value) {
    const next = Math.min(Math.max(1, value), pageCount.value)
    if (next === page.value) return
    page.value = next
    fetchDocuments()
  }

  function setPageSize(value) {
    pageSize.value = value
    page.value = 1
    fetchDocuments()
  }

  async function openDocument(item) {
    if (!item?.file_md5) return
    activeMd5.value = item.file_md5
    document.value = item
    chunks.value = []
    chunkTotal.value = 0
    chunkPage.value = 1
    await loadChunks(1)
  }

  function closeDocument() {
    activeMd5.value = ''
    document.value = null
    chunks.value = []
    chunkTotal.value = 0
    chunkStatus.value = 'idle'
  }

  async function loadChunks(nextPage = chunkPage.value) {
    if (!activeMd5.value) return
    chunkStatus.value = 'loading'
    chunkError.value = ''
    try {
      const data = await getDocumentChunks(activeMd5.value, {
        page: nextPage,
        pageSize: chunkPageSize.value,
      })
      if (activeMd5.value !== data?.document?.file_md5 && data?.document?.file_md5) return
      chunks.value = Array.isArray(data?.items) ? data.items : []
      chunkTotal.value = Number(data?.total) || 0
      chunkPage.value = Number(data?.page) || nextPage
      if (data?.document) document.value = { ...document.value, ...data.document }
      chunkStatus.value = 'ready'
    } catch (err) {
      chunkStatus.value = 'error'
      chunkError.value = err?.message || '分片加载失败'
    }
  }

  function setChunkPage(value) {
    const next = Math.min(Math.max(1, value), chunkPageCount.value)
    if (next === chunkPage.value) return
    loadChunks(next)
  }

  function stopPolling(md5) {
    const timer = pollers.get(md5)
    if (timer) {
      window.clearInterval(timer)
      pollers.delete(md5)
    }
  }

  function updateUpload(md5, patch) {
    uploads.value = uploads.value.map((item) =>
      item.md5 === md5 || item.id === patch.id ? { ...item, ...patch } : item,
    )
  }

  /**
   * 轮询 /api/knowledge/jobs/{md5}，直到 ready / failed。
   * 后端把真实阶段写在 stage 上（parsing / embedding / inserting），这里原样展示。
   */
  function pollJob(md5, entryId) {
    stopPolling(md5)
    let attempts = 0
    const tick = async () => {
      attempts += 1
      if (attempts > 300) {
        stopPolling(md5)
        updateUpload(md5, { state: 'failed', error: '轮询超时，请稍后刷新列表确认结果' })
        return
      }
      try {
        const job = await getIngestJob(md5)
        const nextStatus = job?.status || 'processing'
        updateUpload(md5, {
          state: nextStatus === 'ready' ? 'ready' : nextStatus === 'failed' ? 'failed' : 'processing',
          stage: job?.stage || '',
          chunkCount: job?.chunk_count ?? null,
          error: job?.error || '',
        })
        if (nextStatus === 'ready') {
          stopPolling(md5)
          ui.notify(`《${job?.file_name || '文档'}》已入库`, 'ok')
          await fetchDocuments({ silent: true })
          await fetchOverview()
        } else if (nextStatus === 'failed') {
          stopPolling(md5)
          ui.notify(job?.error || '文档处理失败', 'err')
          await fetchDocuments({ silent: true })
        }
      } catch (err) {
        if (err?.status === 404) {
          stopPolling(md5)
          updateUpload(md5, { state: 'failed', error: '文档登记不存在，请重新上传' })
        }
        // 其他错误（网络抖动、503）保持轮询，下一次再试。
      }
      if (entryId) updateUpload(md5, { id: entryId })
    }
    pollers.set(md5, window.setInterval(tick, 2000))
    tick()
  }

  async function uploadFiles(files, { title = '' } = {}) {
    const list = Array.from(files || [])
    if (!list.length) return
    for (const file of list) {
      uploadSeed += 1
      const entryId = `upload-${uploadSeed}`
      const entry = reactive({
        id: entryId,
        md5: '',
        name: file.name,
        size: file.size,
        progress: 0,
        state: 'uploading',
        stage: '',
        error: '',
        chunkCount: null,
      })
      uploads.value = [...uploads.value, entry]
      try {
        const result = await uploadDocument(file, {
          title: title || file.name.replace(/\.[^.]+$/, ''),
          onProgress: ({ ratio }) => {
            entry.progress = Math.round(ratio * 100)
          },
        })
        const md5 = result?.file_md5
        if (!md5) throw new Error('后端没有返回文档指纹')
        entry.md5 = md5
        entry.state = 'processing'
        entry.progress = 100
        ui.notify(`《${file.name}》已提交，正在后台解析`, 'info')
        await fetchDocuments({ silent: true })
        pollJob(md5, entryId)
      } catch (err) {
        entry.state = 'failed'
        entry.error = err?.message || '上传失败'
        ui.notify(entry.error, 'err')
      }
    }
  }

  function dismissUpload(id) {
    const target = uploads.value.find((item) => item.id === id)
    if (target?.md5) stopPolling(target.md5)
    uploads.value = uploads.value.filter((item) => item.id !== id)
  }

  function clearFinishedUploads() {
    uploads.value = uploads.value.filter(
      (item) => item.state === 'uploading' || item.state === 'processing',
    )
  }

  async function removeDocument(item) {
    const md5 = item?.file_md5
    if (!md5) return false
    try {
      const result = await deleteDocument(md5)
      if (activeMd5.value === md5) closeDocument()
      ui.notify(`已删除《${item.file_name}》，清理 ${result?.chunks_deleted ?? 0} 个分片`, 'ok')
      await fetchDocuments({ silent: true })
      await fetchOverview()
      return true
    } catch (err) {
      if (err?.status === 409) ui.notify('文档正在处理中，请稍后再试', 'warn')
      else ui.notify(err?.message || '删除失败', 'err')
      return false
    }
  }

  async function runSync() {
    if (syncing.value) return
    syncing.value = true
    try {
      const result = await syncKnowledge()
      lastSyncedAt.value = Date.now()
      ui.notify(
        `同步完成：扫描 ${result?.scanned ?? 0} 份，更新 ${result?.upserted ?? 0} 份，移除 ${result?.removed ?? 0} 份`,
        'ok',
      )
      await fetchDocuments({ silent: true })
      await fetchOverview()
      if (activeMd5.value) await loadChunks(chunkPage.value)
      return result
    } catch (err) {
      ui.notify(err?.message || '同步失败', 'err')
      return null
    } finally {
      syncing.value = false
    }
  }

  /** 聊天里引用了某个分片时，直接跳到知识库并定位到该文档。 */
  async function focusSource(source) {
    if (!source?.fileMd5) return false
    const target = items.value.find((item) => item.file_md5 === source.fileMd5)
    if (target) {
      await openDocument(target)
      return true
    }
    try {
      const data = await getDocumentChunks(source.fileMd5, { page: 1, pageSize: 20 })
      if (!data?.document) return false
      activeMd5.value = source.fileMd5
      document.value = data.document
      chunks.value = []
      chunkTotal.value = 0
      // 直接跳到该分片所在页：每页 20 条，序号从 0 开始。
      const index = Number(source.chunkIndex)
      const targetPage = Number.isFinite(index) ? Math.floor(index / chunkPageSize.value) + 1 : 1
      await loadChunks(targetPage)
      return true
    } catch (err) {
      ui.notify(err?.message || '无法打开该文档', 'err')
      return false
    }
  }

  function dispose() {
    for (const md5 of [...pollers.keys()]) stopPolling(md5)
  }

  return {
    query,
    type,
    page,
    pageSize,
    sort,
    items,
    total,
    facets,
    overview,
    status,
    error,
    syncing,
    lastSyncedAt,
    activeMd5,
    document,
    chunks,
    chunkTotal,
    chunkPage,
    chunkPageSize,
    chunkStatus,
    chunkError,
    uploads,
    pageCount,
    chunkPageCount,
    activeItem,
    hasUploadsInFlight,
    FACETS,
    fetchDocuments,
    fetchOverview,
    setQuery,
    setType,
    setSort,
    setPage,
    setPageSize,
    openDocument,
    closeDocument,
    loadChunks,
    setChunkPage,
    uploadFiles,
    dismissUpload,
    clearFinishedUploads,
    removeDocument,
    runSync,
    focusSource,
    dispose,
  }
})
