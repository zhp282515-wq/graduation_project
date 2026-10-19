<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useMultiGlass } from '../glass/useMultiGlass'
import bgUrl from '../assets/bg.jpg'

const canvasRef = ref(null)
const panels = ref([])

let ro = null
let raf = 0

function measure() {
  panels.value = Array.from(document.querySelectorAll('[data-glass]')).map((el) => {
    const r = el.getBoundingClientRect()
    return {
      x: r.left + r.width / 2,
      y: r.top + r.height / 2,
      w: r.width / 2,
      h: r.height / 2,
      radius: parseFloat(getComputedStyle(el).borderRadius) || 24,
    }
  })
}

function schedule() {
  cancelAnimationFrame(raf)
  raf = requestAnimationFrame(measure)
}

onMounted(async () => {
  await nextTick()
  measure()
  ro = new ResizeObserver(schedule)
  document.querySelectorAll('[data-glass]').forEach((el) => ro.observe(el))
  window.addEventListener('resize', schedule)
})

onBeforeUnmount(() => {
  ro?.disconnect()
  cancelAnimationFrame(raf)
  window.removeEventListener('resize', schedule)
})

useMultiGlass({
  canvas: canvasRef,
  panels,
  backgroundUrl: bgUrl,
  saturation: 1.35,
  blur: 0.2,
  frost: 0.1,
  distortion: 1,
  shadowIntensity: 0.3,
  shadowBlur: 28,
  chromaticAberration: 0.3,
})
</script>

<template>
  <canvas ref="canvasRef" class="glass-layer" />
</template>

<style scoped>
.glass-layer {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
  z-index: 0;
  pointer-events: none;
}
</style>
