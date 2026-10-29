<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAtlasStore } from '../stores/atlas'
import { useUiStore } from '../stores/ui'
import { createStarField } from '../three/starfield'
import Icon from '../components/ui/Icon.vue'
import { formatNumber, plainText, shortDocTitle } from '../utils/format'

const route = useRoute()
const router = useRouter()
const ui = useUiStore()
const atlas = useAtlasStore()

const stage = ref(null)
const atlasRoot = ref(null)
const immersive = ref(false)
let nativeFullscreen = false
const engineReady = ref(false)
// 移动端一进来就展开左面板会盖住整张星图，按宽度决定初始状态。
const panelsOpen = ref(typeof window === 'undefined' ? true : window.innerWidth >= 900)
const algoOpen = ref(false)
const searchInput = ref('')
const searchField = ref(null)
const focusRing = ref(false)
let focusTimer = null
function pulseFocusRing() {
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches) return
  focusRing.value = false
  requestAnimationFrame(() => { focusRing.value = true })
  if (focusTimer) window.clearTimeout(focusTimer)
  focusTimer = window.setTimeout(() => { focusRing.value = false }, 1150)
}
const hoverLabel = ref('')
const hoverPoint = ref(null)
const hoverAt = ref({ x: 0, y: 0 })
const focusIndex = ref(0)

const MOTION_KEY = 'jxnu.atlas.motion'
const AUTO_KEY = 'jxnu.atlas.autorotate'
const LABEL_KEY = 'jxnu.atlas.labels'
const systemReduceQuery =
  typeof window !== 'undefined' ? window.matchMedia?.('(prefers-reduced-motion: reduce)') : null
const systemReduced = ref(Boolean(systemReduceQuery?.matches))

function readMotionOverride() {
  try {
    return window.localStorage.getItem(MOTION_KEY) === 'on'
  } catch {
    return false
  }
}

// 系统开了“减少动态效果”时默认安静，但给一个显眼的开关：一次点击就恢复全部动效并记住选择。
const motionOverride = ref(readMotionOverride())
const motionMuted = computed(() => systemReduced.value && !motionOverride.value)
if (motionOverride.value && typeof document !== 'undefined') {
  document.documentElement.dataset.motion = 'on'
}

const prefersReducedMotion = computed(() => motionMuted.value)

function readAutoRotate() {
  if (motionMuted.value) return false
  try {
    const raw = window.localStorage.getItem(AUTO_KEY)
    if (raw === 'off') return false
    if (raw === 'on') return true
  } catch {
    /* 隐私模式下 localStorage 可能不可用，回退到默认开启 */
  }
  return true
}
const autoRotate = ref(readAutoRotate())

function readLabelsOn() {
  // 窄屏默认也显示文档名，但引擎会把标签数量限制为 4 个，避免盖住星群。
  const fallback = true
  try {
    const raw = window.localStorage.getItem(LABEL_KEY)
    if (raw === 'on') return true
    if (raw === 'off') return false
    return fallback
  } catch {
    return fallback
  }
}

const labelsOn = ref(readLabelsOn())

function enableMotion() {
  motionOverride.value = true
  try {
    window.localStorage.setItem(MOTION_KEY, 'on')
  } catch {
    /* 忽略隐私模式写入失败 */
  }
  if (typeof document !== 'undefined') document.documentElement.dataset.motion = 'on'
  engine?.setReducedMotion(false)
  autoRotate.value = true
  engine?.setAutoRotate(true)
  try {
    window.localStorage.setItem(AUTO_KEY, 'on')
  } catch {
    /* 同上 */
  }
  ui.notify('已开启完整动效：自转、星云呼吸与转场', 'ok')
}
const panelOrigin = ref({ x: 96, y: 10 })
const panelRef = ref(null)

/** 详情面板的展开圆心：以面板自身盒子为参照换算成百分比，避免圆心落在盒子外把内容裁掉。 */
function placePanelOrigin(screenX, screenY) {
  const box = panelRef.value?.getBoundingClientRect?.()
  if (!box || !box.width || !box.height) {
    panelOrigin.value = { x: 96, y: 10 }
    return
  }
  const px = ((screenX - box.left) / box.width) * 100
  const py = ((screenY - box.top) / box.height) * 100
  panelOrigin.value = {
    x: Math.min(96, Math.max(4, Number.isFinite(px) ? px : 96)),
    y: Math.min(96, Math.max(4, Number.isFinite(py) ? py : 10)),
  }
}
const hoverFlip = computed(() => (typeof window === 'undefined' ? false : hoverAt.value.x > window.innerWidth - 340))
const panelStyle = computed(() => ({
  '--origin-x': `${panelOrigin.value.x.toFixed(1)}%`,
  '--origin-y': `${panelOrigin.value.y.toFixed(1)}%`,
}))

let engine = null
let searchTimer = null
let cameraBeforeDetail = null

const points = computed(() => atlas.points)
const docs = computed(() =>
  (atlas.documents || []).map((doc) => {
    const meta = atlas.docById.get(doc.file_md5)
    return { ...doc, hue: meta?.hue ?? 212 }
  }),
)
const selected = computed(() => atlas.selected)
const selectedDoc = computed(() => atlas.selectedDoc)
const matches = computed(() => atlas.matchCount)
const total = computed(() => atlas.totalChunks)
const loading = computed(() => atlas.status === 'loading')
const failed = computed(() => atlas.status === 'error')
const empty = computed(() => atlas.status === 'ready' && !total.value)
const results = computed(() => atlas.searchResults)

const docsExpanded = ref(false)

const docFilterList = computed(() => (docsExpanded.value ? docs.value : docs.value.slice(0, 8)))

const docFilterName = computed(() => {
  if (!atlas.docFilter) return '全部文档'
  const doc = atlas.docById.get(atlas.docFilter)
  return doc ? shortDocTitle(doc.original_name || doc.file_name, 22) : '已筛选文档'
})

const progressRatio = computed(() => {
  const { loaded, total: count } = atlas.progress
  if (!count) return 0
  return Math.min(1, loaded / count)
})

const algorithm = computed(() => atlas.algorithm)
const semanticEdges = computed(() => atlas.meta?.algorithm?.semantic_edges || null)

const activeResultIndex = computed(() => {
  if (!atlas.selectedId) return -1
  return results.value.findIndex((point) => point.id === atlas.selectedId)
})

function docHue(md5) {
  return atlas.docById.get(md5)?.hue ?? 212
}

function docName(md5) {
  const doc = atlas.docById.get(md5)
  if (!doc) return '未知文档'
  return shortDocTitle(doc.original_name || doc.file_name, 40)
}

function pointLabel(point) {
  if (!point) return ''
  return `${docName(point.file_md5)} · #${String(point.chunk_index ?? 0).padStart(4, '0')}`
}

/** 只有 PDF 分片带真实页码；Markdown/Word 的 page 字段不可靠，改显示章节路径。 */
function pageOf(point) {
  if (!point) return ''
  const type = String(atlas.docById.get(point.file_md5)?.file_type || '').toLowerCase()
  return type === 'pdf' ? point.page || '' : ''
}

function resultSnippet(point) {
  if (!point) return ''
  const raw = point.preview || point.text || ''
  return plainText(raw)
    .replace(/\|/g, ' ')
    .replace(/-{3,}/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim()
    .slice(0, 130)
}

function pushFilters() {
  if (!engine) return
  engine.setFilter(atlas.filteredIds)
}

const locateError = ref('')
const locateMd5 = ref('')

// 面板会遮住画面：把星体让到「真正看得见的那块区域」的正中，而不是画布正中。
const PANEL_GAP = 24
const LEFT_PANEL_W = 296
const DETAIL_W = 392

function focusOffset() {
  if (typeof window === 'undefined') return { x: 0, y: 0 }
  const vw = window.innerWidth
  const vh = window.innerHeight
  if (vw < 900) {
    // 手机上详情是底部抽屉（约 62vh），把星体抬到上半部的正中。
    return { x: 0, y: -Math.round(vh * 0.2) }
  }
  const railW = immersive.value ? 0 : 78
  const leftEdge = railW + (panelsOpen.value && !immersive.value ? LEFT_PANEL_W + PANEL_GAP : 0)
  const rightEdge = vw - (atlas.selectedId ? DETAIL_W + PANEL_GAP : 0)
  const freeCenter = (leftEdge + rightEdge) / 2
  return { x: Math.round(freeCenter - (railW + (vw - railW) / 2)), y: 0 }
}

function selectedOffset() {
  return atlas.selectedId ? focusOffset() : undefined
}

// 「最大查看尺度」：以该分片所属文档的真实分片分布为准，保证选中星与其同文档星群
// 都在画面里（后端给的 radius 是分位数，不能直接当包围盒用）。
function focusDistanceFor(point) {
  if (!point) return undefined
  const center = atlas.docById.get(point.file_md5)?.center || [point.x, point.y, point.z]
  let extent = 0
  for (const item of atlas.points) {
    if (item.file_md5 !== point.file_md5) continue
    const dx = item.x - center[0]
    const dy = item.y - center[1]
    const dz = item.z - center[2]
    extent = Math.max(extent, Math.sqrt(dx * dx + dy * dy + dz * dz))
  }
  return Math.min(110, Math.max(26, extent * 2.25 + 8))
}

function selectPoint(point, { focus = true } = {}) {
  if (!point) {
    atlas.clearSelection()
    return
  }
  if (!atlas.selectedId) {
    // 第一次打开详情时记下镜头，关闭时才能回到原来的探索状态。
    cameraBeforeDetail = engine?.saveCameraState() || null
  }
  atlas.select(point.id)
  const screen = engine?.toScreen(point)
  nextTick(() => placePanelOrigin(screen?.x ?? window.innerWidth / 2, screen?.y ?? window.innerHeight / 2))
  if (focus) {
    const index = results.value.findIndex((item) => item.id === point.id)
    if (index >= 0) focusIndex.value = index
  }
}

function clearSelection() {
  atlas.clearSelection()
  engine?.setHovered('')
  if (cameraBeforeDetail) {
    engine?.restoreCameraState(cameraBeforeDetail, 780)
    cameraBeforeDetail = null
  }
}

function onCanvasSelect(payload) {
  const point = payload?.point ?? payload ?? null
  if (!point) {
    clearSelection()
    return
  }
  // 用星体在屏幕上的位置作为详情面板的展开原点，形成"从星体长出档案"的空间连续感。
  const screenX = payload?.x ?? window.innerWidth / 2
  const screenY = payload?.y ?? window.innerHeight / 2
  if (!atlas.selectedId) cameraBeforeDetail = engine?.saveCameraState() || null
  atlas.select(point.id)
  nextTick(() => placePanelOrigin(screenX, screenY))
}

function onCanvasHover(payload) {
  const point = payload?.point ?? payload ?? null
  hoverPoint.value = point
  atlas.hoveredId = point?.id || ''
  hoverLabel.value = point ? pointLabel(point) : ''
  if (point && payload) hoverAt.value = { x: payload.x, y: payload.y }
}

function toggleLabels() {
  labelsOn.value = !labelsOn.value
  engine?.setLabelsVisible(labelsOn.value && !immersive.value)
  try {
    window.localStorage.setItem(LABEL_KEY, labelsOn.value ? 'on' : 'off')
  } catch {
    /* 忽略隐私模式下的写入失败 */
  }
  ui.notify(labelsOn.value ? '文档名已显示' : '文档名已隐藏', 'info')
}

function toggleAutoRotate() {
  autoRotate.value = !autoRotate.value
  engine?.setAutoRotate(autoRotate.value)
  try {
    window.localStorage.setItem(AUTO_KEY, autoRotate.value ? 'on' : 'off')
  } catch {
    /* 忽略隐私模式下的写入失败 */
  }
  ui.notify(autoRotate.value ? '自动观测已开启' : '自动观测已暂停', 'info')
}

async function leaveImmersive() {
  immersive.value = false
  if (document.fullscreenElement === atlasRoot.value) {
    try {
      await document.exitFullscreen()
    } catch {
      /* 浏览器已退出全屏时，页面布局仍正常恢复。 */
    }
  }
  nativeFullscreen = false
}

async function toggleImmersive() {
  if (immersive.value) return leaveImmersive()
  if (selected.value) clearSelection()
  immersive.value = true
  if (atlasRoot.value?.requestFullscreen) {
    nativeFullscreen = true
    try {
      await atlasRoot.value.requestFullscreen()
    } catch {
      // 移动浏览器不支持全屏时，使用同样铺满视口的页面布局。
      nativeFullscreen = false
    }
  }
}

function onFullscreenChange() {
  if (nativeFullscreen && document.fullscreenElement !== atlasRoot.value) {
    nativeFullscreen = false
    immersive.value = false
  }
}

watch(immersive, (value) => {
  engine?.setImmersive(value)
  engine?.setLabelsVisible(labelsOn.value && !value)
})

function focusMatch(step = 1) {
  if (!results.value.length) return
  focusIndex.value = (focusIndex.value + step + results.value.length) % results.value.length
  const point = results.value[focusIndex.value]
  if (!point) return
  selectPoint(point)
}

function focusFirstMatch() {
  if (!results.value.length) return
  focusIndex.value = 0
  const point = results.value[0]
  selectPoint(point)
}

function onSearchInput() {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    atlas.setQuery(searchInput.value)
  }, 260)
}

function clearSearch() {
  searchInput.value = ''
  atlas.setQuery('')
}

function toggleDoc(md5) {
  atlas.setDocFilter(atlas.docFilter === md5 ? '' : md5)
  const doc = atlas.docById.get(md5)
  if (doc) engine?.focusDocument(doc)
}

function toggleType(key) {
  atlas.setTypeFilter(atlas.typeFilter === key ? '' : key)
}

function clearFilters() {
  atlas.clearFilters()
  searchInput.value = ''
}

function resetView() {
  engine?.resetView()
}

const docLabels = ref([])

function focusDocLabel(md5) {
  const doc = atlas.docById.get(md5)
  if (doc) engine?.focusDocument(doc)
}

function focusSelectedDoc() {
  if (selectedDoc.value) engine?.focusDocument(selectedDoc.value)
  else if (atlas.docFilter) engine?.focusDocument(atlas.docById.get(atlas.docFilter))
}

async function reload() {
  await atlas.reload()
  await mountData()
}

async function mountData() {
  if (!engine || atlas.status !== 'ready') return
  const chainPairs = atlas.chainPairs.map(([from, to]) => ({
    from,
    to,
    fromHue: docHue(from.file_md5),
    toHue: docHue(to.file_md5),
  }))
  engine.setData({
    points: atlas.points,
    documents: docs.value,
    edges: atlas.edgesResolved,
    chainPairs,
  })
  engine.setShowSemanticEdges(atlas.showSemanticEdges)
  engine.setShowChains(atlas.showChains)
  engineReady.value = true
  pushFilters()

  const focus = route.query.focus ? String(route.query.focus) : ''
  const chunk = route.query.chunk ? String(route.query.chunk) : ''
  const doc = route.query.doc ? String(route.query.doc) : ''
  if (focus) {
    // 先用「文档:分片序号」精确命中；失败再按 Milvus 分片 id 兜底（同一分片的两种身份）。
    const point = atlas.byStarKey.get(focus) || (chunk ? atlas.byId.get(chunk) : null)
    if (point) {
      cameraBeforeDetail = engine.saveCameraState() || null
      atlas.select(point.id)
      engine.setSelected(point.id, {
        screenOffset: focusOffset(),
        distance: focusDistanceFor(point),
      })
    } else {
      locateMd5.value = focus.includes(':') ? focus.split(':')[0] : ''
      locateError.value = '星图中没有找到这条出处对应的分片，可能已被重新入库。'
      ui.notify(locateError.value, 'warn')
    }
  } else if (doc) {
    atlas.setDocFilter(doc)
    engine.focusDocument(atlas.docById.get(doc))
  }
}

function copyChunk() {
  const text = selected.value?.text || ''
  if (!text) return
  navigator.clipboard?.writeText(text).then(
    () => ui.notify('分片正文已复制', 'ok'),
    () => ui.notify('复制失败，请手动选择文本', 'warn'),
  )
}

function openInArchive() {
  if (!selected.value) return
  router.push({
    name: 'archive',
    params: { fileMd5: selected.value.file_md5 },
    query: { chunk: String(selected.value.chunk_index ?? 0) },
  })
}

function askWithChunk() {
  if (!selected.value) return
  router.push({
    name: 'inquiry',
    query: { seed: `关于「${docName(selected.value.file_md5)}」第 ${(selected.value.chunk_index ?? 0) + 1} 个分片：` },
  })
}

function toggleSemantic() {
  atlas.showSemanticEdges = !atlas.showSemanticEdges
  engine?.setShowSemanticEdges(atlas.showSemanticEdges)
}

function toggleChains() {
  atlas.showChains = !atlas.showChains
  engine?.setShowChains(atlas.showChains)
}

async function onKeydown(event) {
  const typing = ['INPUT', 'TEXTAREA'].includes(event.target?.tagName)
  if (event.key === 'Escape') {
    if (immersive.value) {
      await leaveImmersive()
      return
    }
    if (selected.value) clearSelection()
    else if (searchInput.value) clearSearch()
    return
  }
  if (event.key === '/' && !typing) {
    event.preventDefault()
    if (immersive.value) await leaveImmersive()
    panelsOpen.value = true
    await nextTick()
    searchField.value?.focus()
    return
  }
  // 键盘用户也能逐颗浏览命中星体，不必依赖鼠标。
  if (!typing && results.value.length && (event.key === 'ArrowRight' || event.key === 'ArrowLeft')) {
    event.preventDefault()
    focusMatch(event.key === 'ArrowRight' ? 1 : -1)
  }
}

watch(
  () => atlas.filteredIds,
  () => {
    pushFilters()
    focusIndex.value = 0
  },
)

watch(
  () => atlas.selectedId,
  (id) => {
    // 唯一的选中入口：带上面板偏移，星体才会落在“剩余可视区”的正中。
    engine?.setSelected(id || '', {
      screenOffset: selectedOffset(),
      distance: focusDistanceFor(atlas.selected),
    })
    engine?.setAutoPaused('detail', Boolean(id))
    if (!id) engine?.setHovered('')
  },
)

watch(
  () => atlas.showSemanticEdges,
  (value) => engine?.setShowSemanticEdges(value),
)

watch(
  () => atlas.showChains,
  (value) => engine?.setShowChains(value),
)

watch(
  () => atlas.focusRequest,
  (request) => {
    if (!request?.pointId) return
    const point = atlas.byId.get(request.pointId)
    if (point) engine?.focusPoint(point)
  },
)

onMounted(async () => {
  systemReduceQuery?.addEventListener?.('change', (event) => {
    systemReduced.value = event.matches
    if (!motionOverride.value) {
      autoRotate.value = !event.matches
      engine?.setReducedMotion(event.matches)
      engine?.setAutoRotate(autoRotate.value)
    }
  })

  // 窄屏只保留分片最多的 4 个文档名，避免文字盖住星群。
  const narrow = window.innerWidth < 900
  engine = createStarField(stage.value, {
    autoRotate: autoRotate.value,
    reducedMotion: prefersReducedMotion.value,
    labelsVisible: labelsOn.value,
    labelLimit: narrow ? 4 : 0,
    onSelect: onCanvasSelect,
    onHover: onCanvasHover,
    onLabels: (list) => {
      docLabels.value = list
    },
  })
  window.addEventListener('keydown', onKeydown)
  document.addEventListener('fullscreenchange', onFullscreenChange)
  if (import.meta.env.DEV) {
    // 仅供浏览器联调脚本读取：生产构建不会包含这段。
    window.__atlas = engine
    window.__atlasDebug = {
      points: () => atlas.points,
      emphasisOf: (id) => engine.getEmphasis(id),
      screenOf: (id) => {
        const point = atlas.byId.get(id)
        return point ? engine.toScreen(point) : null
      },
    }
  }
  if (atlas.status === 'idle') await atlas.load()
  if (atlas.status === 'ready') await mountData()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  if (document.fullscreenElement === atlasRoot.value) document.exitFullscreen().catch(() => {})
  if (searchTimer) window.clearTimeout(searchTimer)
  engine?.dispose()
  engine = null
})
</script>

<template>
  <div ref="atlasRoot" class="atlas" :class="{ 'is-immersive': immersive }">
    <div
      ref="stage"
      class="stage"
      tabindex="0"
      role="application"
      aria-label="知识星图三维视图：拖动旋转、滚轮缩放、斜杠搜索、方向键浏览命中、Esc 取消选择"
      @focus="pulseFocusRing"
    />
    <span v-if="focusRing" class="focus-ring" aria-hidden="true" />

    <div class="vignette" aria-hidden="true" />
    <div class="grain" aria-hidden="true" />
    <div v-if="!motionMuted" class="atlas-veil" aria-hidden="true">
      <span class="veil-line" />
    </div>

    <header class="atlas-head">
      <div class="head-main">
        <p class="eyebrow">星野 <span class="slash">/</span> ATLAS</p>
        <h1 class="head-title">
          知识星图
          <span class="head-count mono">
            {{ formatNumber(atlas.documents.length) }} 篇 · {{ formatNumber(total) }} 星
          </span>
        </h1>
      </div>
      <div class="head-actions">
        <button
          type="button"
          class="ghost-btn mono immersive-toggle"
          :class="{ 'is-on': immersive }"
          :aria-pressed="immersive"
          :aria-label="immersive ? '退出沉浸模式' : '进入沉浸模式'"
          :title="immersive ? '退出沉浸模式（Esc）' : '沉浸观星：收起面板与标签'"
          @click="toggleImmersive"
        >
          <Icon :key="immersive" :name="immersive ? 'collapse' : 'expand'" :size="14" />
          <span>{{ immersive ? '退出沉浸' : '沉浸' }}</span>
        </button>
        <button
          v-if="motionMuted"
          type="button"
          class="ghost-btn mono is-muted"
          title="Windows/系统开启了“减少动态效果”，星图按系统偏好保持静止。点此开启完整动效。"
          @click="enableMotion"
        >
          <Icon name="sparkle" :size="13" />
          <span class="btn-text">动效已按系统关闭 · 开启</span>
        </button>
        <button
          type="button"
          class="ghost-btn mono"
          :class="{ 'is-on': autoRotate }"
          :aria-pressed="autoRotate"
          :title="autoRotate ? '暂停自动观测' : '开启自动观测'"
          @click="toggleAutoRotate"
        >
          <Icon name="refresh" :size="13" :class="{ orbit: autoRotate }" />
          <span class="btn-text">{{ autoRotate ? '自动观测' : '已暂停' }}</span>
        </button>
        <button
          v-if="!immersive"
          type="button"
          class="ghost-btn mono"
          :class="{ 'is-on': labelsOn }"
          :aria-pressed="labelsOn"
          :title="labelsOn ? '隐藏文档名（分类名称）' : '显示文档名（分类名称）'"
          @click="toggleLabels"
        >
          <Icon :name="labelsOn ? 'eye' : 'eyeOff'" :size="13" />
          <span class="btn-text">文档名</span>
        </button>
        <button v-if="!immersive" type="button" class="ghost-btn mono" :disabled="loading" @click="reload">
          <Icon name="refresh" :size="13" :class="{ spin: loading }" />
          <span class="btn-text">重建</span>
        </button>
        <button v-if="!immersive" type="button" class="ghost-btn mono" :class="{ 'is-on': panelsOpen }" @click="panelsOpen = !panelsOpen">
          <Icon name="layers" :size="13" />
          <span class="btn-text">面板</span>
        </button>
      </div>
    </header>

    <div class="hud-top mono">
      <span class="hud-dot" :class="{ live: loading }" />
      <span v-if="loading">加载中 {{ formatNumber(atlas.progress.loaded) }} / {{ formatNumber(atlas.progress.total) }}</span>
      <span v-else-if="failed">星图未能构建</span>
      <span v-else>{{ formatNumber(total) }} 个分片 · {{ formatNumber(atlas.edges.length) }} 条语义连线</span>
    </div>

    <aside v-if="panelsOpen && !immersive && !failed" class="panel left-panel" :class="{ 'is-hidden': !panelsOpen }">
      <div class="panel-block">
        <label class="search-box atlas-search">
          <Icon name="search" :size="14" />
          <input
            ref="searchField"
            v-model="searchInput"
            type="search"
            placeholder="搜索分片正文、章节、文档名"
            aria-label="搜索知识分片"
            @input="onSearchInput"
            @keydown.enter.prevent="focusFirstMatch"
          />
          <kbd class="mono">/</kbd>
        </label>
        <div class="match-row">
          <span class="mono match-count">{{ formatNumber(matches) }} / {{ formatNumber(total) }} 命中</span>
          <span v-if="results.length" class="mono result-pos">{{ activeResultIndex >= 0 ? activeResultIndex + 1 : 1 }} / {{ results.length }}</span>
          <button type="button" class="mini-btn" :disabled="!results.length" aria-label="上一个命中" @click="focusMatch(-1)">
            <Icon name="chevronLeft" :size="11" />
          </button>
          <button type="button" class="mini-btn" :disabled="!results.length" aria-label="下一个命中" @click="focusMatch(1)">
            <Icon name="chevronRight" :size="11" />
          </button>
        </div>
        <ul v-if="results.length" class="result-list">
          <li v-for="point in results.slice(0, 7)" :key="point.id">
            <button type="button" class="result-row" :class="{ 'is-active': point.id === atlas.selectedId }" @click="selectPoint(point)">
              <span class="result-hue" :style="{ background: `hsl(${docHue(point.file_md5)} 24% 68%)` }" />
              <span class="result-text">
                <span class="result-doc">{{ docName(point.file_md5) }}</span>
                <span class="result-snippet">{{ resultSnippet(point) }}</span>
              </span>
              <span class="mono result-no">#{{ String(point.chunk_index ?? 0).padStart(4, '0') }}</span>
            </button>
          </li>
        </ul>
        <p v-else-if="atlas.query" class="empty-hint mono">没有命中，试试更短的关键词</p>
      </div>

      <div class="panel-block">
        <p class="panel-label mono">文档 · {{ docFilterName }}</p>
        <div class="doc-chips">
          <button
            type="button"
            class="doc-chip"
            :class="{ 'is-on': !atlas.docFilter }"
            @click="toggleDoc('')"
          >
            全部
          </button>
          <button
            v-for="doc in docFilterList"
            :key="doc.file_md5"
            type="button"
            class="doc-chip"
            :class="{ 'is-on': atlas.docFilter === doc.file_md5 }"
            :title="`${docName(doc.file_md5)} · ${doc.chunk_count} 片`"
            @click="toggleDoc(doc.file_md5)"
          >
            <span class="chip-hue" :style="{ background: `hsl(${doc.hue} 24% 68%)` }" />
            {{ shortDocTitle(doc.original_name || doc.file_name, 12) }}
            <span class="mono chip-count">{{ doc.chunk_count }}</span>
          </button>
        </div>
        <button
          v-if="docs.length > 8"
          type="button"
          class="doc-more mono"
          :aria-expanded="docsExpanded"
          @click="docsExpanded = !docsExpanded"
        >
          {{ docsExpanded ? '收起文档' : `展开全部 ${docs.length} 篇` }}
        </button>

        <p class="panel-label mono">类型</p>
        <div class="type-row">
          <button
            v-for="option in atlas.typeOptions"
            :key="option.key"
            type="button"
            class="type-chip mono"
            :class="{ 'is-on': atlas.typeFilter === option.key }"
            @click="toggleType(option.key)"
          >
            {{ option.key.toUpperCase() }} {{ option.count }}
          </button>
        </div>

        <div class="layer-toggles">
          <button type="button" class="layer-toggle mono" :class="{ 'is-on': atlas.showChains }" @click="toggleChains">
            <span class="line-swatch chain" />
            星链（真实顺序）
          </button>
          <button type="button" class="layer-toggle mono" :class="{ 'is-on': atlas.showSemanticEdges }" @click="toggleSemantic">
            <span class="line-swatch semantic" />
            语义连线
          </button>
        </div>

        <button v-if="atlas.query || atlas.docFilter || atlas.typeFilter" type="button" class="link-btn mono" @click="clearFilters">
          清除全部筛选
        </button>
      </div>

      <div class="panel-block algo-block">
        <button type="button" class="algo-head mono" @click="algoOpen = !algoOpen">
          <span>关系与坐标说明</span>
          <Icon name="chevronDown" :size="11" :class="{ flip: algoOpen }" />
        </button>
        <div v-if="algoOpen" class="algo-body">
          <p>
            <strong>星体</strong>＝Milvus 中一个真实分片（同一集合，无抽样）。星群中心来自文档向量质心的
            经典 MDS 降维，星群之间会被后端做一次「去重叠」推开，星群内部的偏移来自分片向量的局部主成分——
            这三步都只服务观看，不改变分片归属与顺序；同一篇文档的星体天然聚在一起，也只是因为它们的语义接近。
          </p>
          <p>
            <strong>星链</strong>＝同一文档内 chunk_index 相邻的两片，是真实的顺序关系。
            <strong>语义连线</strong>＝跨文档 embedding 余弦相似度
            <template v-if="semanticEdges">
              ≥ {{ semanticEdges.min_score }}，最多 {{ semanticEdges.max_edges }} 条（当前 {{ formatNumber(atlas.edges.length) }} 条）
            </template>
            的计算结果，不是人工标注。
          </p>
          <p v-if="algorithm?.layout">排布算法：{{ algorithm.layout }}</p>
        </div>
      </div>
    </aside>

    <div v-if="!immersive" class="doc-labels" aria-hidden="true">
      <button
        v-for="label in docLabels"
        :key="label.md5"
        type="button"
        class="doc-label"
        :style="{
          left: `${label.x}px`,
          top: `${label.y}px`,
          opacity: 0.72 + Math.sqrt(label.weight ?? 0.5) * 0.28,
          fontSize: `${10 + (label.weight ?? 0.5) * 2.6}px`,
        }"
        :title="`${label.title} · ${label.count} 个分片`"
        @click="focusDocLabel(label.md5)"
      >
        <span class="doc-label-name">{{ label.title }}</span>
        <span class="doc-label-count mono">{{ label.count }}</span>
      </button>
    </div>

    <div
      v-if="hoverPoint && !selected"
      class="hover-card"
      :class="{ 'is-flip': hoverFlip }"
      :style="{ left: `${hoverAt.x + 22}px`, top: `${Math.max(84, hoverAt.y - 168)}px` }"
      role="status"
      aria-live="polite"
    >
      <p class="hover-doc">
        {{ docName(hoverPoint.file_md5) }}
        <span class="mono hover-no">#{{ String(hoverPoint.chunk_index ?? 0).padStart(4, '0') }}</span>
      </p>
      <p class="hover-snippet">{{ resultSnippet(hoverPoint) }}</p>
      <p class="hover-meta mono">
        {{ (hoverPoint.block_type || 'chunk').toUpperCase() }} · {{ formatNumber(hoverPoint.chars) }} 字
        <template v-if="pageOf(hoverPoint)"> · 第 {{ pageOf(hoverPoint) }} 页</template>
      </p>
    </div>

    <div class="hud-bottom">
      <p class="legend mono">拖动旋转 · 滚轮缩放 · 悬停预览 · 点击星体</p>
      <button type="button" class="ghost-btn mono" @click="resetView">
        <Icon name="refresh" :size="12" />
        复位视角
      </button>
    </div>

    <transition name="atlas-panel">
      <aside v-if="selected" ref="panelRef" class="panel right-panel" :style="panelStyle" aria-label="星体详情">
        <transition name="panel-swap" mode="out-in">
          <div :key="selected.id" class="star-body-wrap">
        <header class="star-head">
          <div class="star-title">
            <p class="eyebrow mono">
              <span class="star-hue" :style="{ background: `hsl(${docHue(selected.file_md5)} 24% 68%)` }" />
              CHUNK · #{{ String(selected.chunk_index ?? 0).padStart(4, '0') }}
            </p>
            <h2>{{ docName(selected.file_md5) }}</h2>
          </div>
          <button type="button" class="icon-btn" aria-label="关闭详情" @click="clearSelection">
            <Icon name="close" :size="14" />
          </button>
        </header>

        <dl class="star-meta">
          <div>
            <dt class="mono">文档类型</dt>
            <dd>{{ (selectedDoc?.file_type || '—').toUpperCase() }}</dd>
          </div>
          <div>
            <dt class="mono">分片序号</dt>
            <dd>{{ selected.chunk_index }} / {{ selectedDoc?.chunk_count ?? '—' }}</dd>
          </div>
          <div>
            <dt class="mono">字数</dt>
            <dd>{{ formatNumber(selected.chars) }}</dd>
          </div>
          <div>
            <dt class="mono">{{ pageOf(selected) ? '页码' : '章节' }}</dt>
            <dd>{{ pageOf(selected) || selected.section_path || '—' }}</dd>
          </div>
        </dl>

        <p v-if="selected.section_path" class="star-section mono">{{ selected.section_path }}</p>

        <div class="star-text">
          <p>{{ selected.text }}</p>
        </div>

        <footer class="star-actions">
          <button type="button" class="btn solid sm" @click="openInArchive">
            <Icon name="archive" :size="12" />
            在典藏打开
          </button>
          <button type="button" class="btn ghost sm" @click="askWithChunk">
            <Icon name="inquiry" :size="12" />
            就此提问
          </button>
          <button type="button" class="btn ghost sm" @click="copyChunk">
            <Icon name="copy" :size="12" />
            复制
          </button>
        </footer>
        <p class="star-note mono">
          文档指纹 {{ selected.file_md5.slice(0, 16) }}…
          <button type="button" class="link-btn mono" @click="focusSelectedDoc">聚焦星群</button>
        </p>
          </div>
        </transition>
      </aside>
    </transition>

    <div v-if="loading" class="overlay">
      <div class="loader">
        <p class="mono loader-tag">BUILDING THE SKY</p>
        <p class="loader-title">
          <template v-if="atlas.progress.total">
            正在把 {{ formatNumber(atlas.progress.total) }} 个分片放回天空
          </template>
          <template v-else>正在连接知识库索引</template>
        </p>
        <div class="loader-bar" :class="{ 'is-indeterminate': !atlas.progress.total }">
          <span :style="atlas.progress.total ? { width: `${Math.max(6, progressRatio * 100)}%` } : null" />
        </div>
        <p class="mono loader-note">
          <template v-if="atlas.progress.total">
            {{ formatNumber(atlas.progress.loaded) }} / {{ formatNumber(atlas.progress.total) }} ·
            分页拉取中，不会省略任何分片
          </template>
          <template v-else>读取星图元数据 · 分片将逐页点亮</template>
        </p>
      </div>
    </div>

    <div v-if="locateError" class="locate-card" role="status">
      <p class="locate-title mono">LOCATE FAILED</p>
      <p class="locate-text">{{ locateError }}</p>
      <div class="locate-actions">
        <RouterLink v-if="locateMd5" class="btn btn--sm" :to="{ name: 'archive', params: { fileMd5: locateMd5 } }">
          在典藏打开该文档
        </RouterLink>
        <button type="button" class="btn btn--sm btn--quiet" @click="locateError = ''">关闭</button>
      </div>
    </div>

    <div v-else-if="failed" class="overlay">
      <div class="loader is-error">
        <p class="mono loader-tag">ATLAS UNAVAILABLE</p>
        <p class="loader-title">{{ atlas.error || '知识星图构建失败' }}</p>
        <p class="loader-note">如果是知识库尚未就绪，可以先回到「问学」；恢复后再重建星图。</p>
        <div class="loader-actions">
          <button type="button" class="btn ghost sm" @click="reload">重试</button>
          <RouterLink class="btn ghost sm" :to="{ name: 'archive' }">去典藏</RouterLink>
        </div>
      </div>
    </div>

    <div v-else-if="empty" class="overlay">
      <div class="loader">
        <p class="mono loader-tag">EMPTY SKY</p>
        <p class="loader-title">知识库还是空的</p>
        <p class="loader-note">上传第一份校务文档后，星图会把它的每个分片点亮。</p>
        <RouterLink class="btn solid sm" :to="{ name: 'archive' }">去上传文档</RouterLink>
      </div>
    </div>
  </div>
</template>

<style scoped>
.atlas {
  position: relative;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: #090a0a;
  color: var(--ink);
}

.atlas.is-immersive {
  position: fixed;
  inset: 0;
  z-index: 100;
  width: 100%;
  height: 100%;
}

.is-immersive .hud-top,
.is-immersive .legend {
  display: none;
}

.stage {
  position: absolute;
  inset: 0;
  z-index: 1;
}

.stage :deep(canvas) {
  display: block;
  width: 100%;
  height: 100%;
}

.focus-ring {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 24px;
  height: 24px;
  margin: -12px 0 0 -12px;
  border: 1px solid rgba(218, 195, 141, 0.9);
  border-radius: 50%;
  pointer-events: none;
  z-index: 4;
  animation: focus-ring 1100ms var(--ease-out) forwards;
}

@keyframes focus-ring {
  0% {
    transform: scale(0.5);
    opacity: 0.9;
  }
  70% {
    opacity: 0.6;
  }
  100% {
    transform: scale(1.9);
    opacity: 0;
  }
}

.vignette {
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
  background: radial-gradient(circle at 50% 46%, transparent 48%, rgba(3, 4, 8, 0.3) 100%);
}

.grain {
  position: absolute;
  inset: 0;
  z-index: 3;
  pointer-events: none;
  opacity: 0.16;
  background-image: var(--grain);
  mix-blend-mode: overlay;
}

/* 入场遮罩：两道夜色从上下合拢，中央亮线拉开，随后整体退去。
   只做遮挡与光线变化，不拦截任何指针操作，也不会掩盖真实加载状态。 */
.atlas-veil {
  position: absolute;
  inset: 0;
  z-index: 30;
  pointer-events: none;
  overflow: hidden;
  animation: veil-away 760ms cubic-bezier(0.16, 1, 0.3, 1) 480ms forwards;
}

.atlas-veil::before,
.atlas-veil::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  height: 50.5%;
  background: #05050a;
  animation: veil-band 780ms cubic-bezier(0.16, 1, 0.3, 1) forwards;
}

.atlas-veil::before {
  top: 0;
  transform-origin: top center;
}

.atlas-veil::after {
  bottom: 0;
  transform-origin: bottom center;
  animation-delay: 40ms;
}

.veil-line {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(242, 200, 121, 0.9), transparent);
  transform: translate(-50%, -50%);
  animation: veil-line 900ms cubic-bezier(0.16, 1, 0.3, 1) forwards;
}

@keyframes veil-band {
  0% {
    transform: scaleY(1);
  }
  55% {
    transform: scaleY(0.32);
  }
  100% {
    transform: scaleY(0);
  }
}

@keyframes veil-line {
  0% {
    width: 0;
    opacity: 0;
  }
  35% {
    width: 42vw;
    opacity: 1;
  }
  70% {
    width: 86vw;
    opacity: 0.5;
  }
  100% {
    width: 100vw;
    opacity: 0;
  }
}

@keyframes veil-away {
  to {
    opacity: 0;
    visibility: hidden;
  }
}

.orbit {
  animation: spin 9s linear infinite;
}

.atlas-head {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  z-index: 6;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 24px 12px;
  background: linear-gradient(to bottom, rgba(6, 7, 11, 0.72), transparent);
  pointer-events: none;
}

.atlas-head > * {
  pointer-events: auto;
}

.head-title {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin: 3px 0 0;
  font-family: var(--font-serif);
  font-size: 22px;
  font-weight: 500;
  letter-spacing: 0.04em;
}

.head-count {
  font-size: 11px;
  letter-spacing: 0.08em;
  color: var(--ink-3);
}

.head-actions {
  display: flex;
  gap: 8px;
}

.ghost-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  padding: 0 6px;
  border: 0;
  border-bottom: 1px solid transparent;
  border-radius: 0;
  font-size: 11px;
  white-space: nowrap;
  letter-spacing: 0.04em;
  color: var(--ink-2);
  background: transparent;
  transition: color var(--t-fast), border-color var(--t-fast);
}

.ghost-btn:hover {
  color: var(--ink);
  border-bottom-color: var(--line-strong);
}

.ghost-btn.is-on {
  color: var(--accent);
  border-color: var(--accent-line);
}

.ghost-btn:disabled {
  opacity: 0.5;
}

.spin {
  animation: spin 1.1s linear infinite;
}

.hud-top {
  position: absolute;
  left: 26px;
  bottom: 76px;
  z-index: 5;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  letter-spacing: 0.08em;
  color: var(--ink-3);
  text-shadow: 0 1px 10px rgba(0, 0, 0, 0.85);
  pointer-events: none;
}

.hud-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--ink-4);
}

.hud-dot.live {
  background: var(--accent);
  animation: pulse 1.3s ease-in-out infinite;
}

.panel {
  position: absolute;
  z-index: 7;
  border: 1px solid rgba(237, 231, 218, 0.09);
  background: rgba(20, 21, 21, 0.96);
  box-shadow: none;
}

.left-panel {
  top: 86px;
  left: 22px;
  width: 296px;
  max-height: calc(100% - 172px);
  overflow-y: auto;
  border-radius: var(--r-md);
  animation: fade-up 420ms var(--ease-out) both;
}

.panel-block {
  padding: 14px 14px 12px;
}

.panel-block + .panel-block {
  border-top: 1px solid rgba(237, 231, 218, 0.09);
}

.ghost-btn.is-muted {
  border-color: color-mix(in srgb, var(--accent) 55%, transparent);
  color: var(--accent);
}

.atlas-head,
.panel.left-panel,
.hud-bottom,
.hud-top {
  animation: atlas-rise 620ms var(--ease-out) both;
}

.panel.left-panel {
  animation-delay: 80ms;
}

.hud-bottom {
  animation-delay: 160ms;
}

@keyframes atlas-rise {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.atlas-search {
  background: rgba(237, 231, 218, 0.05);
}

.atlas-search kbd {
  padding: 1px 4px;
  border: 1px solid var(--line-strong);
  border-radius: 3px;
  font-size: 11px;
  color: var(--ink-4);
}

.match-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}

.match-count {
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--ink-3);
}

.result-pos {
  margin-left: auto;
  font-size: 11px;
  color: var(--ink-4);
}

.mini-btn {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border: 1px solid var(--line);
  border-radius: 4px;
  color: var(--ink-3);
}

.mini-btn:hover:not(:disabled) {
  color: var(--ink);
  border-color: var(--ink-3);
}

.mini-btn:disabled {
  opacity: 0.3;
}

.result-list {
  list-style: none;
  margin: 8px -6px 0;
  padding: 0;
}

.result-row {
  display: grid;
  grid-template-columns: 4px minmax(0, 1fr) auto;
  gap: 9px;
  width: 100%;
  padding: 8px 6px;
  border-radius: 4px;
  text-align: left;
  transition: background var(--t-fast);
}

.result-row:hover,
.result-row.is-active {
  background: rgba(237, 231, 218, 0.06);
}

.result-hue {
  width: 3px;
  height: 100%;
  border-radius: 2px;
  opacity: 0.8;
}

.result-text {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.result-doc {
  font-size: 11px;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.result-snippet {
  font-size: 11px;
  line-height: 1.5;
  color: var(--ink-3);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.result-no {
  font-size: 11px;
  color: var(--ink-4);
}

.empty-hint {
  margin: 10px 0 2px;
  font-size: 11px;
  color: var(--ink-4);
}

.panel-label {
  margin: 0 0 8px;
  font-size: 11px;
  letter-spacing: 0.16em;
  color: var(--ink-4);
}

.panel-block .panel-label + .doc-chips {
  margin-bottom: 12px;
}

.doc-chips {
  display: grid;
  gap: 1px;
  margin-top: 2px;
}

.doc-chip {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  height: 24px;
  padding: 0 6px;
  text-align: left;
  border: 0;
  border-bottom: 1px solid transparent;
  border-radius: 0;
  font-size: 11px;
  color: var(--ink-3);
  background: transparent;
}

.doc-chip:hover {
  color: var(--ink);
  background: rgba(237, 231, 218, 0.05);
}

.doc-chip.is-on {
  color: var(--ink);
  background: rgba(237, 231, 218, 0.07);
  box-shadow: inset 2px 0 var(--accent);
}

.chip-hue {
  width: 5px;
  height: 5px;
  border-radius: 50%;
}

.doc-more {
  margin: 8px 0 12px;
  font-size: 11px;
  letter-spacing: 0.08em;
  color: var(--ink-4);
  text-align: left;
}

.doc-more:hover {
  color: var(--accent);
}

.chip-count {
  margin-left: auto;
  font-size: 11px;
  opacity: 0.7;
}

.type-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 12px;
}

.type-chip {
  height: 22px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 4px;
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--ink-3);
}

.type-chip.is-on {
  color: var(--ink);
  border-color: var(--ink-3);
}

.layer-toggles {
  display: grid;
  gap: 4px;
  margin-bottom: 10px;
}

.layer-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 4px;
  font-size: 11px;
  color: var(--ink-4);
  text-align: left;
}

.layer-toggle.is-on {
  color: var(--ink-2);
}

.line-swatch {
  width: 18px;
  height: 1px;
  background: currentColor;
}

.line-swatch.chain {
  background: #a9bcd8;
  opacity: 0.7;
}

.line-swatch.semantic {
  background: #9c8fe0;
  opacity: 0.8;
}

.link-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--accent);
  letter-spacing: 0.04em;
}

.algo-block {
  padding-bottom: 6px;
}

.algo-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  font-size: 11px;
  letter-spacing: 0.12em;
  color: var(--ink-3);
}

.algo-head svg {
  transition: transform var(--t-base);
}

.algo-head svg.flip {
  transform: rotate(180deg);
}

.algo-body {
  margin-top: 10px;
  font-size: 11px;
  line-height: 1.8;
  color: var(--ink-3);
}

.algo-body p {
  margin: 0 0 8px;
}

.algo-body strong {
  color: var(--ink-2);
  font-weight: 600;
}

/* 星群注记：屏幕空间渲染，字号不随缩放变化，压住时后排自动让位。 */
.doc-labels {
  position: absolute;
  inset: 0;
  z-index: 4;
  pointer-events: none;
}

.doc-label {
  position: absolute;
  transform: translate(-50%, calc(-100% - 2px));
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  padding: 2px 5px 3px;
  border: 0;
  background: transparent;
  color: rgba(237, 231, 218, 0.8);
  font-family: var(--font-ui);
  font-size: 11.5px;
  letter-spacing: 0.03em;
  line-height: 1.25;
  white-space: nowrap;
  /* 文档名只是注记：不能挡住星体的悬停与点选，否则同一位置会出现“看得见却选不中”。 */
  pointer-events: none;
  /* 没有底板，靠两层暗投影把字从星云里"压"出来。 */
  text-shadow: 0 1px 3px rgba(3, 4, 8, 0.92);
  transition:
    color 180ms ease,
    opacity 220ms var(--ease-out),
    text-shadow 180ms ease;
}

.doc-label:hover {
  color: rgba(255, 250, 240, 0.98);
}

.doc-label-count {
  font-size: 0.78em;
  letter-spacing: 0.1em;
  opacity: 0.8;
}

.locate-card {
  position: absolute;
  left: 50%;
  bottom: 108px;
  z-index: 7;
  width: min(420px, calc(100% - 40px));
  transform: translateX(-50%);
  padding: 14px 16px 12px;
  border: 1px solid rgba(226, 104, 76, 0.45);
  border-radius: var(--r-sm);
  background: rgba(10, 11, 16, 0.95);
}

.locate-title {
  margin: 0;
  font-size: 11px;
  letter-spacing: 0.18em;
  color: var(--accent);
}

.locate-text {
  margin: 6px 0 10px;
  font-size: 12.5px;
  line-height: 1.6;
  color: rgba(240, 235, 224, 0.82);
}

.locate-actions {
  display: flex;
  gap: 8px;
}

.hover-card {
  position: absolute;
  z-index: 6;
  width: min(268px, 42vw);
  padding: 9px 12px 10px;
  border: 1px solid rgba(237, 231, 218, 0.14);
  border-left: 2px solid var(--accent);
  border-radius: 4px;
  background: rgba(8, 9, 13, 0.96);
  box-shadow: 0 12px 28px -24px rgba(0, 0, 0, 0.9);
  pointer-events: none;
  animation: hover-in 160ms var(--ease-out) both;
}

.hover-card.is-flip {
  transform: translateX(-100%);
  margin-left: -30px;
}

.hover-doc {
  margin: 0;
  font-family: var(--font-serif);
  font-size: 12.5px;
  line-height: 1.4;
  color: var(--ink);
}

.hover-no {
  margin-left: 6px;
  font-size: 11px;
  color: var(--ink-3);
}

.hover-snippet {
  margin: 4px 0 0;
  font-size: 11px;
  line-height: 1.55;
  color: var(--ink-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.hover-meta {
  margin: 6px 0 0;
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--ink-3);
}

@keyframes label-in {
  from {
    opacity: 0;
    transform: translate(-50%, calc(-100% + 6px));
  }
  to {
    opacity: 1;
    transform: translate(-50%, -100%);
  }
}

@keyframes hover-in {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
}

.hud-bottom {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 26px;
  background: linear-gradient(to top, rgba(5, 6, 10, 0.92), transparent);
  pointer-events: none;
}

.hud-bottom > * {
  pointer-events: auto;
}

.legend {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11px;
  letter-spacing: 0.08em;
  color: var(--ink-3);
}

.legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.legend-sep {
  opacity: 0.5;
}

.star-body-wrap {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
}

.panel-swap-enter-active {
  transition: opacity 260ms var(--ease-out), transform 260ms var(--ease-out);
}

.panel-swap-leave-active {
  transition: opacity 110ms linear, transform 110ms linear;
}

.panel-swap-enter-from {
  opacity: 0;
  transform: translateY(7px);
}

.panel-swap-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

.right-panel {
  top: 86px;
  right: 22px;
  bottom: 68px;
  width: min(392px, 40vw);
  display: flex;
  flex-direction: column;
  border-radius: var(--r-md);
  overflow: hidden;
  /* 详情从被点中的那颗星的位置展开：clip-path 圆以 --origin-x/--origin-y 为圆心。
     变量由 panelStyle 每次选中时写入，切换星体时圆心随之移动，不会整块重开。 */
  clip-path: circle(162% at var(--origin-x, 96%) var(--origin-y, 10%));
}

.atlas-panel-enter-active {
  transition:
    clip-path 520ms var(--ease-out),
    opacity 300ms ease,
    transform 520ms var(--ease-out);
}

.atlas-panel-leave-active {
  transition:
    opacity 180ms ease,
    transform 180ms ease;
}

.atlas-panel-enter-from {
  clip-path: circle(0% at var(--origin-x, 96%) var(--origin-y, 10%));
  opacity: 0;
  transform: translateY(8px) scale(0.992);
}

.atlas-panel-leave-to {
  opacity: 0;
  transform: translateY(4px) scale(0.996);
}

@media (prefers-reduced-motion: reduce) {
  .atlas-veil {
    display: none;
  }

  .atlas-panel-enter-active,
  .atlas-panel-leave-active {
    transition: opacity 120ms linear;
  }

  .atlas-panel-enter-from,
  .atlas-panel-leave-to {
    clip-path: none;
    transform: none;
  }

  .orbit {
    animation: none;
  }
}

.star-head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 16px 16px 12px;
  border-bottom: 1px solid rgba(237, 231, 218, 0.09);
}

.star-title {
  flex: 1;
  min-width: 0;
}

.star-title h2 {
  margin: 5px 0 0;
  font-family: var(--font-serif);
  font-size: 18px;
  font-weight: 500;
  line-height: 1.45;
  letter-spacing: 0.01em;
}

.star-hue {
  display: inline-block;
  width: 5px;
  height: 5px;
  margin-right: 6px;
  border-radius: 50%;
  vertical-align: middle;
}

.star-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  margin: 0;
  background: rgba(237, 231, 218, 0.08);
  border-bottom: 1px solid rgba(237, 231, 218, 0.09);
}

.star-meta > div {
  padding: 9px 16px;
  background: rgba(9, 10, 16, 0.74);
}

.star-meta dt {
  font-size: 11px;
  letter-spacing: 0.14em;
  color: var(--ink-4);
}

.star-meta dd {
  margin: 4px 0 0;
  font-size: 11px;
  color: var(--ink-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.star-section {
  margin: 0;
  padding: 10px 16px 0;
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--ink-4);
}

.star-text {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 16px 16px;
}

.star-text p {
  margin: 0;
  font-size: 12px;
  line-height: 2;
  color: var(--ink-2);
  white-space: pre-wrap;
  word-break: break-word;
}

.star-actions {
  display: flex;
  gap: 6px;
  padding: 10px 14px;
  border-top: 1px solid rgba(237, 231, 218, 0.09);
  flex-wrap: wrap;
}

.star-note {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin: 0;
  padding: 8px 16px 12px;
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--ink-3);
}

.overlay {
  position: absolute;
  inset: 78px 0 0;
  z-index: 9;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(4, 5, 9, 0.72);
}

.loader {
  width: min(420px, 100%);
  padding: 26px 26px 24px;
  border: 1px solid rgba(237, 231, 218, 0.14);
  border-radius: var(--r-md);
  background: rgba(9, 10, 16, 0.82);
  text-align: left;
}

.loader.is-error {
  border-color: rgba(207, 106, 90, 0.4);
}

.loader-tag {
  margin: 0;
  font-size: 11px;
  letter-spacing: 0.24em;
  color: var(--accent);
}

.loader-title {
  margin: 10px 0 14px;
  font-family: var(--font-serif);
  font-size: 20px;
  line-height: 1.5;
  letter-spacing: 0.02em;
}

.loader-bar {
  height: 2px;
  background: rgba(237, 231, 218, 0.14);
  overflow: hidden;
}

.loader-bar span {
  display: block;
  height: 100%;
  background: var(--accent);
  transition: width 260ms linear;
}

/* 元数据还没回来时不假装有进度：走一条不确定态的光带。 */
.loader-bar.is-indeterminate span {
  width: 38%;
  animation: loader-sweep 1.4s cubic-bezier(0.45, 0, 0.55, 1) infinite;
}

@keyframes loader-sweep {
  0% {
    transform: translateX(-110%);
  }
  100% {
    transform: translateX(290%);
  }
}

.loader-note {
  margin: 10px 0 0;
  font-size: 11px;
  line-height: 1.8;
  letter-spacing: 0.04em;
  color: var(--ink-4);
}

.loader-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}

.sheet-pop-enter-active,
.sheet-pop-leave-active {
  transition: opacity 260ms var(--ease-out), transform 320ms var(--ease-out);
}

.sheet-pop-enter-from,
.sheet-pop-leave-to {
  opacity: 0;
  transform: translateX(18px) scale(0.99);
}

@media (max-width: 1180px) {
  .left-panel {
    width: 274px;
  }

  .right-panel {
    width: 340px;
  }
}

@media (max-width: 640px) {
  .doc-label {
    font-size: 11px;
    letter-spacing: 0.01em;
    padding: 1px 2px;
  }

  .doc-label .label-count {
    font-size: 11px;
  }
}

@media (max-width: 900px) {
  .atlas-head {
    padding: 14px 16px 10px;
  }

  .head-actions {
    gap: 6px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  .ghost-btn {
    padding: 0 8px;
  }

  /* 窄屏只留图标，避免五个开关把抬头挤成两行 */
  .ghost-btn .btn-text {
    display: none;
  }

  .head-title {
    font-size: 18px;
  }

  .head-count {
    display: none;
  }

  .left-panel {
    top: auto;
    left: 10px;
    right: 10px;
    bottom: 56px;
    width: auto;
    max-height: 46%;
  }

  .right-panel {
    top: auto;
    left: 10px;
    right: 10px;
    bottom: 56px;
    width: auto;
    max-height: 58%;
  }

  .hud-top {
    left: 16px;
    bottom: 46px;
  }

  .hud-bottom {
    padding: 10px 14px;
  }

  .legend {
    display: none;
  }

  .hover-chip {
    display: none;
  }
}
</style>
