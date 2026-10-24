<script setup>
import { useUiStore } from '../../stores/ui'
import Icon from './Icon.vue'

const ui = useUiStore()

const LABEL = { info: '提示', ok: '完成', warn: '注意', err: '错误' }
</script>

<template>
  <Teleport to="body">
    <div class="toast-stack" role="status" aria-live="polite">
      <TransitionGroup name="toast">
        <article v-for="toast in ui.toasts" :key="toast.id" class="toast" :data-kind="toast.kind">
          <div class="toast-mark">
            <span class="mark-label mono">{{ LABEL[toast.kind] || '提示' }}</span>
            <p class="toast-text">{{ toast.text }}</p>
          </div>
          <div class="toast-actions">
            <button
              v-if="toast.action"
              type="button"
              class="toast-action mono"
              @click="toast.action.run?.(); ui.dismissToast(toast.id)"
            >
              {{ toast.action.label }}
            </button>
            <button type="button" class="icon-btn icon-btn--sm" aria-label="关闭提示" @click="ui.dismissToast(toast.id)">
              <Icon name="close" :size="13" />
            </button>
          </div>
        </article>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-stack {
  position: fixed;
  left: calc(var(--rail-w) + 22px);
  bottom: 26px;
  z-index: var(--z-toast);
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: min(400px, calc(100vw - var(--rail-w) - 44px));
  pointer-events: none;
}

.toast {
  pointer-events: auto;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 12px 12px 14px;
  border: 1px solid var(--line-strong);
  border-left: 2px solid var(--ink-3);
  border-radius: var(--r-sm);
  background: var(--surface);
  box-shadow: var(--shadow-float);
}

.toast[data-kind='ok'] {
  border-left-color: var(--ok);
}

.toast[data-kind='warn'] {
  border-left-color: var(--warn);
}

.toast[data-kind='err'] {
  border-left-color: var(--err);
}

.toast[data-kind='info'] {
  border-left-color: var(--accent);
}

.toast-mark {
  flex: 1;
  min-width: 0;
}

.mark-label {
  font-size: var(--text-2xs);
  letter-spacing: 0.2em;
  color: var(--ink-3);
}

.toast-text {
  margin-top: 3px;
  font-size: var(--text-sm);
  line-height: 1.6;
  color: var(--ink);
  word-break: break-word;
}

.toast-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  padding-top: 2px;
}

.toast-action {
  font-size: var(--text-2xs);
  letter-spacing: 0.08em;
  color: var(--accent);
  padding: 4px 6px;
  border-radius: var(--r-xs);
}

.toast-action:hover {
  background: var(--accent-soft);
}

.toast-enter-active,
.toast-leave-active,
.toast-move {
  transition: opacity var(--t-base) var(--ease-out), transform var(--t-base) var(--ease-out);
}

.toast-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

.toast-leave-to {
  opacity: 0;
  transform: translateX(-12px);
}

.toast-leave-active {
  position: absolute;
}

@media (max-width: 900px) {
  .toast-stack {
    left: 14px;
    right: 14px;
    bottom: 76px;
    width: auto;
  }
}
</style>
