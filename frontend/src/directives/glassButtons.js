/**
 * v-liquid-buttons —— 把「交互按钮」交给液态玻璃层。
 *
 * 和原库（liquid-glass-js）对按钮的做法完全一致：按钮自己不画背景，玻璃是
 * 算出来的一层像素——折射 → 三层染色 → 上缘镜面 → 外缘细环，用的是原库
 * `Button` 的那套片元着色器（见 glass/liquidGlass.js 的 BUTTON_FRAG_SOURCE），
 * 参数取 myconfig 预设。面板本身仍然是 CSS 玻璃（截图那一版），
 * 所以整个页面只有按钮带液态玻璃。
 *
 * 两种用法：
 *   <aside class="sidebar panel" v-liquid-buttons>     面板模式：接管面板里所有按钮
 *   <button class="restore-tab glass-btn" v-liquid-buttons.self>  自渲染：只管自己
 * （restore 药丸在面板之外，没有面板可依附，只能在元素内部自己插一张 canvas）
 *
 * 指令做三件事：
 *   1. 插一张 .glass-btn-layer canvas（z-index:-1，落在「面板/按钮背景之上、
 *      内容之下」，面板内的子元素不用改 z-index）；
 *   2. 把 .glass-btn / .hide-btn 逐个 attach 给玻璃层；
 *   3. 定期对齐一次，处理 v-if 新增/移除的按钮和 .active 这类 class 变化。
 */
import { LiquidGlassLayer } from '../glass/liquidGlass'
import { LIQUID_GLASS_PRESET } from '../glass/preset'

/**
 * 按钮玻璃的参数 = myconfig 逐字，加一个中性的白色染色目标。
 *
 * myconfig（用户预设）: edgeIntensity .01 / rimIntensity .05 / baseIntensity .01 /
 * edgeDistance .15 / rimDistance .8 / baseDistance .1 / cornerBoost .02 /
 * rippleEffect .1 / blurRadius 3 / tintOpacity .1 / warp false
 *
 * preset.js 里的 LIQUID_GLASS_PRESET 有三处是为「整块面板」改的刻度，
 * 按钮不能跟着走，所以这里显式改回来：
 *   blurRadius  2 → 3   面板面积大、省片元；按钮小，用 myconfig 原值。
 *   tintOpacity .55 → .1  .55 + #0a1526 是把面板压成深色玻璃；
 *                        按钮要浮在面板之上，按那个刻度染深会糊成一块脏斑。
 *   tintColor   #0a1526 → #ffffff  原库按钮写死「白→灰」，纯白即等价。
 */
const BUTTON_PARAMS = {
  ...LIQUID_GLASS_PRESET,
  blurRadius: 3,
  tintOpacity: 0.1,
  tintColor: '#ffffff',
}

/**
 * 容器里哪些元素算「交互按钮」。
 * 「所有交互按钮」= 主按钮 + 图标按钮 + 列表项 + 对话框按钮；纯输入框
 * （.composer / .search-box / .text-input）、整块遮罩、图片缩略图本身不算。
 *   .glass-btn  主按钮 / 列表项（.tab .new-session .session-item .suggest-item
 *               .quick-item .flow-item .attach .send）
 *   .hide-btn   面板折叠的圆形箭头
 *   .search-clear  搜索框里的 ×
 *   .confirm-btn   二次确认弹窗的「取消 / 确认」
 *
 * 有两个小按钮故意留在这里面不接管，改用 CSS 玻璃 —— 玻璃只采得到粒子层，
 * 采不到「它下面的 CSS 绘制内容」，硬接管会在这块pixel上挖出一个比周围暗的洞：
 *   .session-del  正下方是 .session-item 的悬停高光（.glass-btn::before 的指针
 *                 radial，mix-blend screen），那是一块动态的高亮，近似不了，
 *                 接管后按钮四角会露出父级玻璃、看起来像色差；
 *   .preview-del  正下方是用户上传的照片，颜色完全不可预知。
 * 这两个只有 20~24px，交给 backdrop-filter 反而更准。
 */
const BUTTON_SELECTOR = '.glass-btn, .hide-btn, .search-clear, .confirm-btn'

/** 元素增删 / class 变化的对齐周期（ms） */
const SYNC_INTERVAL = 400

/** 背景帧来源：粒子层（WebGL canvas，透明底） */
const backgroundSource = () => document.querySelector('.app-bg canvas')

/**
 * @typedef {object} LayerState
 * @property {Element} el
 * @property {HTMLCanvasElement} canvas
 * @property {LiquidGlassLayer} layer
 * @property {Map<Element, object>} surfaces
 * @property {number} timer
 * @property {boolean} dead
 * @property {boolean} self
 */

/** @type {WeakMap<Element, LayerState>} */
const states = new WeakMap()

/**
 * 把面板 DOM 现状对齐到玻璃层的 surface 列表。
 * 按钮是 v-for 出来的，更新是异步的，所以这里宁可多跑几次也不漏。
 * @param {LayerState} state
 */
function sync(state) {
  if (!state || state.dead || state.self) return
  const { el, layer, surfaces } = state

  const nodes = Array.from(el.querySelectorAll(BUTTON_SELECTOR))
  const alive = new Set(nodes)

  for (const [element, surface] of surfaces) {
    if (!alive.has(element) || !element.isConnected) {
      layer.detach(element)
      surfaces.delete(element)
      // 元素要被丢弃时，顺手把它的标记摘掉，避免复用时残留
      if (surface && surface.element === element) delete element.dataset.liquid
    }
  }

  for (const element of nodes) {
    const surface = surfaces.get(element)
    if (surface) {
      // .active / :disabled 之类会改染色刻度，class 变了才重读一次
      // （每 400ms 对每个按钮踩一遍 getComputedStyle 太浪费）
      const key = element.className
      if (surface.classKey !== key) {
        surface.classKey = key
        layer.refresh(surface)
      }
    } else {
      const created = layer.attach(element)
      if (created) {
        created.classKey = element.className
        surfaces.set(element, created)
      }
    }
  }
}

/**
 * @param {Element} el
 * @param {boolean} self
 */
function mount(el, self) {
  if (!el || states.has(el)) return

  const canvas = document.createElement('canvas')
  canvas.className = self ? 'glass-btn-layer glass-btn-layer--self' : 'glass-btn-layer'
  canvas.setAttribute('aria-hidden', 'true')
  el.prepend(canvas)

  const layer = new LiquidGlassLayer({
    canvas,
    // 背景帧 = 粒子层。按钮玻璃折射的是粒子网，面板的 CSS 底色由 panelBackdrop() 合成
    source: backgroundSource,
    params: BUTTON_PARAMS,
    // 走原库 button.js 那套片元着色器（σ=blur/3、波纹 30、三层染色）
    shader: 'button',
    // 按钮面积小，1.5 倍已经够细，再高就只是白烧片元（每片元最多 49 次采样）
    pixelRatio: Math.min(window.devicePixelRatio || 1, 1.5),
    fps: 30,
  })

  /** @type {LayerState} */
  const state = { el, canvas, layer, surfaces: new Map(), timer: 0, dead: false, self }
  states.set(el, state)

  if (self) {
    const surface = layer.attach(el)
    if (surface) {
      surface.classKey = el.className
      state.surfaces.set(el, surface)
    }
    layer.start()
    return
  }

  sync(state)
  layer.start()
  state.timer = window.setInterval(() => {
    try {
      sync(state)
    } catch (error) {
      console.warn('[liquid-buttons] 按钮对齐失败', error)
    }
  }, SYNC_INTERVAL)
}

/** @param {Element} el */
function unmount(el) {
  const state = states.get(el)
  if (!state) return

  state.dead = true
  if (state.timer) window.clearInterval(state.timer)
  state.timer = 0
  state.surfaces.clear()
  state.layer.destroy()
  state.canvas.remove()
  states.delete(el)
}

export const liquidButtons = {
  mounted(el, binding) {
    // 这一层是"锦上添花"：玻璃起不来（无 WebGL、着色器编译失败、浏览器太老）
    // 也只能退回 CSS 玻璃，绝不能让指令抛错把整块面板的挂载带崩。
    try {
      mount(el, Boolean(binding && binding.modifiers && binding.modifiers.self))
    } catch (error) {
      console.warn('[liquid-buttons] 玻璃层初始化失败，退回 CSS 玻璃', error)
    }
  },
  unmounted(el) {
    try {
      unmount(el)
    } catch (error) {
      console.warn('[liquid-buttons] 玻璃层回收失败', error)
    }
  },
}

export default liquidButtons
