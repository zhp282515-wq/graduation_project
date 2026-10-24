<script setup>
import { computed } from 'vue'
import { formatClock } from '../../utils/format'
import AnswerBlock from './AnswerBlock.vue'
import Icon from '../ui/Icon.vue'

const props = defineProps({
  turn: { type: Object, required: true },
  index: { type: Number, default: 1 },
  isCurrent: { type: Boolean, default: false },
  run: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['regenerate', 'open-source', 'open-sources', 'refill'])

const pad = computed(() => String(props.index).padStart(2, '0'))
const time = computed(() => formatClock(props.turn.createdAt))
const live = computed(() => props.isCurrent)

const reasoning = computed(() => (props.isCurrent ? props.run.reasoning || '' : ''))
const steps = computed(() => (props.isCurrent ? props.run.steps || [] : []))
const phase = computed(() => (props.isCurrent ? props.run.phase : ''))
const error = computed(() => (props.isCurrent ? props.run.error : ''))
const finishReason = computed(() => (props.isCurrent ? props.run.finishReason : ''))
const elapsedMs = computed(() => (props.isCurrent ? props.run.elapsedMs : 0))
</script>

<template>
  <section class="turn" :data-live="live">
    <div class="turn-gutter">
      <span class="gutter-no mono">问 {{ pad }}</span>
      <span v-if="time" class="gutter-time mono">{{ time }}</span>
      <span v-if="live && run.active" class="gutter-live mono">进行中</span>
    </div>

    <div class="turn-col">
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
          :elapsed-ms="elapsedMs"
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
    </div>
  </section>
</template>

<style scoped>
.turn {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 26px;
  padding: 30px 0 34px;
  border-top: 1px solid var(--line);
}

.turn:first-child {
  border-top: 0;
  padding-top: 8px;
}

.turn-gutter {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 5px;
  padding-top: 3px;
  text-align: right;
}

.gutter-no {
  font-size: var(--text-2xs);
  letter-spacing: 0.16em;
  color: var(--ink-3);
}

.gutter-time {
  font-size: var(--text-2xs);
  color: var(--ink-4);
  letter-spacing: 0.04em;
}

.gutter-live {
  margin-top: 3px;
  font-size: 9px;
  letter-spacing: 0.16em;
  color: var(--accent);
}

.turn-col {
  min-width: 0;
  max-width: var(--reading-w);
}

.question {
  position: relative;
  padding: 2px 0 6px 18px;
  border-left: 2px solid var(--ink);
}

.question::before {
  content: "";
  position: absolute;
  left: -2px;
  top: 0;
  width: 2px;
  height: 14px;
  background: var(--accent);
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
  font-size: var(--text-2xs);
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
    grid-template-columns: minmax(0, 1fr);
    gap: 0;
    padding: 26px 0 30px;
  }

  .turn-gutter {
    flex-direction: row;
    align-items: baseline;
    gap: 10px;
    padding-bottom: 10px;
  }

  .turn-col {
    max-width: 100%;
  }

  .gutter-live {
    margin-top: 0;
  }
}
</style>
