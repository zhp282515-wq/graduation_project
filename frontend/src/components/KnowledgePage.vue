<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  deleteKnowledgeDocument,
  getKnowledgeJob,
  listKnowledgeChunks,
  listKnowledgeDocuments,
  syncKnowledge,
  uploadKnowledgeDocument,
} from '../api/knowledge'

const props = defineProps({
  confirm: { type: Function, required: true },
  toast: { type: Function, required: true },
  focusTarget: { type: Object, default: null },
})
const emit = defineEmits(['back-to-source'])
const sourceHint = ref('')
const highlightedChunkId = ref(null)

const TYPE_LABEL = { md: 'MD', doc: 'DOC', docx: 'DOCX', pdf: 'PDF', txt: 'TXT' }
const STAGE_LABEL = {
  parsing: '解析中',
  embedding: '向量化中',
  inserting: '写入中',
}

/* ---------- 列表状态 ---------- */
const docs = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(10)
const q = ref('')
const type = ref('')
const facets = ref({ all: 0, md: 0, doc: 0, docx: 0, pdf: 0, txt: 0 })
const loading = ref(false)
const loadError = ref('')
let reqSeq = 0
let searchTimer = null

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

const typeChips = computed(() => {
  const chips = [{ key: '', label: '全部', count: facets.value.all || 0 }]
  for (const key of ['md', 'doc', 'docx', 'pdf', 'txt']) {
    const count = facets.value[key] || 0
    if (key === 'txt' && count === 0) continue
    chips.push({ key, label: TYPE_LABEL[key], count })
  }
  return chips
})

async function fetchDocuments() {
  const seq = ++reqSeq
  loading.value = true
  loadError.value = ''
  try {
    const data = await listKnowledgeDocuments({
      q: q.value,
      type: type.value,
      page: page.value,
      pageSize: pageSize.value,
    })
    if (seq !== reqSeq) return
    docs.value = data.items
    total.value = data.total
    facets.value = data.facets
    // 页码越界（删除后）自动回退
    if (page.value > totalPages.value) {
      page.value = totalPages.value
      await fetchDocuments()
      return
    }
    // 刷新时恢复进行中的轮询
    for (const d of data.items) {
      if (d.status === 'pending' || d.status === 'processing') ensureJob(d)
    }
    startPolling()
  } catch (e) {
    if (seq !== reqSeq) return
    loadError.value = e.message
  } finally {
    if (seq === reqSeq) loading.value = false
  }
}

function onSearchInput() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    fetchDocuments()
  }, 300)
}

function clearSearch() {
  q.value = ''
  page.value = 1
  fetchDocuments()
}

function selectType(key) {
  if (type.value === key) return
  type.value = key
  page.value = 1
  fetchDocuments()
}

function goPage(p) {
  const next = Math.min(Math.max(1, p), totalPages.value)
  if (next === page.value) return
  page.value = next
  fetchDocuments()
}

const pageSizeOpen = ref(false)
const PAGE_SIZE_OPTIONS = [10, 20, 50]

function changePageSize(size) {
  pageSizeOpen.value = false
  if (size === pageSize.value) return
  pageSize.value = size
  page.value = 1
  fetchDocuments()
}

function closePageSize() {
  pageSizeOpen.value = false
}

function onDocClick() {
  // 点空白处收起下拉
  if (pageSizeOpen.value) closePageSize()
}

/* ---------- 详情 / 切片 ---------- */
const selected = ref(null)
const sourceDocument = ref(null)
const displayedDocs = computed(() => {
  const source = sourceDocument.value
  return source && !docs.value.some(doc => doc.file_md5 === source.file_md5) ? [source, ...docs.value] : docs.value
})
function isSourceDocument(doc) {
  return sourceDocument.value?.file_md5 === doc.file_md5 && selected.value?.file_md5 === doc.file_md5
}
watch([sourceDocument, docs], async () => {
  if (!sourceDocument.value) return
  await nextTick()
  document.querySelector('.kb-row.is-source')?.scrollIntoView({ block: 'nearest', behavior: 'instant' })
})
const chunks = ref([])
const chunkTotal = ref(0)
const chunkPage = ref(1)
const chunkPageSize = 20
const chunksLoading = ref(false)
const chunkError = ref('')
let chunkSeq = 0

const chunkPages = computed(() => Math.max(1, Math.ceil(chunkTotal.value / chunkPageSize)))

async function selectDoc(doc) {
  sourceDocument.value = null
  highlightedChunkId.value = null
  sourceHint.value = ''
  selected.value = doc
  chunkPage.value = 1
  await fetchChunks()
}

function closeDetail() {
  ++chunkSeq
  sourceDocument.value = null
  selected.value = null
  chunks.value = []
}

async function fetchChunks() {
  if (!selected.value) return
  const md5 = selected.value.file_md5
  const seq = ++chunkSeq
  chunksLoading.value = true
  chunkError.value = ''
  try {
    const data = await listKnowledgeChunks(md5, { page: chunkPage.value, pageSize: chunkPageSize })
    if (seq !== chunkSeq) return
    chunks.value = data.items
    chunkTotal.value = data.total
    if (data.document) {
      // 用服务端数据刷新选中行，块数可能刚变化
      const idx = docs.value.findIndex((d) => d.file_md5 === md5)
      if (idx !== -1) Object.assign(docs.value[idx], data.document)
      selected.value = { ...selected.value, ...data.document }
      if (props.focusTarget?.file_md5 === md5) sourceDocument.value = data.document
    }
    return true
  } catch (e) {
    if (seq !== chunkSeq) return
    chunkError.value = e.message
  } finally {
    if (seq === chunkSeq) chunksLoading.value = false
  }
}

function goChunkPage(p) {
  const next = Math.min(Math.max(1, p), chunkPages.value)
  if (next === chunkPage.value) return
  chunkPage.value = next
  fetchChunks()
}

watch(() => props.focusTarget?.requestId, async () => {
  const target = props.focusTarget
  if (!target) {
    ++chunkSeq
    highlightedChunkId.value = null
    sourceHint.value = ''
    chunkError.value = ''
    chunksLoading.value = false
    closeDetail()
    return
  }
  const requestId = target.requestId
  sourceDocument.value = null
  highlightedChunkId.value = null
  sourceHint.value = ''
  selected.value = { file_md5: target.file_md5, file_name: target.title, file_type: target.file_type, status: 'ready' }
  chunkPage.value = Math.floor(target.chunk_index / chunkPageSize) + 1
  const loaded = await fetchChunks()
  if (requestId !== props.focusTarget?.requestId) return
  if (!loaded) {
    sourceHint.value = '当前文档无法打开。可返回来源，继续查看保存的历史分片。'
    return
  }
  const match = target.chunk_id && chunks.value.find(chunk => chunk.chunk_id === target.chunk_id)
  if (match) {
    highlightedChunkId.value = match.chunk_id
    sourceHint.value = '已定位这条回复使用的来源分片。'
    await nextTick()
    document.querySelector('.kb-chunk.is-source')?.scrollIntoView({ block: 'nearest', behavior: 'instant' })
  } else {
    sourceHint.value = '文档已重新切片，当前内容与历史来源可能不同。原分片仍可在来源面板查看。'
    if (chunkPage.value > chunkPages.value) { chunkPage.value = 1; await fetchChunks() }
  }
}, { immediate: true })

/* ---------- 删除 ---------- */
function removeDoc(doc) {
  props.confirm({
    title: '删除文档',
    message: `确定删除「${doc.file_name}」吗？将同时删除它的全部知识块，不可恢复。`,
    confirmText: '删除',
    danger: true,
    onConfirm: async () => {
      try {
        await deleteKnowledgeDocument(doc.file_md5)
        if (selected.value?.file_md5 === doc.file_md5) closeDetail()
        props.toast('已删除文档')
        await fetchDocuments()
      } catch (e) {
        props.toast(`删除失败：${e.message}`, 'error')
      }
    },
  })
}

/* ---------- 上传与轮询 ---------- */
const fileInput = ref(null)
const jobs = ref([])   // { md5, name, status, stage, progress, error }
let pollTimer = null

function openPicker() {
  fileInput.value?.click()
}

async function onFilesPicked(e) {
  const files = Array.from(e.target.files ?? [])
  e.target.value = ''
  for (const file of files) {
    const job = ref({
      md5: null,
      name: file.name,
      status: 'uploading',
      stage: null,
      progress: 0,
      error: '',
    })
    jobs.value.push(job)

    try {
      const res = await uploadKnowledgeDocument(file, {
        onProgress: (loaded, totalBytes) => {
          job.value.progress = Math.round((loaded / totalBytes) * 100)
        },
      })
      job.value.md5 = res.file_md5
      job.value.name = res.file_name || file.name
      job.value.status = res.status || 'pending'
      job.value.progress = 100
      startPolling()
      pollJob(job)
    } catch (err) {
      job.value.status = 'failed'
      job.value.error = err.message
      props.toast(`上传失败：${err.message}`, 'error')
    }
  }
}

function ensureJob(doc) {
  const exists = jobs.value.some((j) => j.value.md5 === doc.file_md5)
  if (exists) return
  jobs.value.push(ref({
    md5: doc.file_md5,
    name: doc.file_name || doc.original_name || '',
    status: doc.status,
    stage: doc.stage,
    progress: 100,
    error: doc.error || '',
  }))
}

async function pollJob(job) {
  if (!job.value.md5) return
  try {
    const data = await getKnowledgeJob(job.value.md5)
    job.value.status = data.status
    job.value.stage = data.stage
    job.value.error = data.error || ''
    if (data.file_name) job.value.name = data.file_name

    if (data.status === 'ready') {
      props.toast(`已入库：${job.value.name}`, 'success')
      await fetchDocuments()
      if (selected.value?.file_md5 === job.value.md5) await fetchChunks()
      setTimeout(() => dismissJob(job), 2500)
    } else if (data.status === 'failed') {
      props.toast(`入库失败：${job.value.name}`, 'error')
    }
  } catch (e) {
    job.value.error = e.message
  }
  startPolling()
}

function startPolling() {
  const active = jobs.value.some((j) =>
    j.value.status === 'pending' || j.value.status === 'processing'
  )
  if (!active) {
    stopPolling()
    return
  }
  if (pollTimer) return
  pollTimer = setInterval(() => {
    for (const j of jobs.value) {
      if (j.value.status === 'pending' || j.value.status === 'processing') pollJob(j)
    }
    startPolling()
  }, 2000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function dismissJob(job) {
  const i = jobs.value.findIndex((j) => j === job)
  if (i !== -1) jobs.value.splice(i, 1)
}

const activeJobs = computed(() =>
  jobs.value.filter((j) => j.value.status !== 'ready')
)

/* ---------- 展示辅助 ---------- */
function formatBytes(n) {
  if (!n) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function formatDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (v) => String(v).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function statusLabel(doc) {
  if (doc.status === 'ready') return '已入库'
  if (doc.status === 'failed') return '失败'
  if (doc.status === 'processing') return STAGE_LABEL[doc.stage] || '处理中'
  return '排队中'
}

function jobStageLabel(job) {
  if (job.status === 'uploading') return `上传中 ${job.progress || 0}%`
  if (job.status === 'pending') return '排队中'
  if (job.status === 'processing') return STAGE_LABEL[job.stage] || '处理中'
  if (job.status === 'failed') return '失败'
  return '已入库'
}

async function manualSync() {
  try {
    const r = await syncKnowledge()
    props.toast(`已同步：新增 ${r.upserted} 份，清理 ${r.removed} 份`, 'success')
    await fetchDocuments()
  } catch (e) {
    props.toast(`同步失败：${e.message}`, 'error')
  }
}

onMounted(() => {
  fetchDocuments()
  document.addEventListener('click', onDocClick)
})

onBeforeUnmount(() => {
  clearTimeout(searchTimer)
  stopPolling()
  document.removeEventListener('click', onDocClick)
})
</script>

<template>
  <section class="kb-page panel" v-glass-tilt>
    <!-- 头部 -->
    <div class="kb-head">
      <div class="kb-heading">
        <button v-if="focusTarget" class="kb-return-source" type="button" @click="emit('back-to-source')">返回来源</button>
        <h2 class="kb-title">知识库</h2>
        <span class="kb-sub">共 {{ total }} 份文档</span>
      </div>

      <div class="kb-tools">
        <div class="search-box">
          <svg class="search-icon" viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"
               fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="7"/>
            <path d="M20 20l-3.5-3.5"/>
          </svg>
          <input
            :value="q"
            class="search-input"
            type="text"
            placeholder="搜索文档名..."
            aria-label="搜索文档"
            @input="q = $event.target.value; onSearchInput()"
          />
          <button v-if="q" class="search-clear" type="button" aria-label="清除搜索" @click="clearSearch">
            <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"
                 fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
              <path d="M6 6l12 12M18 6L6 18"/>
            </svg>
          </button>
        </div>

        <button class="glass-btn kb-upload-btn" v-glass-tilt type="button" @click="openPicker">
          <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"
               fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 16V4M8 8l4-4 4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>
          </svg>
          上传文档
        </button>
        <input
          ref="fileInput"
          class="file-input"
          type="file"
          multiple
          accept=".md,.txt,.pdf,.doc,.docx"
          @change="onFilesPicked"
        />
      </div>
    </div>

    <!-- 格式筛选 -->
    <div class="kb-filters">
      <button
        v-for="chip in typeChips"
        :key="chip.key || 'all'"
        class="glass-btn kb-chip"
        :class="{ active: type === chip.key }"
        v-glass-tilt
        type="button"
        @click="selectType(chip.key)"
      >
        {{ chip.label }}
        <span class="kb-chip-count">{{ chip.count }}</span>
      </button>
      <button class="kb-sync" type="button" title="对齐 Milvus 与登记表" @click="manualSync">
        同步
      </button>
    </div>

    <!-- 上传任务 -->
    <div v-if="activeJobs.length" class="kb-jobs">
      <div v-for="job in activeJobs" :key="job.value.md5 || job.value.name" class="kb-job" :class="job.value.status">
        <span class="kb-job-name">{{ job.value.name }}</span>
        <span class="kb-job-stage">{{ jobStageLabel(job.value) }}</span>
        <div class="kb-progress">
          <i :style="{ width: (job.value.progress || 8) + '%' }" />
        </div>
        <span v-if="job.value.error" class="kb-job-error" :title="job.value.error">{{ job.value.error }}</span>
        <button class="kb-job-close" type="button" aria-label="关闭" @click="dismissJob(job)">×</button>
      </div>
    </div>

    <!-- 主体 -->
    <div class="kb-workspace">
      <div class="kb-list-wrap">
        <div v-if="loadError" class="kb-empty">{{ loadError }}</div>
        <div v-else-if="!displayedDocs.length && !loading" class="kb-empty">
          <p>还没有匹配的文档</p>
          <button v-if="facets.all === 0" class="glass-btn" v-glass-tilt type="button" @click="manualSync">
            从 Milvus 同步现有文档
          </button>
        </div>

        <div v-else class="kb-list" :class="{ dim: loading }">
          <div
            v-for="doc in displayedDocs"
            :key="doc.file_md5"
            class="kb-row glass-btn"
            :class="{ active: selected?.file_md5 === doc.file_md5, 'is-source': isSourceDocument(doc) }"
            :aria-current="isSourceDocument(doc) ? 'true' : undefined"
            v-glass-tilt
            @click="selectDoc(doc)"
          >
            <span class="kb-badge" :class="doc.file_type">{{ TYPE_LABEL[doc.file_type] || doc.file_type }}</span>
            <span class="kb-row-main">
              <span class="kb-row-name">{{ doc.file_name }}</span>
              <span class="kb-row-meta">
                <span v-if="isSourceDocument(doc)" class="kb-source-label">来源文档</span>
                <span>{{ formatBytes(doc.file_size) }}</span>
                <span>·</span>
                <span>{{ doc.chunk_count ?? '—' }} 块</span>
                <span>·</span>
                <span>{{ formatDate(doc.ingested_at || doc.created_at) }}</span>
              </span>
            </span>
            <span class="kb-status" :class="doc.status">{{ statusLabel(doc) }}</span>
            <button
              class="kb-del"
              type="button"
              title="删除文档"
              aria-label="删除文档"
              @click.stop="removeDoc(doc)"
            >
              <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"
                   fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round">
                <path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>
              </svg>
            </button>
          </div>
        </div>

        <div class="kb-pager">
          <button class="glass-btn" v-glass-tilt type="button" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
          <span>第 {{ page }} / {{ totalPages }} 页</span>
          <button class="glass-btn" v-glass-tilt type="button" :disabled="page >= totalPages" @click="goPage(page + 1)">下一页</button>
          <div class="kb-page-size-wrap" @click.stop>
            <button
              class="kb-page-size glass-btn"
              v-glass-tilt
              type="button"
              :aria-expanded="pageSizeOpen"
              @click="pageSizeOpen = !pageSizeOpen"
            >
              {{ pageSize }} 条/页
              <svg class="kb-caret" :class="{ open: pageSizeOpen }" viewBox="0 0 24 24" width="12" height="12"
                   aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.2"
                   stroke-linecap="round" stroke-linejoin="round">
                <path d="M6 9l6 6 6-6"/>
              </svg>
            </button>
            <Transition name="kb-pop">
              <div v-if="pageSizeOpen" class="kb-page-size-menu" role="listbox">
                <button
                  v-for="opt in PAGE_SIZE_OPTIONS"
                  :key="opt"
                  class="kb-page-size-item"
                  :class="{ active: opt === pageSize }"
                  type="button"
                  role="option"
                  :aria-selected="opt === pageSize"
                  @click="changePageSize(opt)"
                >
                  {{ opt }} 条/页
                </button>
              </div>
            </Transition>
          </div>
        </div>
      </div>

      <div class="kb-detail">
        <template v-if="selected">
          <p v-if="sourceHint" class="kb-source-hint" role="status">{{ sourceHint }}</p>
          <div class="kb-detail-head">
            <h3>{{ selected.file_name }}</h3>
            <button class="kb-detail-close" type="button" aria-label="关闭详情" @click="closeDetail">×</button>
          </div>

          <div class="kb-meta-grid">
            <div><span>格式</span><strong>{{ TYPE_LABEL[selected.file_type] || selected.file_type }}</strong></div>
            <div><span>大小</span><strong>{{ formatBytes(selected.file_size) }}</strong></div>
            <div><span>切片</span><strong>{{ selected.chunk_count ?? '—' }}</strong></div>
            <div><span>状态</span><strong>{{ statusLabel(selected) }}</strong></div>
            <div><span>上传</span><strong>{{ formatDate(selected.created_at) }}</strong></div>
            <div><span>入库</span><strong>{{ formatDate(selected.ingested_at) }}</strong></div>
            <div v-if="!focusTarget" class="full"><span>MD5</span><strong class="mono">{{ selected.file_md5 }}</strong></div>
            <div v-if="selected.original_name" class="full">
              <span>原文件名</span><strong>{{ selected.original_name }}</strong>
            </div>
          </div>

          <div v-if="selected.error" class="kb-error-box">{{ selected.error }}</div>

          <div class="kb-chunk-head">
            <span>切片内容</span>
            <span class="kb-chunk-count">{{ chunkTotal }} 块</span>
          </div>

          <div class="kb-chunks">
            <div v-if="chunksLoading" class="kb-empty">加载中…</div>
            <div v-else-if="chunkError" class="kb-empty">{{ chunkError }}</div>
            <div v-else-if="!chunks.length" class="kb-empty">没有切片</div>
            <div v-for="chunk in chunks" :key="chunk.chunk_id || chunk.chunk_index" class="kb-chunk" :class="{ 'is-source': chunk.chunk_id && chunk.chunk_id === highlightedChunkId }">
              <div class="kb-chunk-meta">
                <span class="kb-chunk-idx">#{{ chunk.chunk_index }}</span>
                <span v-if="selected.file_type === 'pdf' && chunk.page">第 {{ chunk.page }} 页</span>
                <span class="kb-chunk-type">{{ chunk.block_type }}</span>
                <span>{{ chunk.char_count }} 字</span>
              </div>
              <div v-if="chunk.section_path" class="kb-chunk-path">{{ chunk.section_path }}</div>
              <pre class="kb-chunk-text">{{ chunk.text }}</pre>
            </div>
          </div>

          <div class="kb-pager">
            <button class="glass-btn" v-glass-tilt type="button" :disabled="chunkPage <= 1" @click="goChunkPage(chunkPage - 1)">上一页</button>
            <span>第 {{ chunkPage }} / {{ chunkPages }} 页</span>
            <button class="glass-btn" v-glass-tilt type="button" :disabled="chunkPage >= chunkPages" @click="goChunkPage(chunkPage + 1)">下一页</button>
          </div>
        </template>

        <div v-else class="kb-placeholder">
          <p>选择左侧文档查看切片与详情</p>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.kb-return-source { min-height: 44px; padding: 0 12px; border: 1px solid rgba(167,205,248,.35); border-radius: 10px; color: #d4e8ff; background: rgba(51,83,119,.38); font: inherit; font-size: 12px; cursor: pointer; }
.kb-return-source:hover { background: rgba(79,117,160,.45); }
.kb-return-source:focus-visible { outline: 2px solid #8fd0ff; outline-offset: 3px; }
.kb-source-hint { margin: 0 0 14px; padding: 12px; color: #d6e9ff; background: rgba(70,107,150,.25); border-radius: 10px; font-size: 12px; line-height: 1.8; }
.kb-chunk.is-source { outline: 2px solid #a5d4ff; outline-offset: -2px; background: rgba(91,143,199,.18); }
.kb-page {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 22px 24px;
  color: var(--text-primary);
}

.kb-page :deep(.glass-btn),
.kb-page .glass-btn {
  background: rgba(255, 255, 255, 0.10);
  border: 1px solid rgba(255, 255, 255, 0.12);
}
.kb-page .glass-btn:hover { background: rgba(255, 255, 255, 0.17); }
.kb-page .glass-btn:active { background: rgba(255, 255, 255, 0.06); }
.kb-page .glass-btn:disabled { opacity: 0.35; cursor: not-allowed; }

.kb-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.kb-heading { display: flex; align-items: baseline; gap: 12px; }
.kb-title { margin: 0; font-size: 20px; font-weight: 600; }
.kb-sub { font-size: 13px; color: var(--text-muted); }

.kb-tools { display: flex; align-items: center; gap: 10px; }
.kb-tools .search-box { width: 260px; }

.kb-upload-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 9px 16px;
  border-radius: 999px;
  font-size: 13.5px;
}

.kb-filters { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.kb-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: 999px;
  font-size: 13px;
}
.kb-chip.active { box-shadow: inset 0 0 0 1px rgba(150, 195, 245, 0.55); }
.kb-chip-count {
  padding: 0 6px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.16);
  font-size: 11px;
  color: var(--text-secondary);
}
.kb-sync {
  margin-left: auto;
  padding: 6px 12px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-muted);
  font-size: 12.5px;
  cursor: pointer;
}
.kb-sync:hover { color: var(--text-primary); background: rgba(255, 255, 255, 0.10); }

.kb-jobs { display: flex; flex-direction: column; gap: 8px; }
.kb-job {
  display: grid;
  grid-template-columns: 1fr auto 160px auto;
  align-items: center;
  gap: 12px;
  padding: 9px 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.09);
  font-size: 12.5px;
}
.kb-job.failed { background: rgba(200, 70, 65, 0.16); }
.kb-job-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kb-job-stage { color: var(--text-muted); }
.kb-job-error { color: #ff9a95; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.kb-progress {
  height: 4px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
  overflow: hidden;
}
.kb-progress i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #5aa0ff, #9ecbff);
  transition: width 0.3s ease;
}
.kb-job-close {
  border: 0; background: transparent; color: var(--text-muted);
  font-size: 15px; cursor: pointer; line-height: 1;
}
.kb-job-close:hover { color: var(--text-primary); }

.kb-workspace {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(340px, 440px);
  gap: 16px;
  overflow: hidden;
}
/* grid 子项默认 min-height:auto，不加这条列表会撑破容器盖住分页器 */
.kb-workspace > * { min-height: 0; }

.kb-list-wrap {
  display: flex;
  flex-direction: column;
  min-height: 0;
  gap: 10px;
  overflow: hidden;
}

.kb-list {
  flex: 1;
  min-height: 0;
  max-height: 100%;
  overflow-y: auto;
  overscroll-behavior: contain;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-right: 4px;
}
.kb-list::-webkit-scrollbar { width: 6px; }
.kb-list::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.28);
  border-radius: 999px;
}
.kb-list.dim { opacity: 0.55; }

.kb-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px;
  border-radius: 12px;
  font-size: 13.5px;
  text-align: left;
  background: rgba(255, 255, 255, 0.09);
  border: 1px solid rgba(255, 255, 255, 0.10);
}
.kb-row:hover { background: rgba(255, 255, 255, 0.15); }
.kb-row.active { box-shadow: inset 0 0 0 1px rgba(150, 195, 245, 0.55); }
.kb-row.is-source { background: rgba(82, 145, 215, .25); border-color: rgba(154, 205, 255, .7); box-shadow: none; }
.kb-row.is-source:hover { background: rgba(82, 145, 215, .33); }
.kb-row.is-source .kb-row-name { color: #e2f1ff; font-weight: 650; }
.kb-source-label { color: #c1e2ff; font-weight: 600; }

.kb-badge {
  flex: none;
  width: 44px;
  padding: 3px 0;
  border-radius: 6px;
  text-align: center;
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.3px;
  background: rgba(255, 255, 255, 0.14);
  color: var(--text-secondary);
}
.kb-badge.pdf { background: rgba(230, 110, 100, 0.24); color: #ffc4bf; }
.kb-badge.doc { background: rgba(110, 160, 235, 0.24); color: #cfe1fb; }
.kb-badge.docx { background: rgba(110, 185, 220, 0.24); color: #cbe9f7; }
.kb-badge.md { background: rgba(140, 220, 180, 0.22); color: #c6f2dd; }

.kb-row-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.kb-row-name {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-weight: 500;
}
.kb-row-meta { display: flex; gap: 6px; font-size: 11.5px; color: var(--text-muted); }

.kb-status {
  flex: none;
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 11px;
  background: rgba(255, 255, 255, 0.12);
  color: var(--text-muted);
}
.kb-status.ready { background: rgba(110, 215, 160, 0.20); color: #b9f0d2; }
.kb-status.failed { background: rgba(230, 110, 100, 0.22); color: #ffc0bb; }
.kb-status.processing { background: rgba(120, 180, 255, 0.22); color: #cfe4ff; }
.kb-status.pending { background: rgba(255, 255, 255, 0.12); }

.kb-del {
  flex: none;
  width: 24px; height: 24px;
  display: grid; place-items: center;
  border: 0; border-radius: 7px;
  background: transparent;
  color: var(--text-muted);
  opacity: 0;
  cursor: pointer;
  transition: opacity 0.2s ease, background 0.2s ease, color 0.2s ease;
}
.kb-row:hover .kb-del, .kb-del:focus-visible { opacity: 1; }
.kb-del:hover { background: rgba(210, 70, 70, 0.20); color: #ff9a95; }

.kb-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-muted);
  font-size: 13px;
}

.kb-pager {
  flex: none;
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  min-height: 44px;
  font-size: 12.5px;
  color: var(--text-primary);
  /* 实底 + 微模糊：滚动内容不会从分页器文字后面透出来 */
  background: rgba(18, 33, 56, 0.55);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border-radius: 10px;
}
.kb-pager .glass-btn {
  /* glass-btn 默认是 block；这里要让文字在按钮内垂直居中 */
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 30px;
  padding: 0 16px;
  border-radius: 999px;
  font-size: 12.5px;
  line-height: 1;
  white-space: nowrap;
}
.kb-pager .glass-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.kb-pager > span {
  display: inline-flex;
  align-items: center;
  line-height: 1;
  color: var(--text-secondary);
}
/* 每页条数：自绘下拉（原生 select 的弹层由系统绘制，样式无法统一） */
.kb-page-size-wrap {
  position: relative;
  margin-left: auto;
}
.kb-page-size {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 12px;
  border-radius: 8px;
  font-size: 12.5px;
  line-height: 1;
  white-space: nowrap;
}
.kb-caret {
  transition: transform 0.2s ease;
  color: var(--text-muted);
}
.kb-caret.open { transform: rotate(180deg); }

.kb-page-size-menu {
  position: absolute;
  right: 0;
  bottom: calc(100% + 6px);
  z-index: 20;
  min-width: 100%;
  padding: 5px;
  border-radius: 10px;
  background: rgba(20, 36, 60, 0.94);
  backdrop-filter: blur(20px) saturate(140%);
  -webkit-backdrop-filter: blur(20px) saturate(140%);
  border: 1px solid rgba(150, 195, 245, 0.28);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
}
.kb-page-size-item {
  display: block;
  width: 100%;
  padding: 7px 12px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12.5px;
  text-align: left;
  white-space: nowrap;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}
.kb-page-size-item:hover {
  background: rgba(255, 255, 255, 0.12);
  color: var(--text-primary);
}
.kb-page-size-item.active {
  background: rgba(120, 180, 255, 0.22);
  color: var(--text-primary);
}

.kb-pop-enter-active,
.kb-pop-leave-active {
  transition: opacity 0.16s ease, transform 0.18s cubic-bezier(0.22, 1, 0.36, 1);
}
.kb-pop-enter-from,
.kb-pop-leave-to {
  opacity: 0;
  transform: translateY(4px) scale(0.97);
}

.kb-detail {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.07);
  overflow: hidden;
}
.kb-detail-head { display: flex; align-items: flex-start; gap: 10px; }
.kb-detail-head h3 {
  flex: 1;
  margin: 0;
  font-size: 15px;
  line-height: 1.45;
  word-break: break-word;
}
.kb-detail-close {
  flex: none;
  width: 24px; height: 24px;
  border: 0; border-radius: 7px;
  background: rgba(255, 255, 255, 0.10);
  color: var(--text-secondary);
  cursor: pointer;
}

.kb-meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 14px;
  font-size: 12px;
}
.kb-meta-grid > div { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.kb-meta-grid > div.full { grid-column: 1 / -1; }
.kb-meta-grid span { color: var(--text-muted); }
.kb-meta-grid strong { font-weight: 500; word-break: break-all; }
.kb-meta-grid .mono { font-family: Consolas, monospace; font-size: 11px; }

.kb-error-box {
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(220, 80, 80, 0.16);
  color: #ffb4b0;
  font-size: 12px;
}

.kb-chunk-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
  color: var(--text-secondary);
  border-top: 1px solid rgba(255, 255, 255, 0.10);
  padding-top: 10px;
}
.kb-chunk-count { color: var(--text-muted); font-size: 11.5px; }

.kb-chunks {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-right: 4px;
}
.kb-chunk {
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.08);
}
.kb-chunk-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-muted);
}
.kb-chunk-idx { font-weight: 600; color: var(--text-secondary); }
.kb-chunk-type {
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.10);
}
.kb-chunk-path {
  margin-top: 5px;
  font-size: 11.5px;
  color: var(--text-muted);
  word-break: break-word;
}
.kb-chunk-text {
  margin: 6px 0 0;
  font-family: inherit;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.kb-placeholder {
  flex: 1;
  display: grid;
  place-items: center;
  color: var(--text-muted);
  font-size: 13px;
}

@media (max-width: 1100px) {
  .kb-workspace { grid-template-columns: 1fr; }
  .kb-detail { max-height: 46vh; }
  .kb-tools .search-box { width: 180px; }
}
</style>
