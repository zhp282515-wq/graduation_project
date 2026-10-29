<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { setTyped, settle, useConfirm } from '../../composables/confirm'

const { state } = useConfirm()
const primary = ref(null)
const typedInput = ref(null)

const needsTyping = computed(() => Boolean(state.requireText))
const typingOk = computed(() => !needsTyping.value || state.typed.trim() === state.requireText)

watch(
  () => state.open,
  async (open) => {
    if (!open) return
    await nextTick()
    if (needsTyping.value) typedInput.value?.focus()
    else primary.value?.focus()
  },
)

function onKeydown(event) {
  if (event.key === 'Escape') {
    event.stopPropagation()
    settle(false)
  }
}

function onTypedKeydown(event) {
  if (event.key !== 'Enter') return
  event.preventDefault()
  if (typingOk.value) settle(true)
}
</script>

<template>
  <Teleport to="body">
    <Transition name="pop">
      <div v-if="state.open" class="confirm-layer" @click.self="settle(false)" @keydown="onKeydown">
        <div class="confirm" role="alertdialog" aria-modal="true" :aria-label="state.title">
          <p class="eyebrow">需要确认</p>
          <h2>{{ state.title }}</h2>
          <p v-if="state.body" class="confirm-body">{{ state.body }}</p>
          <p v-if="state.detail" class="confirm-detail mono">{{ state.detail }}</p>
          <label v-if="needsTyping" class="confirm-typed">
            <span>输入 <b>{{ state.requireText }}</b> 以继续</span>
            <input
              ref="typedInput"
              :value="state.typed"
              type="text"
              autocomplete="off"
              spellcheck="false"
              aria-label="输入账号名以确认注销"
              @input="setTyped($event.target.value)"
              @keydown="onTypedKeydown"
            />
          </label>
          <div class="confirm-actions">
            <button type="button" class="btn" @click="settle(false)">{{ state.cancelText }}</button>
            <button
              ref="primary"
              type="button"
              class="btn"
              :class="state.danger ? 'btn--danger' : 'btn--solid'"
              :disabled="!typingOk"
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
  background: var(--scrim);
  backdrop-filter: blur(5px) saturate(0.95);
  -webkit-backdrop-filter: blur(5px) saturate(0.95);
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

.confirm-typed {
  display: grid;
  gap: 8px;
  margin-top: 16px;
  font-size: var(--text-sm);
  color: var(--ink-2);
}

.confirm-typed b {
  font-weight: 500;
  color: var(--ink);
}

.confirm-typed input {
  width: 100%;
  padding: 9px 12px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-sm);
  background: var(--surface-2);
  font: inherit;
  color: var(--ink);
}

.confirm-typed input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: var(--focus-ring);
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 22px;
}
</style>
