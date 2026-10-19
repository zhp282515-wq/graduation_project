<script setup lang="ts">
import { ref, toRef } from 'vue'
import {
  useLiquidGlassShader,
  type BackgroundMedia,
  type ShaderUniforms,
} from './useLiquidGlassShader'

const props = defineProps<{
  backgroundMedia: BackgroundMedia
  uniforms: ShaderUniforms
  isTransitioning?: boolean
}>()

const emit = defineEmits<{ ready: [] }>()

const canvasRef = ref<HTMLCanvasElement | null>(null)

useLiquidGlassShader({
  canvas: canvasRef,
  uniforms: props.uniforms,
  background: toRef(props, 'backgroundMedia'),
  onReady: () => emit('ready'),
})
</script>

<template>
  <canvas ref="canvasRef" class="w-full h-full" style="width: 100%; height: 100%" />
</template>
