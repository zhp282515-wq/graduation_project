import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { createMeteors } from './meteors'
import { createCosmos } from './cosmos'

/**
 * 知识星图的 WebGL 渲染层。
 *
 * 这里只负责"把真实分片画成星体、把真实关系画成线"：
 * 星体坐标由后端 StarMapBuilder 生成（见 knowledge/starmap.py），
 * 同文档相邻分片的连线是真实顺序关系，语义连线是后端用 embedding 余弦相似度算出来的。
 * 不生成虚构的知识分片或关系；远景星尘与流星仅为背景装饰。
 */

const VERTEX = `
  attribute float aSize;
  attribute float aPhase;
  attribute float aVisible;
  attribute float aEmphasis;
  attribute vec3 aColor;
  uniform float uTime;
  uniform float uPixel;
  uniform float uFocus;
  uniform float uSel;
  varying vec3 vColor;
  varying float vAlpha;
  varying float vEmph;
  varying float vSize;

  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    float dist = max(1.0, -mv.z);
    // 闪烁只做很小的幅度：星星是一颗稳定亮着的光点，不该整体忽明忽暗。
    float twinkle = 0.95 + 0.05 * sin(uTime * 0.9 + aPhase * 6.28318);
    // 高亮只做两件事：轻微放大 + 柔和呼吸，不再画圆环。
    float shimmer = 0.5 + 0.5 * sin(uTime * 1.55 + aPhase * 6.28318);
    float emph = clamp(aEmphasis, 0.0, 2.0);
    float hoverBoost = emph > 0.01 && emph < 1.5 ? (0.78 + 0.34 * shimmer) * emph : 0.0;
    float selectBoost = emph >= 1.5 ? 1.30 + 0.24 * shimmer : 0.0;
    float boost = max(hoverBoost, selectBoost);
    float sizeBoost = 1.0 + (emph >= 1.5 ? 1.55 : 0.8 * emph);
    // 星体只占一两个像素：亮的是一颗粒子，不是一团雾。
    // 距离只做很轻的缩放，星星之间的差别主要来自星等（aSize 与 aColor）。
    float size = aSize * clamp(110.0 / dist, 0.8, 1.5) * twinkle * sizeBoost;
    size = clamp(size, 1.0 + boost * 0.4, emph > 0.01 ? 6.2 : 3.6);
    gl_PointSize = size * uPixel;
    vSize = gl_PointSize;
    // 近亮远暗：让星群有纵深，而不是压成一片白。
    float depth = clamp(uFocus / dist, 0.78, 1.0);
    vColor = aColor;
    float dimOthers = mix(1.0, 0.86, uSel * (1.0 - clamp(emph, 0.0, 1.0)));
    float baseBrightness = mix(0.9, 1.0, smoothstep(0.01, 1.5, emph));
    vAlpha = mix(0.05, 1.0, aVisible) * twinkle * depth * (1.0 + boost * 0.3) * dimOthers * baseBrightness;
    vEmph = boost;
    gl_Position = projectionMatrix * mv;
  }
`

const FRAGMENT = `
  varying vec3 vColor;
  varying float vAlpha;
  varying float vEmph;
  varying float vSize;

  void main() {
    float radius = length(gl_PointCoord - 0.5);
    // 边缘只留一个设备像素的抗锯齿：圆里是实心的，圆外立刻结束，没有渐隐的光晕。
    float edge = clamp(1.0 / max(vSize, 1.0), 0.08, 0.34);
    float disc = 1.0 - smoothstep(0.5 - edge, 0.5, radius);
    if (disc < 0.004) discard;
    // 中心更亮一点：亮星的核心接近白，暗星的核心也只是自己那点灰度。
    float core = 1.0 - smoothstep(0.0, 0.5, radius);
    vec3 color = min(vColor * (1.0 + core * 0.55) * (1.0 + vEmph * 0.85), vec3(1.0));
    gl_FragColor = vec4(color, disc * clamp(vAlpha, 0.0, 1.0));
  }
`

function hueColor(hue, lightness = 0.74, saturation = 0.2) {
  return new THREE.Color().setHSL(((hue % 360) + 360) % 360 / 360, saturation, lightness)
}

function makeRingTexture() {
  const size = 128
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  ctx.strokeStyle = 'rgba(255,255,255,0.9)'
  ctx.lineWidth = 3
  ctx.beginPath()
  ctx.arc(size / 2, size / 2, size / 2 - 6, 0, Math.PI * 2)
  ctx.stroke()
  ctx.globalAlpha = 0.45
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.arc(size / 2, size / 2, size / 2 - 16, 0, Math.PI * 2)
  ctx.stroke()
  const texture = new THREE.CanvasTexture(canvas)
  texture.needsUpdate = true
  return texture
}

function circleGeometry(radius, segments = 128) {
  const positions = new Float32Array((segments + 1) * 3)
  for (let i = 0; i <= segments; i += 1) {
    const angle = (i / segments) * Math.PI * 2
    positions[i * 3] = Math.cos(angle) * radius
    positions[i * 3 + 1] = 0
    positions[i * 3 + 2] = Math.sin(angle) * radius
  }
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  return geometry
}

function easeInOutSine(t) {
  return -(Math.cos(Math.PI * t) - 1) / 2
}

function easeInOutCubic(t) {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
}

export function createStarField(container, options = {}) {
  const {
    onSelect = () => {},
    onHover = () => {},
    onLabels = null,
  labelsVisible: labelsVisibleOption = true,
  labelLimit: labelLimitOption = 0,
    autoRotate = true,
    reducedMotion: reduceOption = null,
  } = options

  const reducedQuery = window.matchMedia?.('(prefers-reduced-motion: reduce)')
  let reducedMotion = reduceOption === null ? Boolean(reducedQuery?.matches) : Boolean(reduceOption)

  const scene = new THREE.Scene()
  scene.fog = new THREE.FogExp2(0x05060a, 0.00055)

  const camera = new THREE.PerspectiveCamera(52, 1, 1, 8000)
  camera.position.set(0, 260, 520)

  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: 'high-performance',
  })
  const lowPower =
    (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 4) ||
    (navigator.deviceMemory && navigator.deviceMemory <= 4)
  const maxRatio = lowPower ? 1.35 : 2
  const baseRatio = Math.min(window.devicePixelRatio || 1, maxRatio)
  let quality = 1
  renderer.setPixelRatio(baseRatio)
  renderer.setClearColor(0x000000, 0)
  renderer.outputColorSpace = THREE.SRGBColorSpace
  container.appendChild(renderer.domElement)

  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.06
  controls.rotateSpeed = 0.46
  controls.zoomSpeed = 0.9
  controls.panSpeed = 0.7
  controls.minDistance = 24
  controls.maxDistance = 3400
  controls.autoRotate = false
  controls.autoRotateSpeed = 0

  const root = new THREE.Group()
  scene.add(root)
  const cosmos = createCosmos({ lowPower })
  scene.add(cosmos.group)
  const meteors = createMeteors({ lowPower })
  scene.add(meteors.mesh)

  const ringTexture = makeRingTexture()

  const starUniforms = {
    uSel: { value: 0 },
    uTime: { value: 0 },
    uPixel: { value: renderer.getPixelRatio() },
    uFocus: { value: 280 },
  }

  let starPoints = null
  let starGeometry = null
  let chainLines = null
  let semanticLines = null
  let rings = null
  let emphasisCurrent = null
  let emphasisGoal = null
  const slotById = new Map()
  let labels = []
  let labelsVisible = labelsVisibleOption !== false
  let labelLimit = Math.max(0, Number(labelLimitOption) || 0)
  let labelSink = typeof onLabels === 'function' ? onLabels : null
  let lastLabelPush = 0
  let immersive = false
  let pointList = []
  let pointIndex = new Map()
  let docRadius = new Map()
  let selectedPoint = null
  let visibility = null
  let selectedId = ''
  let hoveredId = ''
  let disposed = false
  let frameId = 0
  let boundsRadius = 500
  let fitRadius = 90
  let fitDistanceRef = 120
  let hasData = false

  const raycaster = new THREE.Raycaster()
  raycaster.params.Points = { threshold: 4 }
  const pointer = new THREE.Vector2(-2, -2)
  let pointerDirty = false
  let pointerDown = null
  let flight = null

  // ---- 自动旋转 / 交互节流 -------------------------------------------------
  // 旋转由 OrbitControls 驱动（按帧时间推进，天然与刷新率解耦），
  // 这里只负责把「目标速度」平滑地推上去或收下来，避免速度跳变。
  const AUTO_SPEED = 0.5
  const autoReasons = new Set()
  let autoUserEnabled = Boolean(autoRotate)
  let autoSpeed = 0
  let hoverLock = false
  let lastFrameAt = performance.now()
  let animationTime = 0
  let frames = 0
  let fpsWindowStart = performance.now()
  let fps = 0
  let rafPaused = false
  let savedCamera = null
  // 首帧取景的机位快照：复位视角必须回到这里，而不是按当前状态另算一个近似值。
  let initialCamera = null
  const tmpVec = new THREE.Vector3()
  const tmpVec2 = new THREE.Vector3()

  function autoTarget() {
    if (!autoUserEnabled || reducedMotion || rafPaused) return 0
    if (autoReasons.size) return 0
    return AUTO_SPEED
  }

  function setAutoRotate(enabled) {
    autoUserEnabled = Boolean(enabled)
    if (!autoUserEnabled) autoReasons.delete('user-off')
    return autoUserEnabled
  }

  function setLabelsVisible(value) {
    labelsVisible = Boolean(value)
    if (!labelsVisible && labelSink) labelSink([])
  }

  function setLabelLimit(value) {
    labelLimit = Math.max(0, Number(value) || 0)
  }

  function setAutoPaused(reason, paused) {
    if (!reason) return
    if (paused) autoReasons.add(reason)
    else autoReasons.delete(reason)
  }

  function isAutoRotating() {
    return autoSpeed > 0.01
  }

  function onControlsStart() {
    // 用户一上手就把镜头交给手势，避免自动飞行与拖拽互相打架。
    flight = null
    setAutoPaused('pointer', true)
  }

  let pointerIdleTimer = 0
  function onControlsEnd() {
    clearTimeout(pointerIdleTimer)
    pointerIdleTimer = window.setTimeout(() => setAutoPaused('pointer', false), 1200)
  }

  controls.addEventListener('start', onControlsStart)
  controls.addEventListener('end', onControlsEnd)

  function setSize() {
    const width = container.clientWidth || 1
    const height = container.clientHeight || 1
    camera.aspect = width / height
    camera.updateProjectionMatrix()
    renderer.setSize(width, height, false)
    starUniforms.uPixel.value = renderer.getPixelRatio()
  }

  function clearGroup(group) {
    if (!group) return
    group.traverse((child) => {
      if (child.geometry) child.geometry.dispose()
      if (child.material) {
        const materials = Array.isArray(child.material) ? child.material : [child.material]
        materials.forEach((material) => {
          if (material.map && material.map !== ringTexture) {
            material.map.dispose()
          }
          material.dispose()
        })
      }
    })
    root.remove(group)
  }

  function buildRings(radius) {
    const group = new THREE.Group()
    const ink = 0xa39c8d
    const radii = [radius * 0.74, radius * 0.9, radius * 1.0]
    radii.forEach((value, index) => {
      const material = new THREE.LineBasicMaterial({
        color: ink,
        transparent: true,
        opacity: index === 1 ? 0.085 : 0.04,
        depthWrite: false,
      })
      group.add(new THREE.Line(circleGeometry(value), material))
    })

    // 时间轴刻度：每 5 度一格短刻线，每 30 度一格长刻线。
    const tickCount = 72
    const ticks = []
    const outer = radii[2]
    for (let i = 0; i < tickCount; i += 1) {
      const angle = (i / tickCount) * Math.PI * 2
      const long = i % 6 === 0
      const inner = outer * (long ? 0.962 : 0.984)
      ticks.push(Math.cos(angle) * inner, 0, Math.sin(angle) * inner)
      ticks.push(Math.cos(angle) * outer, 0, Math.sin(angle) * outer)
    }
    const tickGeometry = new THREE.BufferGeometry()
    tickGeometry.setAttribute('position', new THREE.Float32BufferAttribute(ticks, 3))
    group.add(
      new THREE.LineSegments(
        tickGeometry,
        new THREE.LineBasicMaterial({ color: ink, transparent: true, opacity: 0.07, depthWrite: false }),
      ),
    )
    return group
  }

  /**
   * 文档标签：只写真实文件名与真实分片数，挂在星群质心上方。
   * 标签随相机距离缩放，放大时不会挤成一片字。
   */
  function shortDocLabel(raw) {
    return String(raw)
      .replace(/\.(md|txt|pdf|docx?)$/i, '')
      .replace(/^江西师范大学\s*[-–—·]?\s*/, '')
      .replace(/\s*[-–—]\s*官网$/i, '')
      .replace(/（修订）|\(修订\)/g, '')
      .trim()
  }

  function buildLabels(documents) {
    // 标签不再画成贴图，而是把每篇文档的锚点交给页面，用 DOM 渲染成像素级清晰的注记。
    const labels = []
    const docs = documents
      .filter((doc) => Number(doc.chunk_count) >= 12)
      .sort((a, b) => Number(b.chunk_count) - Number(a.chunk_count))
    const maxCount = Math.max(1, Number(docs[0]?.chunk_count) || 1)
    docs.forEach((doc) => {
      const center = doc.center || [0, 0, 0]
      const radius = Math.max(3, Number(doc.radius) || 8)
      labels.push({
        position: new THREE.Vector3(
          Number(center[0]) || 0,
          (Number(center[1]) || 0) + radius * 0.92,
          Number(center[2]) || 0,
        ),
        userData: {
          fileMd5: doc.file_md5,
          title: shortDocLabel(doc.file_name || doc.original_name || '未命名文档'),
          count: Number(doc.chunk_count) || 0,
          weight: Math.min(1, Math.max(0.12, (Number(doc.chunk_count) || 0) / maxCount)),
        },
      })
    })
    return labels
  }

  function buildStars(points, documents) {
    const docMap = new Map(documents.map((doc) => [doc.file_md5, doc]))
    const count = points.length
    const positions = new Float32Array(count * 3)
    const colors = new Float32Array(count * 3)
    const sizes = new Float32Array(count)
    const phases = new Float32Array(count)
    const visible = new Float32Array(count).fill(1)
    const emphasis = new Float32Array(count)
    // 真实星空里只有最亮的那几颗看得出星温，其余都是接近白的点。
    const warmStar = new THREE.Color(0xffcf9a)
    const coolStar = new THREE.Color(0xc6d8ff)

    points.forEach((point, index) => {
      positions[index * 3] = Number(point.x) || 0
      positions[index * 3 + 1] = Number(point.y) || 0
      positions[index * 3 + 2] = Number(point.z) || 0
      const doc = docMap.get(point.file_md5)
      const hue = doc?.hue ?? 212
      // 星等：幂律分布——大多是暗星，少数亮星。真实星空的分层就来自这里。
      const rank = (index * 0.7548776662) % 1
      const heft = Math.min(1, (Number(point.size) || 1) / 4.4)
      const magnitude = Math.pow(rank, 1.9) * 0.86 + heft * 0.14
      // 色温：文档色相只留一点点色偏，亮星才看得出冷暖，暗星接近灰白。
      const tint = hueColor(hue, 0.95, 0.14)
      const thermal = Math.max(0, (magnitude - 0.55) / 0.45)
      tint.lerp((index * 0.4142135624) % 1 < 0.5 ? warmStar : coolStar, thermal * 0.5)
      const level = 0.3 + Math.pow(magnitude, 1.0) * 0.7
      colors[index * 3] = tint.r * level
      colors[index * 3 + 1] = tint.g * level
      colors[index * 3 + 2] = tint.b * level
      sizes[index] = 0.95 + magnitude * 2.5
      phases[index] = (index * 0.61803398875) % 1
    })

    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    geometry.setAttribute('aColor', new THREE.BufferAttribute(colors, 3))
    geometry.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1))
    geometry.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1))
    geometry.setAttribute('aVisible', new THREE.BufferAttribute(visible, 1))
    geometry.setAttribute('aEmphasis', new THREE.BufferAttribute(emphasis, 1))
    geometry.computeBoundingSphere()

    const material = new THREE.ShaderMaterial({
      uniforms: starUniforms,
      vertexShader: VERTEX,
      fragmentShader: FRAGMENT,
      transparent: true,
      depthWrite: false,
      // 星体用正常混合：亮就是这一颗星本身的亮。
      // 叠加混合会让星群密集处的点彼此累加，堆出一片没有边界的雾光。
      blending: THREE.NormalBlending,
    })

    return new THREE.Points(geometry, material)
  }

  function buildLines(pairs, { color, opacity, vertexColors = false }) {
    if (!pairs.length) return null
    const positions = new Float32Array(pairs.length * 6)
    const colors = vertexColors ? new Float32Array(pairs.length * 6) : null
    pairs.forEach((pair, index) => {
      const from = pair.from || pair[0]
      const to = pair.to || pair[1]
      positions[index * 6] = from.x
      positions[index * 6 + 1] = from.y
      positions[index * 6 + 2] = from.z
      positions[index * 6 + 3] = to.x
      positions[index * 6 + 4] = to.y
      positions[index * 6 + 5] = to.z
      if (colors) {
        const c1 = hueColor(pair.fromHue ?? 212, 0.46, 0.12)
        const c2 = hueColor(pair.toHue ?? 212, 0.46, 0.12)
        colors[index * 6] = c1.r
        colors[index * 6 + 1] = c1.g
        colors[index * 6 + 2] = c1.b
        colors[index * 6 + 3] = c2.r
        colors[index * 6 + 4] = c2.g
        colors[index * 6 + 5] = c2.b
      }
    })
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    if (colors) geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
    const material = new THREE.LineBasicMaterial({
      color: vertexColors ? 0xffffff : color,
      vertexColors: Boolean(vertexColors),
      transparent: true,
      opacity,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    return new THREE.LineSegments(geometry, material)
  }

  function setData({ points = [], documents = [], edges = [], chainPairs = [] } = {}) {
    // 只做一次"视觉收拢"：每篇文档的分片向其质心按 0.55 倍收缩，
    // 让 54 个星群在三维里彼此分开。归属、顺序、相似度都不变。
    const localScale = 1
    const docCenters = new Map(documents.map((doc) => [doc.file_md5, doc.center || [0, 0, 0]]))
    points = points.map((point) => {
      const center = docCenters.get(point.file_md5)
      if (!center) return point
      return {
        ...point,
        x: center[0] + (point.x - center[0]) * localScale,
        y: center[1] + (point.y - center[1]) * localScale,
        z: center[2] + (point.z - center[2]) * localScale,
      }
    })

    pointList = points
    pointIndex = new Map(points.map((point) => [point.id, point]))
    docRadius = new Map(documents.map((doc) => [doc.file_md5, Math.max(4, Number(doc.radius) || 8)]))
    hasData = true

    if (starPoints) clearGroup(starPoints)
    if (chainLines) clearGroup(chainLines)
    if (semanticLines) clearGroup(semanticLines)
    if (rings) clearGroup(rings)
    rings = null

    const withHue = documents.map((doc) => ({ ...doc }))
    starPoints = buildStars(points, withHue)
    root.add(starPoints)

    labels = buildLabels(withHue)

    chainLines = buildLines(chainPairs, { color: 0xa9b0b8, opacity: 0.055, vertexColors: true })
    if (chainLines) root.add(chainLines)

    const edgePairs = edges
      .map((edge) => {
        const from = edge.from || pointIndex.get(edge.a?.id ?? edge.a)
        const to = edge.to || pointIndex.get(edge.b?.id ?? edge.b)
        return from && to ? { from, to } : null
      })
      .filter(Boolean)
    semanticLines = buildLines(edgePairs, { color: 0x9c948a, opacity: 0.1 })
    if (semanticLines) root.add(semanticLines)

    // 尺度：用分片分布的中位数半径决定相机距离，少数离群星不会把镜头拉太远。
    fitRadius = 90
    const center = new THREE.Vector3()
    if (points.length) {
      const box = new THREE.Box3()
      const vector = new THREE.Vector3()
      points.forEach((point) => {
        vector.set(point.x || 0, point.y || 0, point.z || 0)
        box.expandByPoint(vector)
      })
      box.getCenter(center)
      const distances = points
        .map((point) => center.distanceTo(new THREE.Vector3(point.x || 0, point.y || 0, point.z || 0)))
        .sort((a, b) => a - b)
      const p80 = distances[Math.min(distances.length - 1, Math.floor(distances.length * 0.8))] || 60
      fitRadius = Math.max(24, p80 * 1.35)
      boundsRadius = Math.max(fitRadius, distances[distances.length - 1] || fitRadius)
    }

    // 圆形时间轴：三条同心发丝环 + 72 格刻度，水平铺在星群下方，随星图缓慢自转。
    rings = buildRings(fitRadius * 1.0)
    rings.position.copy(center)
    rings.position.y = center.y - fitRadius * 0.04
    rings.visible = !immersive
    root.add(rings)

    controls.target.copy(center)
    const dir = new THREE.Vector3(0.44, 0.52, 1).normalize()
    // 竖屏（手机）横向视野更窄，按宽高比适度拉远，避免星群被画面左右切掉。
    const aspect = (container.clientWidth || 1) / Math.max(1, container.clientHeight || 1)
    const aspectBoost = aspect < 1 ? Math.pow(1 / Math.max(0.4, aspect), 0.5) : 1
    const fitDistance = fitRadius * 1.72 * aspectBoost
    fitDistanceRef = fitDistance
    const fitPosition = center.clone().addScaledVector(dir, fitDistance)
    initialCamera = { position: fitPosition.clone(), target: center.clone() }
    camera.position.copy(center).addScaledVector(dir, fitDistance)
    controls.minDistance = Math.max(12, fitRadius * 0.08)
    controls.maxDistance = Math.max(fitRadius * 14, boundsRadius * 2.4)
    controls.update()
    if (!reducedMotion) {
      // 入场：从当前机位（至少 1.8 倍取景距离、最多 4.5 倍）缓慢靠岸到默认机位。
      // 用 sine 缓动，避免中段突然加速；3 秒足够慢，又不会让人等。
      const startDistance = fitDistance * 2.85
      camera.position.copy(center).addScaledVector(dir, startDistance)
      startFlight(fitPosition, center, { duration: 3200, ease: 'sine' })
    }

    slotById.clear()
    pointList.forEach((point, index) => slotById.set(point.id, index))
    emphasisCurrent = null
    emphasisGoal = null
    primeEmphasis()
    setSize()
    applyVisibility()
  }

  function applyVisibility() {
    if (!starPoints) return
    const attribute = starPoints.geometry.getAttribute('aVisible')
    const array = attribute.array
    for (let i = 0; i < pointList.length; i += 1) {
      const point = pointList[i]
      if (selectedId && point.id === selectedId) {
        array[i] = 1
        continue
      }
      if (!visibility) {
        array[i] = 1
        continue
      }
      array[i] = visibility.has(point.id) ? 1 : 0
    }
    attribute.needsUpdate = true
  }

  function setFilter(ids) {
    visibility = ids ? new Set(ids) : null
    applyVisibility()
  }

  function saveCameraState() {
    savedCamera = {
      position: camera.position.clone(),
      target: controls.target.clone(),
    }
    return savedCamera
  }

  function restoreCameraState(state = savedCamera, duration = 860) {
    if (!state) return false
    animateCamera(state.position.clone(), state.target.clone(), duration)
    return true
  }

  function primeEmphasis() {
    if (!starPoints) return
    const count = pointList.length
    if (!emphasisCurrent || emphasisCurrent.length !== count) {
      emphasisCurrent = new Float32Array(count)
      emphasisGoal = new Float32Array(count)
    }
    emphasisGoal.fill(0)
    const hoverSlot = hoveredId ? slotById.get(hoveredId) : undefined
    if (hoverSlot !== undefined) emphasisGoal[hoverSlot] = 1
    const selectSlot = selectedId ? slotById.get(selectedId) : undefined
    if (selectSlot !== undefined) emphasisGoal[selectSlot] = 2
  }

  function setSelected(id, { fly = true, screenOffset, distance } = {}) {
    selectedId = id || ''
    selectedPoint = pointIndex.get(selectedId) || null
    applyVisibility()
    primeEmphasis()
    const point = selectedPoint
    if (point) {
      starUniforms.uSel.value = 1
      setAutoPaused('selection', true)
      if (!fly) return
      // 选中：平滑移到视觉中心，并推到允许的最大查看尺度；连续切换时从当前飞行状态接管。
      focusPoint(point, { screenOffset, distance })
    } else {
      starUniforms.uSel.value = 0
      setAutoPaused('selection', false)
    }
  }

  function setHovered(id) {
    hoveredId = id || ''
    const point = pointIndex.get(hoveredId)
    primeEmphasis()
    setAutoPaused('hover', Boolean(point))
  }

  function setShowSemanticEdges(value) {
    if (semanticLines) semanticLines.visible = Boolean(value)
  }

  function setShowChains(value) {
    if (chainLines) chainLines.visible = Boolean(value)
  }

  function desiredDistanceFor(point, current = camera.position.distanceTo(controls.target)) {
    // 选中只做「轻微推近」：保留整片星群在画面里，用户才能继续点旁边另一颗星（A → B 连续切换）。
    // 距离太近会让画面只剩一颗星和空白，反而失去空间感。
    return Math.min(120, Math.max(62, current * 0.88))
  }

  // 星体之间的镜头飞行：起点永远是「此刻的真实机位」，因此连续点击时新目标会从当前
  // 动画的中间状态接管，不会先跑完上一段、也不会瞬移。路径用二次贝塞尔加上一点抬升，
  // 时长按空间距离伸缩（520–1180ms），既有穿行感又不会让人等。
  function startFlight(targetPosition, targetLookAt, options = {}) {
    if (reducedMotion) {
      flight = null
      camera.position.copy(targetPosition)
      controls.target.copy(targetLookAt)
      controls.update()
      return
    }
    const startPosition = camera.position.clone()
    const startTarget = controls.target.clone()
    const span = startPosition.distanceTo(targetPosition)
    const forced = Number(options.duration)
    const duration = Number.isFinite(forced) && forced > 0
      ? Math.min(3600, Math.max(400, forced))
      : Math.min(1180, Math.max(520, 460 + span * 12))
    // 飞行期间暂停自转，避免 OrbitControls 在插值之上继续转动，飞行结束再平滑恢复。
    setAutoPaused('flight', true)
    const lift = Math.min(26, Math.max(2.5, span * 0.13))
    const control = startPosition.clone().add(targetPosition).multiplyScalar(0.5)
    control.y += lift
    flight = {
      startPosition,
      control,
      endPosition: targetPosition.clone(),
      startTarget,
      endTarget: targetLookAt.clone(),
      startedAt: performance.now(),
      duration,
      ease: options.ease === 'sine' ? easeInOutSine : easeInOutCubic,
    }
  }

  function stepFlight(now) {
    if (!flight) return
    const t = Math.min(1, (now - flight.startedAt) / flight.duration)
    const e = (flight.ease || easeInOutCubic)(t)
    const a = (1 - e) * (1 - e)
    const b = 2 * (1 - e) * e
    const c = e * e
    camera.position.set(
      a * flight.startPosition.x + b * flight.control.x + c * flight.endPosition.x,
      a * flight.startPosition.y + b * flight.control.y + c * flight.endPosition.y,
      a * flight.startPosition.z + b * flight.control.z + c * flight.endPosition.z,
    )
    controls.target.set(
      flight.startTarget.x + (flight.endTarget.x - flight.startTarget.x) * e,
      flight.startTarget.y + (flight.endTarget.y - flight.startTarget.y) * e,
      flight.startTarget.z + (flight.endTarget.z - flight.startTarget.z) * e,
    )
    if (t >= 1) {
      flight = null
      setAutoPaused('flight', false)
    }
  }

  function animateCamera(targetPosition, targetLookAt) {
    startFlight(targetPosition, targetLookAt)
  }

  function focusDistanceFor(point) {
    // 「最大查看尺度」：近到能看清这颗星与它周围的同文档星群，又不会穿进星团内部。
    const radius = docRadius.get(point.file_md5) || 8
    return Math.min(56, Math.max(20, radius * 3.4))
  }

  function focusPoint(point, { distance, screenOffset } = {}) {
    if (!point) return
    const target = new THREE.Vector3(point.x, point.y, point.z)
    const direction = camera.position.clone().sub(target)
    if (direction.lengthSq() < 1) direction.set(0.4, 0.5, 1)
    direction.normalize()
    const endDistance = Number.isFinite(distance) ? distance : focusDistanceFor(point)
    // 面板会遮住右侧/底部：把目标点在屏幕上让出这块区域，让星体真正落在“可看的中心”。
    const shifted = target.clone()
    if (screenOffset && (screenOffset.x || screenOffset.y)) {
      const worldPerPixel = (2 * Math.tan((camera.fov * Math.PI) / 360) * endDistance)
        / Math.max(1, renderer.domElement.clientHeight)
      const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0).normalize()
      const up = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1).normalize()
      shifted.addScaledVector(right, -(screenOffset.x || 0) * worldPerPixel)
      shifted.addScaledVector(up, (screenOffset.y || 0) * worldPerPixel)
    }
    startFlight(shifted.clone().add(direction.multiplyScalar(endDistance)), shifted)
  }

  function focusDocument(doc) {
    if (!doc) return
    const center = new THREE.Vector3(doc.center?.[0] || 0, doc.center?.[1] || 0, doc.center?.[2] || 0)
    const radius = Math.max(Number(doc.radius) || 90, 60)
    const direction = camera.position.clone().sub(center)
    if (direction.lengthSq() < 1) direction.set(0.3, 0.45, 1)
    direction.normalize()
    startFlight(center.clone().add(direction.multiplyScalar(radius * 2.9)), center)
  }

  function resetView() {
    // 复位 = 回到星图首帧取景时的机位（位置与朝向都恢复），而不是围绕当前目标另算一个距离。
    if (!initialCamera) return
    startFlight(initialCamera.position.clone(), initialCamera.target.clone(), { duration: 900 })
  }

  function toScreen(point) {
    const vector = new THREE.Vector3(point.x, point.y, point.z).project(camera)
    return {
      x: ((vector.x + 1) / 2) * container.clientWidth,
      y: ((1 - vector.y) / 2) * container.clientHeight,
      visible: vector.z < 1,
    }
  }

  function pick(event) {
    const rect = renderer.domElement.getBoundingClientRect()
    const px = event.clientX - rect.left
    const py = event.clientY - rect.top
    const x = (px / rect.width) * 2 - 1
    const y = -(py / rect.height) * 2 + 1
    if (!starPoints) return null

    // 拾取阈值跟着相机距离走：远处星群在屏幕上更密，阈值必须换算成"像素半径"，
    // 否则高 DPI / 拉远之后鼠标明明指着星体却选不中。
    const worldPerPixel =
      (2 * Math.tan((camera.fov * Math.PI) / 360) * camera.position.distanceTo(controls.target)) /
      Math.max(1, rect.height)
    raycaster.params.Points.threshold = Math.max(0.35, worldPerPixel * 11)
    raycaster.setFromCamera({ x, y }, camera)

    const hits = raycaster.intersectObject(starPoints, false)
    if (!hits.length) return null

    // 命中后不再盲信"第一个交点"：把候选逐一投影回屏幕，按真实像素距离 +
    // 深度惩罚排序。这样重叠星体里被指到的那颗才会胜出，悬停不会乱跳。
    const visible = starPoints.geometry.getAttribute('aVisible')
    let best = null
    let bestScore = Infinity
    const limit = Math.min(hits.length, 48)
    for (let i = 0; i < limit; i += 1) {
      const hit = hits[i]
      const index = hit.index
      if (visible && visible.array[index] < 0.5) continue
      const point = pointList[index]
      if (!point) continue
      tmpVec.set(point.x, point.y, point.z).project(camera)
      if (tmpVec.z > 1) continue
      const sx = (tmpVec.x * 0.5 + 0.5) * rect.width
      const sy = (-tmpVec.y * 0.5 + 0.5) * rect.height
      const dx = sx - px
      const dy = sy - py
      const dist = Math.hypot(dx, dy)
      if (dist > 16) continue
      // 深度惩罚只用于同屏重叠时的偏好：前排优先，但不会压过明显的像素距离优势。
      const score = dist + i * 0.6
      if (score < bestScore) {
        bestScore = score
        best = { point, sx, sy }
      }
    }
    return best
  }

  let hoverFrame = 0
  let lastHoverAt = 0
  function onPointerMove(event) {
    if (pointerDown) return
    pointer.x = event.clientX
    pointer.y = event.clientY
    // 悬停识别按帧节流：鼠标高频移动时不会每次都做射线/投影计算。
    if (hoverFrame) return
    hoverFrame = requestAnimationFrame(() => {
      hoverFrame = 0
      const now = performance.now()
      if (now - lastHoverAt < 24) return
      lastHoverAt = now
      const hit = pick(event)
      const id = hit?.point?.id || ''
      if (id !== hoveredId) {
        setHovered(id)
        onHover(hit ? { point: hit.point, x: hit.sx, y: hit.sy } : null)
      }
      renderer.domElement.style.cursor = hit ? 'pointer' : 'grab'
    })
  }

  function onPointerLeave() {
    if (hoverFrame) {
      cancelAnimationFrame(hoverFrame)
      hoverFrame = 0
    }
    if (hoveredId) {
      setHovered('')
      onHover(null)
    }
  }

  function onPointerDown(event) {
    pointerDown = { x: event.clientX, y: event.clientY, time: performance.now() }
  }

  function onPointerUp(event) {
    const down = pointerDown
    pointerDown = null
    if (!down) return
    const moved = Math.hypot(event.clientX - down.x, event.clientY - down.y)
    const elapsed = performance.now() - down.time
    if (moved > 6 || elapsed > 700) return
    const hit = pick(event)
    onSelect(hit ? { point: hit.point, x: hit.sx, y: hit.sy } : { point: null, x: 0, y: 0 })
  }

  function onResize() {
    setSize()
  }

  function onVisibility() {
    if (document.hidden) {
      // 页面不可见时彻底停止渲染，省电也避免回来时一帧堆积。
      rafPaused = true
      if (frameId) cancelAnimationFrame(frameId)
      frameId = 0
    } else if (rafPaused) {
      rafPaused = false
      lastFrameAt = performance.now()
      if (!frameId) render()
    }
  }

  function onReducedMotionChange(event) {
    reducedMotion = Boolean(event.matches)
    if (reducedMotion) {
      meteors.reset()
      autoSpeed = 0
      controls.autoRotate = false
    }
  }

  const observer = new ResizeObserver(onResize)
  observer.observe(container)
  renderer.domElement.style.cursor = 'grab'
  renderer.domElement.addEventListener('pointermove', onPointerMove)
  renderer.domElement.addEventListener('pointerleave', onPointerLeave)
  renderer.domElement.addEventListener('pointerdown', onPointerDown)
  renderer.domElement.addEventListener('pointerup', onPointerUp)
  document.addEventListener('visibilitychange', onVisibility)
  reducedQuery?.addEventListener?.('change', onReducedMotionChange)
  setSize()

  function render() {
    if (disposed) return
    frameId = requestAnimationFrame(render)
    if (rafPaused) return

    const now = performance.now()
    const dt = Math.min(0.06, Math.max(0, (now - lastFrameAt) / 1000))
    lastFrameAt = now
    // 时间只在渲染时累加：切走标签页再回来，星体闪烁与刻度环都从原处继续，不会突跳。
    if (!reducedMotion) animationTime += dt
    starUniforms.uTime.value = animationTime
    meteors.update(dt, container.clientWidth, container.clientHeight, {
      enabled: !reducedMotion && hasData,
      paused: autoReasons.size > 0 || Boolean(flight),
    })

    const target = autoTarget()
    autoSpeed += (target - autoSpeed) * Math.min(1, dt * 2.6)
    if (autoSpeed < 0.002) autoSpeed = 0
    controls.autoRotate = autoSpeed > 0
    controls.autoRotateSpeed = autoSpeed
    if (flight) stepFlight(now)

    if (emphasisCurrent && emphasisGoal && starPoints) {
      const attribute = starPoints.geometry.getAttribute('aEmphasis')
      const array = attribute.array
      const k = Math.min(1, dt * 9)
      let dirty = false
      for (let i = 0; i < array.length; i += 1) {
        const diff = emphasisGoal[i] - emphasisCurrent[i]
        if (Math.abs(diff) > 0.002) {
          emphasisCurrent[i] += diff * k
          array[i] = emphasisCurrent[i]
          dirty = true
        } else if (array[i] !== emphasisGoal[i]) {
          emphasisCurrent[i] = emphasisGoal[i]
          array[i] = emphasisGoal[i]
          dirty = true
        }
      }
      if (dirty) attribute.needsUpdate = true
    }
    if (rings && !reducedMotion) rings.rotation.y = animationTime * 0.012
    if (root) root.rotation.y = Math.sin(animationTime * 0.03) * 0.02
    controls.update(dt)
    cosmos.update(camera, dt, renderer.getPixelRatio(), reducedMotion)
    const focus = camera.position.distanceTo(controls.target)
    starUniforms.uFocus.value = focus
    const vw = renderer.domElement.clientWidth
    const vh = renderer.domElement.clientHeight
    const boxes = []
    const projected = tmpVec2
    const next = []
    const visibleLabels = labelsVisible ? (labelLimit > 0 ? labels.slice(0, labelLimit) : labels) : []
    for (const label of visibleLabels) {
      projected.copy(label.position).project(camera)
      if (projected.z > 1) continue
      const x = (projected.x * 0.5 + 0.5) * vw
      const y = (-projected.y * 0.5 + 0.5) * vh
      if (y < -20 || y > vh + 20) continue
      // 屏幕空间的粗略包围盒（标签是像素尺寸，不随相机缩放），压住时让分片更多的文档留下。
      const wpx = 26 + String(label.userData.title).length * 12
      const hpx = 20
      // 贴边时把标签整体推进可视区，而不是直接丢掉——移动端窄屏尤其需要。
      const half = wpx / 2 + 6
      if (x < -half || x > vw + half) continue
      const clampedX = Math.min(Math.max(x, half), vw - half)
      const clampedY = Math.min(Math.max(y, hpx + 4), vh - 6)
      const box = { x: clampedX - wpx / 2, y: clampedY - hpx, w: wpx, h: hpx }
      const collide = boxes.some(
        (other) =>
          box.x < other.x + other.w + 10 &&
          box.x + box.w + 10 > other.x &&
          box.y < other.y + other.h + 10 &&
          box.y + box.h + 10 > other.y,
      )
      if (collide) continue
      boxes.push(box)
      next.push({
        md5: label.userData.fileMd5,
        title: label.userData.title,
        count: label.userData.count,
        weight: label.userData.weight ?? 0.5,
        x: clampedX,
        y: clampedY,
      })
    }
    if (labelsVisible && now - lastLabelPush > 120) {
      lastLabelPush = now
      // 入场镜头还在远处时先不铺标签：星群缩成一小团，文字会挤在一起。
      const far = camera.position.distanceTo(controls.target) > fitDistanceRef * 1.18
      labelSink && labelSink(far ? [] : next)
    }
    frames += 1
    if (now - fpsWindowStart >= 500) {
      fps = Math.round((frames * 1000) / (now - fpsWindowStart))
      frames = 0
      fpsWindowStart = now
      // 自适应画质：像素比高了撑不住就逐级退让，帧率富余时再慢慢补回来。
      if (fps > 0 && fps < 52 && quality > 0.62) {
        quality = Math.max(0.62, quality - 0.12)
        renderer.setPixelRatio(baseRatio * quality)
        setSize()
      } else if (fps > 72 && quality < 1) {
        quality = Math.min(1, quality + 0.04)
        renderer.setPixelRatio(baseRatio * quality)
        setSize()
      }
    }
    renderer.render(scene, camera)
  }
  render()

  function dispose() {
    disposed = true
    cancelAnimationFrame(frameId)
    if (hoverFrame) cancelAnimationFrame(hoverFrame)
    clearTimeout(pointerIdleTimer)
    observer.disconnect()
    document.removeEventListener('visibilitychange', onVisibility)
    reducedQuery?.removeEventListener?.('change', onReducedMotionChange)
    controls.removeEventListener('start', onControlsStart)
    controls.removeEventListener('end', onControlsEnd)
    renderer.domElement.removeEventListener('pointermove', onPointerMove)
    renderer.domElement.removeEventListener('pointerleave', onPointerLeave)
    renderer.domElement.removeEventListener('pointerdown', onPointerDown)
    renderer.domElement.removeEventListener('pointerup', onPointerUp)
    controls.dispose()
    cosmos.dispose()
    meteors.dispose()
    scene.traverse((child) => {
      if (child.geometry) child.geometry.dispose()
      if (child.material) {
        const materials = Array.isArray(child.material) ? child.material : [child.material]
        materials.forEach((material) => {
          if (material.map) material.map.dispose()
          material.dispose()
        })
      }
    })
    ringTexture.dispose()
    renderer.dispose()
    if (renderer.domElement.parentNode === container) container.removeChild(renderer.domElement)
  }

  return {
    setData,
    setFilter,
    setSelected,
    setHovered,
    setShowSemanticEdges,
    setShowChains,
    focusPoint,
    focusDocument,
    resetView,
    resize: setSize,
    toScreen,
    setAutoRotate,
    setAutoPaused,
    setLabelsVisible,
    setLabelLimit,
    setImmersive(value) {
      immersive = Boolean(value)
      if (rings) rings.visible = !immersive
    },
    setReducedMotion(value) {
      reducedMotion = Boolean(value)
      meteors.reset()
      autoSpeed = 0
      controls.autoRotate = false
      lastFrameAt = performance.now()
    },
    toggleAutoRotate: () => setAutoRotate(!autoUserEnabled),
    isAutoRotating,
    saveCameraState,
    restoreCameraState,
    getPerf: () => ({ fps, autoSpeed, reducedMotion, autoUserEnabled, immersive, cosmos: cosmos.getState(), meteor: meteors.getState() }),
    getCamera: () => ({
      position: camera.position.toArray(),
      target: controls.target.toArray(),
      distance: camera.position.distanceTo(controls.target),
    }),
    getEmphasis: (id) => {
      if (!emphasisCurrent) return 0
      const slot = slotById.get(id)
      return slot === undefined ? 0 : emphasisCurrent[slot]
    },
    getFlight: () =>
      flight
        ? {
            progress: Math.min(1, (performance.now() - flight.startedAt) / flight.duration),
            duration: flight.duration,
            endTarget: flight.endTarget.toArray(),
          }
        : null,
    dispose,
    get ready() {
      return hasData
    },
  }
}
