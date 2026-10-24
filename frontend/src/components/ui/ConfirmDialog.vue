<script setup>
import { nextTick, ref, watch } from 'vue'
import { settle, useConfirm } from '../../composables/confirm'

const { state } = useConfirm()
const primary = ref(null)

watch(
  () => state.open,
  async (open) => {
    if (!open) return
    await nextTick()
    primary.value?.focus()
  },
)

function onKeydown(event) {
  if (event.key === 'Escape') {
    event.stopPropagation()
    settle(false)
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="state.open" class="confirm-layer" @click.self="settle(false)" @keydown="onKeydown">
        <div class="confirm" role="alertdialog" aria-modal="true" :aria-label="state.title">
          <p class="eyebrow">需要确认</p>
          <h2>{{ state.title }}</h2>
          <p v-if="state.body" class="confirm-body">{{ state.body }}</p>
          <p v-if="state.detail" class="confirm-detail mono">{{ state.detail }}</p>
          <div class="confirm-actions">
            <button type="button" class="btn" @click="settle(false)">{{ state.cancelText }}</button>
            <button
              ref="primary"
              type="button"
              class="btn"
              :class="state.danger ? 'btn--danger' : 'btn--solid'"
              @click="settle(true)"
            >
              {{ state.confirmText }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.confirm-layer {
  position: fixed;
  inset: 0;
  z-index: var(--z-confirm);
  display: grid;
  place-items: center;
  padding: 20px;
  background: color-mix(in srgb, var(--bg-deep) 70%, transparent);
  backdrop-filter: blur(4px);
}

.confirm {
  width: min(420px, 100%);
  border: 1px solid var(--line-strong);
  border-radius: var(--r-md);
  background: var(--surface);
  padding: 24px 26px 20px;
  box-shadow: var(--shadow-sheet);
}

.confirm h2 {
  margin-top: 8px;
  font-family: var(--font-serif);
  font-size: var(--text-xl);
  font-weight: 500;
  letter-spacing: 0.03em;
}

.confirm-body {
  margin-top: 10px;
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--ink-2);
}

.confirm-detail {
  margin-top: 8px;
  font-size: var(--text-2xs);
  color: var(--ink-3);
  word-break: break-all;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 22px;
}
</style>
