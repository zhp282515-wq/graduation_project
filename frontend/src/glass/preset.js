/**
 * 液态玻璃预设 —— 取自 liquid-glass-js 的 myconfig
 * ---------------------------------------------------------------------------
 * 原库用 WebGL 着色器实现，参数语义如下（container.js）：
 *
 *   distFromEdge   = 到形状边缘的距离 / min(w, h)        归一化 0..0.5
 *   normalizedDist = distFromEdge * min(w, h)            换算回像素
 *
 *   edgeIntensity  = exp(-normalizedDist * edgeDistance)
 *   rimIntensity   = exp(-normalizedDist * rimDistance)
 *   baseIntensity  = 1 - exp(-normalizedDist * baseDistance)   // 仅 warp 开启时生效
 *   totalIntensity = base*warp?  + edge*edgeIntensity + rim*rimIntensity
 *   tint           = mix(背景色, 白→灰渐变, tintOpacity)
 *
 * 也就是说：rim 与 edge 都是「从边缘往内按指数衰减」的亮度带，
 * 衰减到 5% 的宽度 = ln20 / k ≈ 2.996 / k。
 *
 * 这一个对象有两处消费方，保证只有一组真值：
 *   1. liquidGlass.js —— 面板本体，逐行照搬原库着色器，参数直接进 uniform。
 *   2. App.vue 的 CSS —— 面板内的小控件（按钮/输入框/页签）和
 *      「WebGL 不可用」时的兜底，把同一组参数换算成 CSS 变量：
 *        blurRadius  → --lg-blur       backdrop-filter 的模糊半径
 *        （染色）     → --lg-tint       控件的白色填充刻度，见下方 CSS_TINT
 *        rimIntensity→ --lg-rim        贴边亮环 / 轮缘透镜的强度
 *        edgeIntensity→ --lg-edge      内侧宽带光晕的强度
 *        rim/edgeDistance → --lg-rim-band / --lg-edge-band   两条带的像素宽度
 *        cornerBoost → --lg-corner     四角微光
 *        rippleEffect→ --lg-ripple     指针跟随光泽的幅度
 *
 * 想改风格只改下面这个对象即可，整个界面的玻璃会一起变。
 */

/**
 * myconfig 预设（与 liquid-glass-js 的参数一一对应）。
 *
 * 三个值被重新设定，原因都写在这里：
 *   blurRadius  1   → 2     σ=1.0、核半径 ±3px。网线只被「柔化」不被「摊开」：
 *                           再往上（3~5）1px 的亮线会摊成十几像素的柔光带，
 *                           看起来像污渍而不是玻璃。
 *   tintOpacity 0.1 → 0.55  原库那 10% 的白是为浅色照片背景调的；这里的背景是
 *                           深色界面上的白色粒子网，往白染只会把网洗成灰雾，
 *                           对比度仍保留（0.2..1）所以「还是看得见形状」，最乱。
 *                           改成往深色染 ⇒ 面板压暗、网线退成底纹、出现明度台阶。
 *   tintColor   （新增）   染色目标色。原库硬编码白→灰；这里默认取页面底色一侧的
 *                           深蓝黑，让玻璃带一点冷调，和界面文字色统一。
 * 其余参数与 myconfig 逐字一致：rim 主导、edge 极弱、warp 关闭、
 * 轮缘带宽 2.996/0.8 ≈ 3.75px —— 也就是「薄、清澈、靠边缘透镜感定形」。
 */
export const LIQUID_GLASS_PRESET = {
  edgeIntensity: 0.01,
  rimIntensity: 0.05,
  baseIntensity: 0.01,
  edgeDistance: 0.15,
  rimDistance: 0.8,
  baseDistance: 0.1,
  cornerBoost: 0.02,
  rippleEffect: 0.1,
  blurRadius: 2,
  tintOpacity: 0.55,
  tintColor: '#0a1526',
  warp: false,
  hideButtons: false,
}

/** exp(-x) 降到 5% 时的 x，即 ln20 */
const FALLOFF_05 = Math.log(20)

/**
 * CSS 侧的染色刻度（面板内小控件 + 无 WebGL 时的兜底）。
 * 它是「按 tintOpacity=0.1 时的观感标定」的独立常量，不与着色器的 tintOpacity
 * 联动：App.vue 里 100 多处 `calc(var(--lg-tint) * N)` 的 N 都是照这个刻度调的，
 * 改预设的 tintOpacity 时不应该把那些控件一起冲亮或冲暗。
 */
const CSS_TINT = 0.1

/** 指数衰减带的像素宽度：exp(-w * k) = 0.05 */
function bandWidth(k) {
  return FALLOFF_05 / Math.max(k, 1e-6)
}

/**
 * 把预设写进 :root 的 CSS 变量。
 * App.vue 的样式表里有一份等值的兜底声明，即使这里没跑也不会崩。
 */
export function applyPreset(preset = LIQUID_GLASS_PRESET, root = document.documentElement) {
  const p = { ...LIQUID_GLASS_PRESET, ...preset }
  const set = (name, value) => root.style.setProperty(name, value)

  set('--lg-blur', `${p.blurRadius}px`)
  set('--lg-tint', String(CSS_TINT))
  set('--lg-rim', String(p.rimIntensity))
  set('--lg-edge', String(p.edgeIntensity))
  // warp 关闭时基底层完全不参与，和着色器里的 baseComponent 判断一致
  set('--lg-base', String(p.warp ? p.baseIntensity : 0))
  set('--lg-corner', String(p.cornerBoost))
  set('--lg-ripple', String(p.rippleEffect))
  set('--lg-rim-band', `${bandWidth(p.rimDistance).toFixed(2)}px`)
  set('--lg-edge-band', `${bandWidth(p.edgeDistance).toFixed(2)}px`)
  set('--lg-base-band', `${bandWidth(p.baseDistance).toFixed(2)}px`)

  return p
}

export default LIQUID_GLASS_PRESET
