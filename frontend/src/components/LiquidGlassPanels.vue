<template>
  <canvas ref="canvasRef" class="liquid-glass-layer" aria-hidden="true"></canvas>
</template>

<script setup>
/**
 * 把页面里所有 .panel 交给 WebGL 液态玻璃层。
 * 玻璃本身画在整屏 canvas 上（每块面板一个 viewport），
 * 面板元素只留内容，背景由 data-liquid 对应的 CSS 关掉。
 *
 * ⚠️ 当前未挂载：面板已经回到截图那一版的 CSS 玻璃，液态玻璃只落在
 * 交互按钮上（见 directives/glassButtons.js）。留着这份代码是因为
 * LiquidGlassLayer 仍支持「一块 canvas 多个 viewport」的整屏用法，
 * 想再试面板玻璃时把它挂回 App.vue 的 .ui 里即可（样式随组件自带）。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { LiquidGlassLayer } from '../glass/liquidGlass'

const props = defineProps({
  /** 要接管的面板选择器 */
  selector: { type: String, default: '.panel' },
  /** 重绘上限，粒子背景在动，30fps 足够顺滑 */
  fps: { type: Number, default: 30 },
})

const canvasRef = ref(null)
let layer = null
let syncTimer = 0

function sync() {
  if (!layer) return
  const nodes = Array.from(document.querySelectorAll(props.selector))
  const alive = new Set(nodes)

  for (const surface of Array.from(layer.surfaces)) {
    if (!alive.has(surface.element) || !surface.element.isConnected) {
      layer.detach(surface.element)
    }
  }

  const attached = new Set(Array.from(layer.surfaces, (s) => s.element))
  for (const element of nodes) {
    if (!attached.has(element)) layer.attach(element)
  }
}

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return

  layer = new LiquidGlassLayer({
    canvas,
    source: () => document.querySelector('.app-bg canvas'),
    fps: props.fps,
    // 与原库一致：按 CSS 像素渲染（原版 canvas 的 width/height 就是元素尺寸，
    // 不乘 devicePixelRatio）。玻璃本来就负责柔化背景，1 倍足够；
    // 而片元数是这块唯一的性能瓶颈（每片元最多 21 次纹理采样）。
    pixelRatio: 1,
  })

  sync()
  layer.start()

  // 右栏两张卡片是 v-if 控制的，面板可能被销毁重建，定期重新对齐
  syncTimer = window.setInterval(sync, 1000)
})

onBeforeUnmount(() => {
  if (syncTimer) window.clearInterval(syncTimer)
  syncTimer = 0
  if (layer) layer.destroy()
  layer = null
})
</script>

<style>
/* 整屏玻璃层：canvas 是替换元素，fixed + inset:0 不会自动撑满，必须写尺寸 */
.liquid-glass-layer {
  position: fixed;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  z-index: 0;
  pointer-events: none;
}
</style>
