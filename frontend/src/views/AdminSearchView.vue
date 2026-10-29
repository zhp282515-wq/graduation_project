<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { isAbortError, request } from '../api/http'

const modes = [
  { value: 'vector', label: '纯向量检索', detail: '按语义相似度召回' },
  { value: 'hybrid', label: '混合检索', detail: '结合向量与关键词' },
  { value: 'hybrid_rerank', label: '混合检索 + 重排', detail: '融合召回后再排序' },
]
const modeLabels = Object.fromEntries(modes.map((mode) => [mode.value, mode.label]))
const scoreLabels = { cosine: '余弦相似度', rrf: 'RRF 融合分', rerank: '重排相关度' }

const query = ref('')
const mode = ref('hybrid_rerank')
const topK = ref(20)
const topN = ref(5)
const busy = ref(false)
const error = ref('')
const result = ref(null)
let controller = null

async function search() {
  if (busy.value) return
  const submittedQuery = query.value.trim()
  if (!submittedQuery || submittedQuery.length > 1000) {
    error.value = '请输入 1–1000 字的检索问题。'
    return
  }
  if (!Number.isInteger(topK.value) || !Number.isInteger(topN.value) ||
      topK.value < 1 || topK.value > 50 || topN.value < 1 || topN.value > 50) {
    error.value = '召回条数和最终展示条数须为 1–50 的整数。'
    return
  }
  if (topN.value > topK.value) {
    error.value = '最终展示条数不能超过召回条数。'
    return
  }
  const submitted = { query: submittedQuery, mode: mode.value, top_k: topK.value, top_n: topN.value }
  controller = new AbortController()
  busy.value = true
  error.value = ''
  try {
    const data = await request('/api/admin/knowledge/search', {
      method: 'POST', body: submitted, signal: controller.signal,
    })
    result.value = { ...submitted, ...data, query: submitted.query, top_k: submitted.top_k, top_n: submitted.top_n }
  } catch (err) {
    if (!isAbortError(err)) error.value = err.message || '检索失败，请稍后重试。'
  } finally {
    controller = null
    busy.value = false
  }
}

onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <section class="search-view view">
    <div class="view-inner">
      <header class="view-head">
        <div>
          <h1>知识检索</h1>
          <p>管理员独立检索工具 · 查询所有已就绪文档，包含仅管理员可见的内容。</p>
        </div>
      </header>

      <form class="knowledge-query" novalidate @submit.prevent="search">
        <label class="field-label" for="knowledge-query">检索问题</label>
        <div class="query-row">
          <input id="knowledge-query" v-model="query" type="search" maxlength="1000" placeholder="输入问题或关键词" :disabled="busy" />
          <button class="btn accent" type="submit" :disabled="busy">{{ busy ? '检索中…' : '检索知识库' }}</button>
        </div>

        <fieldset class="mode-field" :disabled="busy">
          <legend class="field-label">检索方式</legend>
          <div class="mode-options">
            <label v-for="option in modes" :key="option.value" class="mode-option" :class="{ selected: mode === option.value }">
              <input v-model="mode" type="radio" name="search-mode" :value="option.value" />
              <span><strong>{{ option.label }}</strong><small>{{ option.detail }}</small></span>
            </label>
          </div>
        </fieldset>

        <div class="search-parameters">
          <label for="search-top-k"><span>召回条数</span><input id="search-top-k" v-model.number="topK" type="number" min="1" max="50" step="1" inputmode="numeric" :disabled="busy" /></label>
          <label for="search-top-n"><span>最终展示条数</span><input id="search-top-n" v-model.number="topN" type="number" min="1" max="50" step="1" inputmode="numeric" :disabled="busy" /></label>
          <p>每项 1–50 条，展示条数不超过召回条数。</p>
        </div>
      </form>

      <p v-if="error" class="search-error" role="alert">{{ error }}</p>

      <section v-if="result" class="result-section" aria-labelledby="results-title" :aria-busy="busy">
        <div class="result-heading">
          <div><h2 id="results-title">检索结果</h2><p class="result-query">{{ result.query }}</p></div>
          <span class="result-count">{{ result.items?.length || 0 }} 条结果</span>
        </div>
        <div class="search-summary" aria-label="本次检索信息">
          <span>{{ modeLabels[result.mode] || result.mode }}</span>
          <span>召回 {{ result.top_k }} · 展示 {{ result.top_n }}</span>
          <span>候选 {{ result.candidate_count }} 条</span>
          <span>耗时 {{ Number(result.elapsed_ms.toFixed(1)) }} ms</span>
        </div>
        <p v-if="result.rerank_status === 'fallback'" class="fallback-note" role="status">重排失败，已回退到混合检索</p>
        <p v-if="!result.items?.length" class="empty-results">没有找到相关内容，可以换一组关键词。</p>
        <ol v-else class="search-results">
          <li v-for="(item, index) in result.items" :key="item.source.chunk_id || index">
            <div class="result-meta">
              <span>{{ index + 1 }} · {{ item.source.file_name }}</span>
              <span v-if="item.source.page">第 {{ item.source.page }} 页</span>
              <span v-if="typeof item.score === 'number' && Number.isFinite(item.score)">{{ scoreLabels[result.score_type] || '分数' }} {{ item.score.toFixed(3) }}</span>
            </div>
            <p>{{ item.text }}</p>
            <RouterLink :to="{ name: 'archive', params: { fileMd5: item.source.file_md5 }, query: { chunk: item.source.chunk_index } }">查看来源文档 →</RouterLink>
          </li>
        </ol>
      </section>
    </div>
  </section>
</template>

<style scoped>
.search-view { overflow: auto; padding-bottom: 44px; }
.view-head p { font-size: 14px; color: var(--ink-3); margin-top: 18px; }
.knowledge-query { margin-block: 35px 24px; max-width: 900px; }
.field-label { display: block; margin-bottom: 10px; font-size: 14px; font-weight: 500; }
.query-row { display: flex; gap: 12px; }
.query-row input, .search-parameters input { background: var(--surface); border: 1px solid var(--line-strong); border-radius: var(--r-sm); color: var(--ink); }
.query-row input { flex: 1; min-width: 0; padding: 11px 14px; font-size: 16px; }
.query-row .btn { height: auto; min-height: 44px; }
.mode-field { padding: 0; margin: 28px 0 0; border: 0; min-width: 0; }
.mode-options { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border: 1px solid var(--line); border-radius: var(--r-md); overflow: hidden; background:var(--surface); }
.mode-option { display: flex; align-items: flex-start; gap: 10px; padding: 16px 12px; cursor: pointer; border-right: 1px solid var(--line); }
.mode-option:last-child { border-right: 0; }
.mode-option.selected { background: var(--accent-soft); }
.mode-option input { accent-color: var(--accent); flex: none; margin-top: 3px; }
.mode-option strong, .mode-option small { display: block; }
.mode-option strong { font-size: 14px; font-weight: 500; }
.mode-option small { margin-top: 5px; color: var(--ink-3); font-size: 13px; line-height: 1.5; }
.mode-option:has(input:focus-visible) { outline: 2px solid var(--accent); outline-offset: -2px; }
.mode-field:disabled .mode-option { cursor: default; }
.search-parameters { display: flex; align-items: end; flex-wrap: wrap; gap: 14px 24px; margin-top: 24px; }
.search-parameters label { display: grid; gap: 8px; font-size: 14px; }
.search-parameters input { width: 100px; min-height: 42px; padding: 8px 10px; font-size: 15px; font-variant-numeric: tabular-nums; }
.search-parameters p { margin: 0 0 11px; color: var(--ink-3); font-size: 13px; }
.search-error { max-width: 900px; margin: 0 0 24px; color: var(--err); font-size: 14px; }
.result-section { max-width: 900px; margin-top: 38px; }
.result-heading { display: flex; justify-content: space-between; align-items: baseline; gap: 24px; }
.result-heading h2 { font-family: var(--font-serif); font-size: 23px; font-weight: 500; }
.result-query { margin-top: 10px; font-size: 16px; color:var(--ink); overflow-wrap: anywhere; }
.result-count { flex: none; color: var(--ink-3); font-size: 14px; font-variant-numeric: tabular-nums; }
.search-summary { display: flex; flex-wrap: wrap; gap: 8px 22px; padding: 16px 0; margin-top: 18px; border-block: 1px solid var(--line); color: var(--ink-3); font-size: 13px; font-variant-numeric: tabular-nums; }
.fallback-note { padding: 12px 0 0; color: var(--warn); font-size: 14px; }
.search-results { list-style: none; padding: 0; }
.search-results li { padding: 25px 0; border-bottom: 1px solid var(--line); }
.result-meta { display: flex; flex-wrap: wrap; gap: 8px 18px; color: var(--ink-3); font-size: 13px; font-variant-numeric: tabular-nums; }
.search-results p { font-size: 15px; line-height: 1.9; white-space: pre-wrap; overflow-wrap: anywhere; margin: 17px 0; }
.search-results a { color: var(--accent); font-size: 14px; }
.search-results a:hover { text-decoration: underline; text-underline-offset: 3px; }
.empty-results { margin-top: 28px; color: var(--ink-3); }
@media (max-width: 640px) {
  .query-row { flex-direction: column; }
  .mode-options { grid-template-columns: 1fr; }
  .mode-option { border-right: 0; border-bottom: 1px solid var(--line); }
  .mode-option:last-child { border-bottom: 0; }
  .search-parameters p { width: 100%; margin: 0; }
  .result-heading { align-items: flex-start; }
}
</style>
