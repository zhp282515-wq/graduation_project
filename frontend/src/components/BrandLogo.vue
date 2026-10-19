<script setup>
/**
 * 从同一份校徽 SVG 中裁出两块，只加载一份 135KB 源文件：
 *   徽标圆章  viewBox 204 81 388 388
 *   书法校名  viewBox 63 509 692 101
 */
import { computed } from 'vue'
import logoUrl from '../assets/logo.svg'

const props = defineProps({
  part: { type: String, default: 'emblem' }, // 'emblem' | 'name'
  height: { type: Number, default: 54 },
  /** 任何合法 CSS 颜色，默认白色 */
  color: { type: String, default: '#fff' },
})

// 源图 794×659 坐标系下的裁剪框
const CROPS = {
  emblem: { x: 204, y: 81, w: 388, h: 388 },
  name: { x: 63, y: 509, w: 692, h: 101 },
}

const crop = computed(() => CROPS[props.part] ?? CROPS.emblem)
const scale = computed(() => props.height / crop.value.h)
const width = computed(() => crop.value.w * scale.value)

// 源 SVG 是单色路径，用 mask 把填充色换成任意颜色
const style = computed(() => ({
  width: `${width.value}px`,
  height: `${props.height}px`,
  backgroundColor: props.color,
  maskImage: `url(${logoUrl})`,
  WebkitMaskImage: `url(${logoUrl})`,
  maskSize: `${794 * scale.value}px ${659 * scale.value}px`,
  WebkitMaskSize: `${794 * scale.value}px ${659 * scale.value}px`,
  maskPosition: `${-crop.value.x * scale.value}px ${-crop.value.y * scale.value}px`,
  WebkitMaskPosition: `${-crop.value.x * scale.value}px ${-crop.value.y * scale.value}px`,
  maskRepeat: 'no-repeat',
  WebkitMaskRepeat: 'no-repeat',
}))
</script>

<template>
  <div class="logo-crop" :style="style" role="img" aria-label="江西师范大学" />
</template>

<style scoped>
.logo-crop {
  flex: none;
  /* 白色校徽压在浅色云层上，加一层淡阴影把轮廓分离出来 */
  filter: drop-shadow(0 1px 2px rgba(30, 70, 130, 0.35));
}
</style>
