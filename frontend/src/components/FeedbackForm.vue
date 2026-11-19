<script setup>
import { computed, ref } from 'vue'
import { dislikeReasons, feedbackCategories, submissionId } from '../api/feedback'
import { http } from '../api/http'

const props = defineProps({ answer: Object })
const emit = defineEmits(['sent'])
const category = ref(props.answer ? 'answer' : '')
const description = ref('')
const reason = ref('')
const images = ref([])
const saving = ref(false)
const error = ref('')
const receipt = ref(null)
const ready = computed(() => category.value && (description.value.trim() || reason.value))
let id = submissionId()

function chooseImages(event) {
  const files = Array.from(event.target.files)
  event.target.value = ''
  error.value = ''
  if (images.value.length + files.length > 3) {
    error.value = '每条反馈最多上传 3 张图片'
    return
  }
  if (files.some(file => file.size > 10 * 1024 * 1024 ||
      !['image/jpeg', 'image/png', 'image/gif', 'image/webp'].includes(file.type))) {
    error.value = '请选择 JPEG、PNG、GIF 或 WebP，单张不超过 10 MB'
    return
  }
  images.value = [...images.value, ...files]
}

async function submit() {
  if (!ready.value || saving.value) return
  saving.value = true
  error.value = ''
  const form = new FormData()
  form.set('submission_id', id)
  form.set('category', category.value)
  form.set('description', description.value)
  if (props.answer) {
    form.set('message_id', props.answer.id)
    form.set('revision', props.answer.revision)
    if (reason.value) form.set('reason', reason.value)
  }
  for (const file of images.value) form.append('attachments', file)
  try {
    receipt.value = (await http.post('/api/feedback', form)).id
    emit('sent', receipt.value)
  } catch (err) {
    error.value = err.message || '提交失败，请重试'
  } finally {
    saving.value = false
  }
}

function restart() {
  receipt.value = null
  category.value = ''
  description.value = ''
  images.value = []
  id = submissionId()
}
</script>

<template>
  <div v-if="receipt" class="receipt">
    <p role="status">反馈已提交，编号 #{{ receipt }}</p>
    <button v-if="!answer" type="button" class="btn" @click="restart">提交另一条反馈</button>
  </div>
  <form v-else class="feedback-form" @submit.prevent="submit">
    <label>类别
      <select v-model="category" required :disabled="saving">
        <option value="" disabled>请选择类别</option>
        <option v-for="(label, key) in feedbackCategories" :key="key" :value="key">{{ label }}</option>
      </select>
    </label>
    <label v-if="answer">点踩原因（选填）
      <select v-model="reason" :disabled="saving">
        <option value="">请选择原因</option>
        <option v-for="(label, key) in dislikeReasons" :key="key" :value="key">{{ label }}</option>
      </select>
    </label>
    <label>说明{{ reason ? '（选填）' : '' }}
      <textarea v-model="description" rows="5" maxlength="2000" :required="!reason" :disabled="saving"
        placeholder="请描述你遇到的问题或建议" />
    </label>
    <label>图片（选填）
      <input type="file" accept="image/jpeg,image/png,image/gif,image/webp" multiple
        :disabled="saving || images.length >= 3" @change="chooseImages" />
    </label>
    <small>最多 3 张，每张不超过 10 MB。</small>
    <ul v-if="images.length" class="image-list">
      <li v-for="(file, index) in images" :key="index">
        <span>{{ file.name }}</span>
        <button type="button" class="btn btn--quiet btn--sm" :disabled="saving" @click="images.splice(index, 1)">移除</button>
      </li>
    </ul>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <button type="submit" class="btn btn--primary" :disabled="!ready || saving">{{ saving ? '提交中…' : '提交反馈' }}</button>
  </form>
</template>

<style scoped>
.feedback-form, label { display: grid; gap: 8px }
.feedback-form { gap: 16px; align-items: start }
select, textarea { padding: 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--ink); width: 100%; font: inherit }
textarea { resize: vertical }
input { max-width: 100% }
small { color: var(--ink-3) }
.image-list { margin: 0; padding: 0; list-style: none }
.image-list li { display: flex; align-items: center; justify-content: space-between; gap: 8px }
.image-list span { overflow-wrap: anywhere }
.error { color: var(--err); margin: 0 }
.feedback-form > .btn { justify-self: start }
</style>
