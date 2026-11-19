<script setup>
import { ref } from 'vue'
import { rateAnswer } from '../../api/feedback'
import { useAuthStore } from '../../stores/auth'
import { useUiStore } from '../../stores/ui'
import FeedbackForm from '../FeedbackForm.vue'
import BaseSheet from '../ui/BaseSheet.vue'
import Icon from '../ui/Icon.vue'

const props = defineProps({ answer: { type: Object, required: true } })
const ui = useUiStore()
const auth = useAuthStore()
const busy = ref(false)
const feedbackOpen = ref(false)

async function rate(vote) {
  if (busy.value) return
  const selected = props.answer
  busy.value = true
  try {
    const result = await rateAnswer(selected, selected.rating === vote ? null : vote)
    selected.rating = result.vote
    feedbackOpen.value = !auth.isAdmin && props.answer === selected && result.vote === 'dislike'
  } catch (error) {
    if (error.name !== 'AbortError') ui.notify(error.message || '评价未保存，请重试', 'err')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <button v-for="(label, vote) in { like: '点赞', dislike: '点踩' }" :key="vote" type="button"
    class="btn btn--quiet btn--sm rating" :class="vote" :aria-pressed="answer.rating === vote"
    :aria-label="label" :title="label" :disabled="busy" @click="rate(vote)">
    <Icon :name="vote" :size="15" />
  </button>
  <button v-if="!auth.isAdmin && answer.rating === 'dislike'" type="button" class="btn btn--quiet btn--sm" @click="feedbackOpen = true">补充反馈</button>
  <BaseSheet v-if="!auth.isAdmin" v-model:open="feedbackOpen" title="回答反馈" subtitle="点踩已保存，你可以补充原因或说明。">
    <FeedbackForm v-if="feedbackOpen" :answer="answer" />
  </BaseSheet>
</template>

<style scoped>
.rating { min-width: 30px; min-height: 30px; justify-content: center }
.rating[aria-pressed="true"] { background: var(--surface-2); color: var(--ok) }
.rating.dislike[aria-pressed="true"] { color: var(--err) }
</style>
