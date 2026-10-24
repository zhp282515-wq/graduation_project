<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useLibraryStore, stageLabel } from '../stores/library'
import { useUiStore } from '../stores/ui'
import { useConfirm } from '../composables/confirm'
import Icon from '../components/ui/Icon.vue'
import { formatBytes, formatNumber, relativeTime, shortDocTitle } from '../utils/format'

const route = useRoute()
const router = useRouter()
const ui = useUiStore()
const library = useLibraryStore()
const { confirm } = useConfirm()

const searchInput = ref('')
const fileInput = ref(null)
const dragging = ref(false)
const expanded = reactive(new Set())
const chunkNodes = new Map()

let searchTimer = null

const TYPE_LABEL = { md: 'MD', doc: 'DOC', docx: 'DOCX', pdf: 'PDF', txt: 'TXT' }
const STATUS_TEXT = { pending: '等待处理', processing: '处理中', ready: '已入库', failed: '失败' }

const docs = computed(() => library.items || [])
const activeDoc = computed(() => library.activeItem)
const hasSelection = computed(() => Boolean(library.activeMd5))

const facets = computed(() => library.facets || { all: 0, md: 0, doc: 0, docx: 0, pdf: 0, txt: 0 })
// 抬头统计取后端聚合值；当前页求和只能算出这一页的分片数，会严重偏小。
const docTotal = computed(() => Number(library.overview?.documents) || facets.value.all || 0)
const totalChunks = computed(
  () => Number(library.overview?.chunks) || docs.value.reduce((sum, doc) => sum + (Number(doc.chunk_count) || 0), 0),
)
// 只有 PDF 分片带真实页码，其他格式的 page 字段没有意义。
const activeIsPdf = computed(() => String(library.document?.file_type || '').toLowerCase() === 'pdf')

function statusClass(doc) {
  if (!doc) return ''
  if (doc.status === 'failed') return 'err'
  if (doc.status === 'pending' || doc.status === 'processing') return 'busy'
  return 'ok'
}

function docSubtitle(doc) {
  const pieces = [TYPE_LABEL[doc.file_type] || String(doc.file_type || '文件').toUpperCase()]
  if (Number(doc.chunk_count)) pieces.push(`${formatNumber(doc.chunk_count)} 片`)
  if (Number(doc.file_size)) pieces.push(formatBytes(doc.file_size))
  return pieces.join(' · ')
}

function onSearchInput() {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    library.setQuery(searchInput.value.trim())
    library.fetchDocuments()
  }, 300)
}

function clearSearch() {
  searchInput.value = ''
  library.setQuery('')
  library.fetchDocuments()
}

function pickType(key) {
  library.setType(key === library.type ? '' : key)
  library.fetchDocuments()
}

function onSort(event) {
  library.setSort(event.target.value)
  library.fetchDocuments()
}

function onPageSize(event) {
  library.setPageSize(Number(event.target.value))
}

async function selectDoc(doc) {
  await library.openDocument(doc)
  expanded.clear()
}

function closeDetail() {
  library.closeDocument()
}

function toggleChunk(index) {
  if (expanded.has(index)) expanded.delete(index)
  else expanded.add(index)
}

function registerChunk(index, node) {
  if (node) chunkNodes.set(index, node)
  else chunkNodes.delete(index)
}

async function openByMd5(md5, chunkIndex) {
  if (!md5) {
    closeDetail()
    return
  }
  if (library.activeMd5 !== md5) {
    await library.openDocument({ file_md5: md5 })
  }
  if (chunkIndex !== null && chunkIndex !== undefined && chunkIndex !== '') {
    const target = Number(chunkIndex)
    if (Number.isFinite(target)) {
      const targetPage = Math.floor(target / library.chunkPageSize) + 1
      if (targetPage !== library.chunkPage) await library.loadChunks(targetPage)
      await nextTick()
      expanded.add(target)
      await nextTick()
      chunkNodes.get(target)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
  }
}

function syncRoute() {
  const md5 = route.params.fileMd5 ? String(route.params.fileMd5) : ''
  const chunk = route.query.chunk ?? null
  openByMd5(md5, chunk)
}

watch(() => route.params.fileMd5, syncRoute)

watch(
  () => library.activeMd5,
  (md5) => {
    const current = route.params.fileMd5 ? String(route.params.fileMd5) : ''
    if ((md5 || '') === current) return
    if (md5) router.replace({ name: 'archive', params: { fileMd5: md5 } })
    else router.replace({ name: 'archive' })
  },
)

async function handleUpload(files) {
  const list = Array.from(files || [])
  if (!list.length) return
  await library.uploadFiles(list)
  if (library.activeMd5) await library.loadChunks(library.chunkPage)
}

function onFilePick(event) {
  handleUpload(event.target.files)
  event.target.value = ''
}

function onDrop(event) {
  dragging.value = false
  handleUpload(event.dataTransfer?.files)
}

function openUploader() {
  fileInput.value?.click()
}

async function removeDoc(doc) {
  const name = shortDocTitle(doc?.original_name || doc?.file_name)
  const ok = await confirm({
    title: '从知识库删除这份文档？',
    message: `「${name}」及其 ${formatNumber(doc?.chunk_count || 0)} 个分片会从 Milvus 中移除，源文件如果仍在上传目录里也会被删除。这个操作不能撤销。`,
    confirmText: '删除文档',
    tone: 'danger',
  })
  if (!ok) return
  const removed = await library.removeDocument(doc)
  if (removed && library.activeMd5 === doc.file_md5) {
    closeDetail()
    router.replace({ name: 'archive' })
  }
}

async function syncLibrary() {
  await library.runSync()
}

function copyMd5(md5) {
  if (!md5) return
  navigator.clipboard?.writeText(md5).then(
    () => ui.notify('已复制文件指纹', 'ok'),
    () => ui.notify('复制失败，请手动选择', 'warn'),
  )
}

function formatTime(value) {
  if (!value) return '—'
  return relativeTime(value)
}

function stageText(doc) {
  if (!doc) return ''
  if (doc.status === 'failed') return doc.error || '处理失败'
  return stageLabel(doc.status, doc.stage) || STATUS_TEXT[doc.status] || doc.status || ''
}

onMounted(() => {
  if (library.status === 'idle') library.fetchDocuments()
  searchInput.value = library.query
  syncRoute()
})

onBeforeUnmount(() => {
  if (searchTimer) window.clearTimeout(searchTimer)
})
</script>

<template>
  <div class="archive" :class="{ 'has-selection': hasSelection }">
    <header class="view-head archive-head">
      <div class="head-main">
        <p class="eyebrow">典藏 <span class="slash">/</span> ARCHIVE</p>
        <h1 class="head-title">
          知识库档案
          <span class="head-count mono">{{ formatNumber(docTotal) }} 篇 · {{ formatNumber(totalChunks) }} 片</span>
        </h1>
      </div>
      <div class="head-actions">
        <button type="button" class="btn ghost" :disabled="library.syncing" @click="syncLibrary">
          <Icon name="sync" :size="13" :class="{ spin: library.syncing }" />
          {{ library.syncing ? '同步中' : '同步' }}
        </button>
        <button type="button" class="btn solid" @click="openUploader">
          <Icon name="upload" :size="13" />
          上传文档
        </button>
        <input
          ref="fileInput"
          class="sr-only"
          type="file"
          accept=".md,.markdown,.txt,.pdf,.doc,.docx"
          multiple
          tabindex="-1"
          @change="onFilePick"
        />
      </div>
    </header>

    <div class="archive-body">
      <aside class="list-pane">
        <div class="list-tools">
          <label class="search-box">
            <Icon name="search" :size="14" />
            <input
              v-model="searchInput"
              type="search"
              placeholder="搜索标题或原始文件名"
              aria-label="搜索知识库文档"
              @input="onSearchInput"
            />
            <button v-if="searchInput" type="button" class="clear" aria-label="清除搜索" @click="clearSearch">
              <Icon name="close" :size="11" />
            </button>
          </label>

          <div class="facet-row">
            <button
              v-for="facet in library.FACETS"
              :key="facet.key || 'all'"
              type="button"
              class="facet mono"
              :class="{ 'is-on': library.type === facet.key }"
              @click="pickType(facet.key)"
            >
              {{ facet.label }}
              <span class="facet-count">{{ facets[facet.key || 'all'] ?? 0 }}</span>
            </button>
          </div>

          <div class="sort-row">
            <select class="mini-select mono" :value="library.sort" aria-label="排序方式" @change="onSort">
              <option value="uploaded">按入库时间</option>
              <option value="name">按名称</option>
            </select>
            <select class="mini-select mono" :value="library.pageSize" aria-label="每页数量" @change="onPageSize">
              <option :value="10">10 / 页</option>
              <option :value="20">20 / 页</option>
              <option :value="50">50 / 页</option>
            </select>
            <span class="spacer" />
            <span class="mono result-count">{{ formatNumber(library.total) }} 条</span>
          </div>
        </div>

        <div
          class="list-scroll"
          @dragover.prevent="dragging = true"
          @dragleave.prevent="dragging = false"
          @drop.prevent="onDrop"
        >
          <div v-if="library.uploads.length" class="upload-panel">
            <div class="upload-head">
              <span class="mono">上传队列</span>
              <button type="button" class="link-btn mono" @click="library.clearFinishedUploads()">清除已完成</button>
            </div>
            <div v-for="job in library.uploads" :key="job.id" class="upload-item" :data-state="job.state">
              <div class="upload-line">
                <span class="upload-name">{{ job.name }}</span>
                <span class="mono upload-state">{{ job.stateText || stageLabel(job.state, job.stage) }}</span>
                <button
                  v-if="job.state === 'done' || job.state === 'failed'"
                  type="button"
                  class="upload-close"
                  aria-label="收起这条上传记录"
                  @click="library.dismissUpload(job.id)"
                >
                  <Icon name="close" :size="10" />
                </button>
              </div>
              <div class="upload-track">
                <span class="upload-fill" :style="{ width: `${job.progress || (job.state === 'done' ? 100 : 4)}%` }" />
              </div>
              <p v-if="job.error" class="upload-error">{{ job.error }}</p>
            </div>
          </div>

          <div v-if="library.status === 'loading' && !docs.length" class="row-skeletons">
            <span v-for="n in 6" :key="n" class="skeleton row" />
          </div>

          <div v-else-if="library.status === 'error'" class="pane-state">
            <p class="mono state-tag">LOAD FAILED</p>
            <p class="state-text">{{ library.error }}</p>
            <button type="button" class="btn ghost" @click="library.fetchDocuments()">
              <Icon name="refresh" :size="13" />
              重新加载
            </button>
          </div>

          <div v-else-if="!docs.length" class="pane-state">
            <p class="mono state-tag">{{ library.query ? 'NO MATCH' : 'EMPTY SHELF' }}</p>
            <p class="state-text">
              {{ library.query ? '没有找到匹配的档案，换个关键词试试。' : '知识库还是空的。上传第一份校务文档，星图会随之点亮。' }}
            </p>
            <button v-if="!library.query" type="button" class="btn ghost" @click="openUploader">
              <Icon name="upload" :size="13" />
              上传文档
            </button>
            <button v-else type="button" class="btn ghost" @click="clearSearch">清除搜索</button>
          </div>

          <ul v-else class="doc-list">
            <li v-for="doc in docs" :key="doc.file_md5">
              <button
                type="button"
                class="doc-row"
                :class="{ 'is-active': doc.file_md5 === library.activeMd5 }"
                @click="selectDoc(doc)"
              >
                <span class="doc-type mono" :data-type="doc.file_type">{{ TYPE_LABEL[doc.file_type] || 'FILE' }}</span>
                <span class="doc-main">
                  <span class="doc-name">{{ shortDocTitle(doc.original_name || doc.file_name, 40) }}</span>
                  <span class="doc-meta mono">{{ docSubtitle(doc) }} · {{ formatTime(doc.ingested_at || doc.created_at) }}</span>
                </span>
                <span class="doc-status" :class="statusClass(doc)" role="img" :title="stageText(doc)" :aria-label="stageText(doc)" />
              </button>
            </li>
          </ul>

          <div v-if="dragging" class="drop-veil mono">松手开始入库</div>
        </div>

        <div class="list-foot">
          <button type="button" class="pager" :disabled="library.page <= 1" aria-label="上一页" @click="library.setPage(library.page - 1)">
            <Icon name="chevronLeft" :size="12" />
          </button>
          <span class="mono page-label">{{ library.page }} / {{ library.pageCount }}</span>
          <button
            type="button"
            class="pager"
            :disabled="library.page >= library.pageCount"
            aria-label="下一页"
            @click="library.setPage(library.page + 1)"
          >
            <Icon name="chevronRight" :size="12" />
          </button>
          <span class="spacer" />
          <span v-if="library.lastSyncedAt" class="mono foot-note">同步于 {{ formatTime(library.lastSyncedAt) }}</span>
        </div>
      </aside>

      <section class="detail-pane">
        <template v-if="activeDoc">
          <div class="detail-head">
            <button type="button" class="icon-btn back" aria-label="返回列表" @click="closeDetail">
              <Icon name="chevronLeft" :size="15" />
            </button>
            <div class="detail-title">
              <p class="eyebrow mono">文档 · {{ TYPE_LABEL[activeDoc.file_type] || 'FILE' }}</p>
              <h2>{{ shortDocTitle(activeDoc.original_name || activeDoc.file_name, 64) }}</h2>
            </div>
            <div class="detail-actions">
              <RouterLink
                class="icon-btn"
                :to="{ name: 'atlas', query: { doc: activeDoc.file_md5 } }"
                title="在星图中查看这份文档"
                aria-label="在星图中查看这份文档"
              >
                <Icon name="atlas" :size="15" />
              </RouterLink>
              <button
                type="button"
                class="icon-btn danger"
                title="删除文档"
                aria-label="删除文档"
                @click="removeDoc(activeDoc)"
              >
                <Icon name="trash" :size="15" />
              </button>
            </div>
          </div>

          <dl class="meta-grid">
            <div class="meta-cell">
              <dt class="mono">分片</dt>
              <dd>{{ formatNumber(activeDoc.chunk_count) }}</dd>
            </div>
            <div class="meta-cell">
              <dt class="mono">大小</dt>
              <dd>{{ formatBytes(activeDoc.file_size) }}</dd>
            </div>
            <div class="meta-cell">
              <dt class="mono">状态</dt>
              <dd class="status-cell" :class="statusClass(activeDoc)">
                <span class="doc-status" :class="statusClass(activeDoc)" />
                {{ stageText(activeDoc) }}
              </dd>
            </div>
            <div class="meta-cell">
              <dt class="mono">入库</dt>
              <dd>{{ formatTime(activeDoc.ingested_at || activeDoc.updated_at) }}</dd>
            </div>
            <div class="meta-cell wide fingerprint">
              <dt class="mono">指纹</dt>
              <dd>
                <code class="mono">{{ activeDoc.file_md5 }}</code>
                <button type="button" class="link-btn mono" @click="copyMd5(activeDoc.file_md5)">复制</button>
              </dd>
            </div>
            <div v-if="activeDoc.error" class="meta-cell wide error-cell">
              <dt class="mono">错误</dt>
              <dd>{{ activeDoc.error }}</dd>
            </div>
          </dl>

          <div class="chunk-head">
            <p class="mono chunk-label">分片内容 · CHUNKS</p>
            <div class="chunk-pager">
              <button
                type="button"
                class="pager"
                :disabled="library.chunkPage <= 1"
                aria-label="上一页分片"
                @click="library.setChunkPage(library.chunkPage - 1)"
              >
                <Icon name="chevronLeft" :size="12" />
              </button>
              <span class="mono">{{ library.chunkPage }} / {{ library.chunkPageCount }}</span>
              <button
                type="button"
                class="pager"
                :disabled="library.chunkPage >= library.chunkPageCount"
                aria-label="下一页分片"
                @click="library.setChunkPage(library.chunkPage + 1)"
              >
                <Icon name="chevronRight" :size="12" />
              </button>
            </div>
          </div>

          <div v-if="library.chunkStatus === 'error'" class="pane-state inline">
            <p class="mono state-tag">CHUNK LOAD FAILED</p>
            <p class="state-text">{{ library.chunkError }}</p>
            <button type="button" class="btn ghost" @click="library.loadChunks(library.chunkPage)">重试</button>
          </div>

          <div v-else-if="library.chunkStatus === 'loading' && !library.chunks.length" class="chunk-skeletons">
            <span v-for="n in 4" :key="n" class="skeleton chunk" />
          </div>

          <ol v-else-if="library.chunks.length" class="chunk-list">
            <li
              v-for="chunk in library.chunks"
              :key="chunk.chunk_id || chunk.chunk_index"
              :ref="(node) => registerChunk(chunk.chunk_index, node)"
              class="chunk"
              :class="{ 'is-open': expanded.has(chunk.chunk_index) }"
            >
              <button type="button" class="chunk-top" @click="toggleChunk(chunk.chunk_index)">
                <span class="chunk-no mono">#{{ String(chunk.chunk_index).padStart(4, '0') }}</span>
                <span class="chunk-info">
                  <span v-if="chunk.section_path" class="chunk-section">{{ chunk.section_path }}</span>
                  <span class="chunk-tags mono">
                    <span v-if="chunk.page && activeIsPdf">p.{{ chunk.page }}</span>
                    <span v-if="chunk.block_type">{{ chunk.block_type }}</span>
                    <span>{{ formatNumber(chunk.char_count) }} 字</span>
                  </span>
                </span>
                <Icon class="chunk-chev" name="chevronDown" :size="12" />
              </button>
              <p v-if="!expanded.has(chunk.chunk_index)" class="chunk-preview">{{ chunk.text }}</p>
              <p v-else class="chunk-full">{{ chunk.text }}</p>
            </li>
          </ol>

          <div v-else class="pane-state inline">
            <p class="mono state-tag">NO CHUNKS</p>
            <p class="state-text">登记表显示这份文档已入库，但 Milvus 中没有读到分片。可以尝试「同步」重建登记。</p>
          </div>
        </template>

        <div v-else class="detail-empty">
          <div class="empty-figure" aria-hidden="true">
            <span class="ring" />
            <span class="ring ring-2" />
            <Icon name="archive" :size="26" />
          </div>
          <h2 class="empty-title">档案室</h2>
          <p class="empty-text">
            左侧是知识库里的全部文档。选一份，查看它的元数据和每一个分片；
            或者把 .md / .txt / .pdf / .docx 拖进这里入库。
          </p>
          <button type="button" class="btn solid" @click="openUploader">
            <Icon name="upload" :size="13" />
            选择文档
          </button>
          <p class="mono empty-note">单份 ≤ 50MB · 支持 Markdown / 文本 / PDF / Word</p>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.archive {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  /* 与问学同一套内容栅格：抬头、列表、详情都落在 --maxw + --gutter 里 */
  width: 100%;
  max-width: var(--maxw);
  margin-inline: auto;
  padding: 0 var(--gutter);
}

.archive-head {
  flex: 0 0 auto;
  padding: 22px 0 16px;
}

.head-title {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin: 2px 0 0;
  font-family: var(--font-serif);
  font-size: 17px;
  font-weight: 500;
  letter-spacing: 0.02em;
}

.head-count {
  font-size: var(--text-2xs);
  letter-spacing: 0.08em;
  color: var(--ink-3);
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.spin {
  animation: spin 1.1s linear infinite;
}

.archive-body {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(300px, 384px) minmax(0, 1fr);
}

.list-pane {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--line);
}

.list-tools {
  flex: 0 0 auto;
  padding: 14px 16px 10px;
  border-bottom: 1px solid var(--line);
}

.facet-row {
  display: flex;
  flex-wrap: nowrap;
  gap: 4px;
  margin-top: 10px;
  overflow-x: auto;
  padding-bottom: 2px;
  scrollbar-width: none;
  /* 溢出时右缘淡出，避免半个筛选项贴在边上显得像裁切错误 */
  mask-image: linear-gradient(90deg, #000 93%, transparent);
}

.facet-row::-webkit-scrollbar {
  display: none;
}

.facet {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 4px;
  height: 22px;
  padding: 0 7px;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 9.5px;
  letter-spacing: 0.03em;
  color: var(--ink-3);
  transition: color var(--t-fast), border-color var(--t-fast), background var(--t-fast);
}

.facet:hover {
  color: var(--ink);
  border-color: var(--line-strong);
}

.facet.is-on {
  color: var(--accent);
  border-color: var(--accent-line);
  background: var(--accent-soft);
}

.facet-count {
  opacity: 0.6;
}

.sort-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
}

.mini-select {
  height: 26px;
  padding: 0 22px 0 9px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  color: var(--ink-2);
  background-color: transparent;
  background-image: linear-gradient(45deg, transparent 50%, currentColor 50%),
    linear-gradient(135deg, currentColor 50%, transparent 50%);
  background-position: calc(100% - 12px) 11px, calc(100% - 8px) 11px;
  background-size: 4px 4px, 4px 4px;
  background-repeat: no-repeat;
  font-size: 10px;
  letter-spacing: 0.06em;
  cursor: pointer;
  appearance: none;
  -webkit-appearance: none;
  transition: border-color var(--t-fast), color var(--t-fast);
}

.mini-select:hover {
  border-color: var(--line-strong);
  color: var(--ink);
}

.mini-select:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}

.mini-select option {
  background: var(--surface);
  color: var(--ink);
}

.spacer {
  flex: 1;
}

.result-count {
  font-size: 10px;
  color: var(--ink-4);
}

.list-scroll {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.doc-list {
  list-style: none;
  margin: 0;
  padding: 6px 8px;
}

.doc-row {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr) 8px;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 11px 10px;
  border-radius: var(--r-sm);
  text-align: left;
  transition: background var(--t-fast);
}

.doc-row:hover {
  background: var(--surface-2);
}

.doc-row.is-active {
  background: var(--surface-2);
  box-shadow: inset 2px 0 0 var(--accent);
}

.doc-type {
  font-size: 9px;
  letter-spacing: 0.08em;
  color: var(--ink-3);
  padding: 3px 0;
  border-top: 1px solid var(--line-strong);
  border-bottom: 1px solid var(--line-strong);
  text-align: center;
}

.doc-type[data-type='pdf'] {
  color: var(--accent);
  border-color: var(--accent-line);
}

.doc-main {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.doc-name {
  font-family: var(--font-serif);
  font-size: 14px;
  line-height: 1.45;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.doc-meta {
  font-size: 10px;
  letter-spacing: 0.03em;
  color: var(--ink-4);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.doc-status {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ink-4);
}

.doc-status.ok {
  background: var(--ok);
}

.doc-status.busy {
  background: var(--warn);
  animation: pulse 1.4s ease-in-out infinite;
}

.doc-status.err {
  background: var(--err);
}

.upload-panel {
  margin: 10px 10px 4px;
  padding: 10px 12px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface);
}

.upload-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 10px;
  letter-spacing: 0.12em;
  color: var(--ink-3);
}

.upload-item + .upload-item {
  margin-top: 10px;
}

.upload-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.upload-name {
  flex: 1;
  min-width: 0;
  font-size: var(--text-xs);
  color: var(--ink-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.upload-state {
  font-size: 9px;
  color: var(--ink-3);
  letter-spacing: 0.04em;
}

.upload-item[data-state='failed'] .upload-state {
  color: var(--err);
}

.upload-track {
  height: 2px;
  margin-top: 6px;
  background: var(--line);
  overflow: hidden;
}

.upload-fill {
  display: block;
  height: 100%;
  background: var(--accent);
  transition: width 320ms var(--ease-out);
}

.upload-error {
  margin: 6px 0 0;
  font-size: 10px;
  color: var(--err);
}

.upload-close {
  color: var(--ink-4);
}

.row-skeletons {
  display: grid;
  gap: 10px;
  padding: 14px;
}

.row-skeletons .row {
  height: 44px;
}

.pane-state {
  display: grid;
  justify-items: start;
  gap: 10px;
  padding: 34px 22px;
}

.pane-state.inline {
  padding: 26px 4px;
}

.state-tag {
  margin: 0;
  font-size: 10px;
  letter-spacing: 0.2em;
  color: var(--accent);
}

.state-text {
  margin: 0;
  max-width: 42ch;
  font-size: var(--text-xs);
  line-height: 1.85;
  color: var(--ink-3);
}

.drop-veil {
  position: absolute;
  inset: 8px;
  display: grid;
  place-items: center;
  border: 1px dashed var(--accent);
  background: color-mix(in srgb, var(--surface) 88%, transparent);
  color: var(--accent);
  font-size: var(--text-2xs);
  letter-spacing: 0.18em;
  border-radius: var(--r-sm);
}

.list-foot {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-top: 1px solid var(--line);
}

.page-label {
  font-size: 10px;
  color: var(--ink-3);
}

.foot-note {
  font-size: 9px;
  color: var(--ink-4);
}

.detail-pane {
  min-width: 0;
  overflow-y: auto;
  padding: 20px clamp(18px, 2.6vw, 38px) 48px;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--line);
}

.back {
  display: none;
}

.detail-title {
  flex: 1;
  min-width: 0;
}

.detail-title h2 {
  margin: 4px 0 0;
  font-family: var(--font-serif);
  font-size: clamp(20px, 2.2vw, 27px);
  font-weight: 500;
  line-height: 1.35;
  letter-spacing: 0.01em;
  color: var(--ink);
}

.detail-actions {
  display: flex;
  gap: 6px;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  margin: 18px 0 0;
  background: var(--line);
  border: 1px solid var(--line);
}

.meta-cell {
  padding: 11px 13px 13px;
  background: var(--surface);
}

.meta-cell.wide {
  grid-column: 1 / -1;
}

.meta-cell dt {
  font-size: 9px;
  letter-spacing: 0.16em;
  color: var(--ink-4);
}

.meta-cell dd {
  margin: 6px 0 0;
  font-size: var(--text-xs);
  color: var(--ink-2);
}

.status-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-cell.err {
  color: var(--err);
}

.fingerprint dd {
  display: flex;
  align-items: center;
  gap: 10px;
}

.fingerprint code {
  font-size: 10px;
  color: var(--ink-2);
  word-break: break-all;
}

.error-cell dd {
  color: var(--err);
}

.chunk-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 26px 0 10px;
}

.chunk-label {
  margin: 0;
  font-size: 10px;
  letter-spacing: 0.18em;
  color: var(--ink-3);
}

.chunk-pager {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 10px;
  color: var(--ink-3);
}

.chunk-list {
  list-style: none;
  margin: 0;
  padding: 0;
  border-top: 1px solid var(--line);
}

.chunk {
  border-bottom: 1px solid var(--line);
}

.chunk-top {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 12px 2px;
  text-align: left;
}

.chunk-no {
  flex: 0 0 52px;
  font-size: 10px;
  color: var(--ink-4);
  letter-spacing: 0.04em;
}

.chunk-info {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.chunk-section {
  flex: 1;
  min-width: 0;
  font-size: var(--text-xs);
  color: var(--ink-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chunk-tags {
  display: inline-flex;
  gap: 10px;
  font-size: 9px;
  color: var(--ink-4);
}

.chunk-chev {
  color: var(--ink-4);
  transition: transform var(--t-base) var(--ease-out);
}

.chunk.is-open .chunk-chev {
  transform: rotate(180deg);
}

.chunk-preview {
  margin: 0 0 12px 54px;
  font-size: var(--text-xs);
  line-height: 1.85;
  color: var(--ink-3);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.chunk-full {
  margin: 0 0 16px 54px;
  font-size: var(--text-xs);
  line-height: 1.95;
  color: var(--ink-2);
  white-space: pre-wrap;
  word-break: break-word;
}

.chunk-skeletons {
  display: grid;
  gap: 10px;
  padding-top: 10px;
}

.chunk-skeletons .chunk {
  height: 62px;
  border: 0;
}

.detail-empty {
  display: grid;
  justify-items: center;
  gap: 12px;
  max-width: 420px;
  margin: clamp(40px, 12vh, 120px) auto 0;
  text-align: center;
}

.empty-figure {
  position: relative;
  display: grid;
  place-items: center;
  width: 92px;
  height: 92px;
  color: var(--ink-3);
}

.empty-figure .ring {
  position: absolute;
  inset: 0;
  border: 1px solid var(--line-strong);
  border-radius: 50%;
}

.empty-figure .ring-2 {
  inset: 14px;
  border-style: dashed;
  opacity: 0.7;
}

.empty-title {
  margin: 8px 0 0;
  font-family: var(--font-serif);
  font-size: 26px;
  font-weight: 400;
  letter-spacing: 0.06em;
}

.empty-text {
  margin: 0;
  font-size: var(--text-xs);
  line-height: 1.9;
  color: var(--ink-3);
}

.empty-note {
  margin: 4px 0 0;
  font-size: 9px;
  letter-spacing: 0.1em;
  color: var(--ink-4);
}

@media (max-width: 1080px) {
  .archive-body {
    grid-template-columns: minmax(280px, 320px) minmax(0, 1fr);
  }

  .meta-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .archive-body {
    grid-template-columns: minmax(0, 1fr);
  }

  .facet-row {
    flex-wrap: nowrap;
    overflow-x: auto;
    padding-bottom: 2px;
    scrollbar-width: none;
  }

  .facet-row::-webkit-scrollbar {
    display: none;
  }

  .facet {
    flex: 0 0 auto;
  }

  .list-pane {
    border-right: 0;
  }

  .archive.has-selection .list-pane {
    display: none;
  }

  .archive:not(.has-selection) .detail-pane {
    display: none;
  }

  .back {
    display: grid;
  }
}
</style>
