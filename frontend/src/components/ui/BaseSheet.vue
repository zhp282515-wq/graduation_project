<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import Icon from './Icon.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '' },
  subtitle: { type: String, default: '' },
  eyebrow: { type: String, default: '' },
  width: { type: Number, default: 520 },
  closeOnScrim: { type: Boolean, default: true },
})

const emit = defineEmits(['update:open', 'close'])

const panel = ref(null)
let lastFocused = null

const styleVars = computed(() => ({ '--sheet-w': `${props.width}px` }))

function close() {
  emit('update:open', false)
  emit('close')
}

function onKeydown(event) {
  if (!props.open) return
  if (event.key === 'Escape') {
    event.stopPropagation()
    close()
    return
  }
  if (event.key !== 'Tab' || !panel.value) return
  const focusables = panel.value.querySelectorAll(
    'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
  )
  if (!focusables.length) {
    event.preventDefault()
    panel.value.focus()
    return
  }
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}

function teardown() {
  document.removeEventListener('keydown', onKeydown, true)
  if (lastFocused && typeof lastFocused.focus === 'function') {
    lastFocused.focus({ preventScroll: true })
  }
  lastFocused = null
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      lastFocused = document.activeElement
      document.addEventListener('keydown', onKeydown, true)
      await nextTick()
      panel.value?.focus()
    } else {
      teardown()
    }
  },
)

onBeforeUnmount(teardown)

defineExpose({ close })
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="open" class="scrim" @click="closeOnScrim && close()" />
    </Transition>
    <Transition name="sheet">
      <aside
        v-if="open"
        ref="panel"
        class="sheet"
        :style="styleVars"
        role="dialog"
        aria-modal="true"
        :aria-label="title || '详情'"
        tabindex="-1"
      >
        <header class="sheet-head">
          <div class="head-copy">
            <p v-if="eyebrow" class="eyebrow">{{ eyebrow }}</p>
            <h2 v-if="title">{{ title }}</h2>
            <p v-if="subtitle" class="subtitle">{{ subtitle }}</p>
            <slot name="head" />
          </div>
          <button class="icon-btn" type="button" aria-label="关闭" @click="close">
            <Icon name="close" :size="16" />
          </button>
        </header>
        <div class="sheet-body">
          <slot />
        </div>
        <footer v-if="$slots.foot" class="sheet-foot">
          <slot name="foot" />
        </footer>
      </aside>
    </Transition>
  </Teleport>
</template>

<style scoped>
.sheet {
  width: min(var(--sheet-w, 520px), 100vw);
}

.sheet-head h2 {
  font-family: var(--font-serif);
  font-size: var(--text-xl);
  font-weight: 500;
  letter-spacing: 0.03em;
  line-height: 1.3;
  margin-top: 6px;
}

.head-copy {
  min-width: 0;
}

.subtitle {
  margin-top: 6px;
  font-size: var(--text-sm);
  color: var(--ink-3);
}

.sheet-foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 26px;
  border-top: 1px solid var(--line);
  background: var(--surface-2);
}
</style>
