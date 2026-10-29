<script setup>
import { computed, onMounted, ref } from 'vue'
import { http, isAbortError } from '../api/http'

const data = ref(null)
const providerId = ref('')
const modelId = ref('')
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const saved = ref(false)
const provider = computed(() => data.value?.providers.find(item => item.id === providerId.value))
const model = computed(() => provider.value?.models.find(item => item.id === modelId.value))
const dirty = computed(() => providerId.value !== data.value?.current.provider || modelId.value !== data.value?.current.model)
const canSave = computed(() => provider.value?.configured && model.value && dirty.value && !saving.value)

function apply(result) {
  data.value = result
  const selected = result.providers.find(item => item.id === result.current.provider && item.configured && item.models.some(m => m.id === result.current.model))
  const initial = selected || result.providers.find(item => item.configured && item.models.length)
  providerId.value = initial?.id || ''
  modelId.value = selected ? result.current.model : (initial?.models[0]?.id || '')
}
async function load() {
  loading.value = true; error.value = ''
  try { apply(await http.get('/api/admin/model-settings')) }
  catch (err) { if (!isAbortError(err)) error.value = err.message || '模型配置加载失败，请重试。' }
  finally { loading.value = false }
}
function selectProvider() {
  modelId.value = provider.value?.models[0]?.id || ''
  error.value = ''; saved.value = false
}
async function save() {
  if (!canSave.value) return
  saving.value = true; error.value = ''; saved.value = false
  try {
    const result = await http.put('/api/admin/model-settings', { provider: providerId.value, model: modelId.value })
    apply(result); saved.value = true
  } catch (err) { if (!isAbortError(err)) error.value = err.message || '保存失败，请重试。' }
  finally { saving.value = false }
}
onMounted(load)
</script>

<template>
  <section class="model-view view">
    <div class="view-inner">
      <header class="view-head"><div><h1 class="head-title">模型配置</h1><p>为全站之后开始的对话选择模型。正在生成的回答不会受到影响。</p></div></header>
      <div v-if="loading" class="model-state" role="status">正在加载模型配置…</div>
      <div v-else-if="!data" class="model-state"><p role="alert">{{ error }}</p><button class="btn" type="button" @click="load">重试</button></div>
      <template v-else>
        <div class="current-model"><span>当前模型</span><strong>{{ data.current.provider }} / {{ data.current.model }}</strong></div>
        <p v-if="data.current_error" class="model-warning" role="alert">{{ data.current_error }} 请重新选择可用模型并保存。</p>
        <form class="model-form" @submit.prevent="save">
          <label for="model-provider">供应商</label>
          <select id="model-provider" v-model="providerId" :disabled="saving" @change="selectProvider">
            <option value="" disabled>暂无可用供应商</option>
            <option v-for="item in data.providers" :key="item.id" :value="item.id" :disabled="!item.configured || !item.models.length">{{ item.label }}{{ item.configured ? ' · 已配置密钥' : ' · 未配置密钥' }}</option>
          </select>
          <p class="model-help">密钥由服务端环境变量配置。已配置密钥不代表已验证连接。</p>
          <label for="model-choice">模型</label>
          <select id="model-choice" v-model="modelId" :disabled="saving || !provider" @change="error = ''; saved = false">
            <option value="" disabled>请选择模型</option>
            <option v-for="item in provider?.models || []" :key="item.id" :value="item.id">{{ item.label }}</option>
          </select>
          <p v-if="model" class="model-help">{{ model.reasoning ? '支持深度思考' : '不支持深度思考' }} · {{ model.images ? '支持图片输入' : '不支持图片输入' }}</p>
          <p v-if="error" class="model-error" role="alert">{{ error }}</p>
          <p v-if="saved" class="model-success" role="status">模型配置已保存，后续对话将使用新配置。</p>
          <button class="btn accent" type="submit" :disabled="!canSave">{{ saving ? '保存中…' : '保存配置' }}</button>
        </form>
      </template>
    </div>
  </section>
</template>

<style scoped>
.model-view { overflow-y: auto; padding-bottom: 50px; }
.view-head p { margin-top: 18px; max-width: 60ch; color: var(--ink-3); font-size: 14px; line-height: 1.7; }
.current-model { display: flex; gap: 18px; align-items: baseline; flex-wrap: wrap; margin-top: 34px; padding-bottom: 20px; border-bottom: 1px solid var(--line); font-size: 14px; }
.current-model span { color: var(--ink-3); }
.current-model strong { font-weight: 600; overflow-wrap: anywhere; }
.model-form { display: grid; gap: 9px; max-width: 480px; margin-top: 28px; }
.model-form label { margin-top: 12px; font-size: 14px; font-weight: 600; }
.model-form select { width: 100%; min-height: 44px; padding: 8px 12px; border: 1px solid var(--line-strong); border-radius: var(--r-xs); background: var(--surface); color: var(--ink); font: inherit; }
.model-form button { min-height: 44px; margin-top: 20px; }
.model-help { margin: 0; color: var(--ink-3); font-size: 13px; line-height: 1.7; }
.model-warning, .model-error { color: var(--err); font-size: 14px; line-height: 1.7; }
.model-warning { margin: 18px 0 0; }
.model-success { color: var(--ok); font-size: 14px; }
.model-state { margin-top: 30px; color: var(--ink-2); font-size: 14px; }
.model-state button { margin-top: 12px; }
</style>
