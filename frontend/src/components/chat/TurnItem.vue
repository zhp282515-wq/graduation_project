<script setup>
import { computed } from 'vue'
import AnswerBlock from './AnswerBlock.vue'
import Icon from '../ui/Icon.vue'

const props = defineProps({
  turn: { type: Object, required: true },
  index: { type: Number, default: 1 },
  isCurrent: { type: Boolean, default: false },
  run: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['regenerate', 'open-source', 'open-sources', 'refill'])

const live = computed(() => props.isCurrent && Boolean(props.run.active))
const details = computed(() => (props.isCurrent ? props.run : props.turn.trace) || {})
const reasoning = computed(() => details.value.reasoning || '')
const steps = computed(() => details.value.steps || [])
const phase = computed(() => details.value.phase || '')
const error = computed(() => details.value.error || '')
const finishReason = computed(() => details.value.finishReason || '')
</script>

<template>
  <section class="turn">
    <div v-if="turn.userText || turn.images?.length" class="question">
      <p v-if="turn.userText" class="q-text">{{ turn.userText }}</p>
      <div v-if="turn.images?.length" class="q-images">
        <a
          v-for="(image, imageIndex) in turn.images"
          :key="`${image}-${imageIndex}`"
          class="q-image"
          :href="image"
          target="_blank"
          rel="noopener noreferrer"
        >
          <img :src="image" alt="提问时附带的图片" loading="lazy" decoding="async" />
        </a>
      </div>
    </div>

    <div v-if="turn.assistant" class="response">
      <AnswerBlock
        :answer="turn.assistant"
        :live="live"
        :reasoning="reasoning"
        :steps="steps"
        :phase="phase"
        :error="error"
        :finish-reason="finishReason"
        :index="index"
        @regenerate="emit('regenerate', turn.key)"
        @refill="emit('refill', turn)"
        @open-source="emit('open-source', $event)"
        @open-sources="emit('open-sources', turn.assistant.sources)"
      />
    </div>
    <div v-else class="response awaiting">
      <p class="awaiting-text mono">
        <Icon name="sparkle" :size="12" />
        正在等待 Agent 的回应…
      </p>
      <span class="skeleton bar" />
      <span class="skeleton bar short" />
    </div>
  </section>
</template>

<style scoped>
.turn {
  padding: 30px 0 34px;
  border-top: 1px solid var(--line);
}

.turn:first-child {
  border-top: 0;
  padding-top: 8px;
}

.question {
  position: relative;
  padding: 14px 18px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface-2);
}

.question::before {
  content: none;
}

.q-text {
  font-family: var(--font-serif);
  font-size: var(--text-md);
  line-height: 1.75;
  letter-spacing: 0.015em;
  color: var(--ink);
  white-space: pre-wrap;
  word-break: break-word;
  text-wrap: pretty;
}

.q-images {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.q-image {
  display: block;
  width: 96px;
  height: 96px;
  border-radius: var(--r-sm);
  overflow: hidden;
  border: 1px solid var(--line);
  background: var(--surface-2);
  transition: transform var(--t-base) var(--ease-out), border-color var(--t-fast);
}

.q-image:hover {
  transform: translateY(-2px);
  border-color: var(--accent-line);
}

.q-image img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.response {
  margin-top: 18px;
}

.awaiting {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 4px;
}

.awaiting-text {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  letter-spacing: 0.14em;
  color: var(--ink-3);
}

.awaiting .bar {
  height: 10px;
  width: 86%;
  display: block;
}

.awaiting .bar.short {
  width: 58%;
}

@media (max-width: 1180px) {
  .turn {
    padding: 26px 0 30px;
  }
}
</style>
