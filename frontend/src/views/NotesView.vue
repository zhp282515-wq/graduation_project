<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useNotesStore } from '../stores/notes'
import { useUiStore } from '../stores/ui'
import { confirm } from '../composables/confirm'
import { renderMarkdown } from '../utils/markdown'
import { relativeTime } from '../utils/format'
import Icon from '../components/ui/Icon.vue'

const route = useRoute()
const router = useRouter()
const notes = useNotesStore()
const ui = useUiStore()

const draftTitle = ref('')
const draftBody = ref('')
const savedAt = ref('')
const mode = ref('edit')
const titleRef = ref(null)
const bodyRef = ref(null)
const busy = ref(false)

const noteId = computed(() => String(route.params.noteId || ''))
const note = computed(() => (noteId.value ? notes.find(noteId.value) : null))
const dirty = computed(
  () => Boolean(note.value) && (draftTitle.value !== note.value.title || draftBody.value !== note.value.content),
)
const previewHtml = computed(() => renderMarkdown(draftBody.value || ''))
const wordCount = computed(() => (draftBody.value.match(/[\u4e00-\u9fa5]|[A-Za-z0-9]+/g) || []).length)

function syncDraft() {
  const current = note.value
  draftTitle.value = current?.title || ''
  draftBody.value = current?.content || ''
  savedAt.value = current?.updated_at || ''
}

watch(note, syncDraft, { immediate: true })

onMounted(async () => {
  if (!notes.items.length) await notes.fetchNotes()
  if (!noteId.value && notes.sorted.length) router.replace(`/notes/${notes.sorted[0].id}`)
})

async function saveNote() {
  if (!note.value || busy.value) return
  if (!dirty.value) {
    ui.notify('没有需要保存的改动', 'info')
    return
  }
  busy.value = true
  try {
    const saved = await notes.save({ id: note.value.id, title: draftTitle.value.trim() || '未命名笔记', content: draftBody.value })
    savedAt.value = saved.updated_at
    ui.notify('笔记已保存', 'success')
  } catch (err) {
    ui.notify(err?.message || '保存失败', 'error')
  } finally {
    busy.value = false
  }
}

function download() {
  if (!note.value) return
  const title = draftTitle.value.trim() || '未命名笔记'
  const body = draftBody.value.startsWith('#') ? draftBody.value : `# ${title}\n\n${draftBody.value}`
  const blob = new Blob([body], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${title.replace(/[\\/:*?"<>|]/g, '_')}.md`
  link.click()
  URL.revokeObjectURL(url)
}

async function removeNote() {
  if (!note.value) return
  const ok = await confirm({
    title: `删除「${note.value.title}」？`,
    body: '这条笔记会从账号里永久删除，下载过的 .md 文件不受影响。',
    confirmText: '删除笔记',
    danger: true,
  })
  if (!ok) return
  await notes.remove(note.value.id)
  const next = notes.sorted[0]
  if (next) router.replace(`/notes/${next.id}`)
  else router.replace('/notes')
  ui.notify('笔记已删除', 'success')
}

async function focusTitle() {
  await nextTick()
  titleRef.value?.focus()
  titleRef.value?.select()
}

function onKeydown(event) {
  if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 's') return
  event.preventDefault()
  saveNote()
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <section class="notes-view view" aria-label="笔记">
    <header v-if="note" class="view-head notes-head">
      <div class="head-main">
        <p class="eyebrow">笔记 <span class="slash">/</span> NOTES</p>
        <input
          ref="titleRef"
          v-model="draftTitle"
          class="note-title"
          aria-label="笔记标题"
          spellcheck="false"
          @keydown.enter.prevent="bodyRef?.focus()"
        />
        <p class="note-meta mono">
          <span>{{ wordCount }} 字</span>
          <template v-if="savedAt"><span class="dot">·</span><span>{{ relativeTime(savedAt) }}更新</span></template>
          <template v-if="dirty"><span class="dot">·</span><span class="unsaved">未保存</span></template>
        </p>
      </div>
      <div class="head-actions note-actions">
        <button type="button" class="btn btn--quiet btn--sm" title="重命名" @click="focusTitle">
          <Icon name="edit" :size="12" />
          重命名
        </button>
        <button type="button" class="btn btn--quiet btn--sm" @click="download">
          <Icon name="download" :size="12" />
          下载 .md
        </button>
        <button type="button" class="btn btn--quiet btn--sm danger" :disabled="notes.removingId === note.id" @click="removeNote">
          <Icon name="trash" :size="12" />
          删除
        </button>
        <button type="button" class="btn btn--solid btn--sm" :disabled="busy || !dirty" @click="saveNote">
          {{ busy ? '保存中…' : dirty ? '保存' : '已保存' }}
        </button>
      </div>
    </header>

    <div v-if="!note" class="notes-blank">
      <div v-if="notes.status === 'loading'" class="state-block">
        <p class="state-title">正在读取笔记…</p>
      </div>
      <div v-else-if="notes.status === 'error'" class="state-block">
        <p class="state-title">笔记打不开</p>
        <p class="state-text">{{ notes.error }}</p>
        <button type="button" class="link-btn" @click="notes.fetchNotes()">重试</button>
      </div>
      <div v-else-if="noteId" class="state-block" data-align="center">
        <p class="state-title">这条笔记不在这里</p>
        <p class="state-text">它可能已经被删除，或者属于另一个账号——笔记只对创建它的人可见。</p>
        <RouterLink class="btn btn--solid btn--sm" to="/notes">
          <Icon name="file" :size="12" />
          回到我的笔记
        </RouterLink>
      </div>
      <div v-else class="state-block" data-align="center">
        <p class="state-title">还没有笔记</p>
        <p class="state-text">在问学的回答下方点「保存为笔记」，这条回答会原样存成 Markdown，收进左侧列表。</p>
        <RouterLink class="btn btn--solid btn--sm" to="/inquiry">
          <Icon name="inquiry" :size="12" />
          去问学
        </RouterLink>
      </div>
    </div>

    <div v-else class="notes-body" :data-mode="mode">
      <div class="pane pane--edit">
        <div class="pane-head">
          <span class="mono">Markdown</span>
          <button type="button" class="link-btn pane-switch" @click="mode = 'view'">预览</button>
        </div>
        <textarea
          ref="bodyRef"
          v-model="draftBody"
          class="note-editor"
          spellcheck="false"
          aria-label="笔记正文"
          placeholder="从这里开始写。支持 Markdown：标题、列表、代码块、表格。"
        />
      </div>
      <div class="pane pane--view">
        <div class="pane-head">
          <span class="mono">预览</span>
          <button type="button" class="link-btn pane-switch" @click="mode = 'edit'">编辑</button>
        </div>
        <div class="note-preview">
          <div v-if="previewHtml" class="md markdown-body" v-html="previewHtml" />
          <p v-else class="preview-empty">正文还是空的。</p>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.notes-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  width: 100%;
  padding: 0 var(--gutter);
}

.notes-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding: 22px 0 14px;
  border-bottom: 1px solid var(--line);
}

.head-main {
  min-width: 0;
  flex: 1 1 auto;
}

.eyebrow {
  margin: 0 0 6px;
  font-size: var(--text-xs);
  letter-spacing: 0.14em;
  color: var(--ink-4);
  text-transform: uppercase;
}

.eyebrow .slash {
  padding: 0 4px;
  color: var(--line-strong);
}

.note-title {
  display: block;
  width: 100%;
  padding: 0;
  border: 0;
  background: none;
  font-family: var(--font-serif);
  font-size: clamp(24px, 2.4vw, 32px);
  font-weight: 500;
  line-height: 1.25;
  color: var(--ink);
  letter-spacing: 0.01em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.note-title:focus {
  outline: none;
}

.note-meta {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 8px 0 0;
  font-size: var(--text-xs);
  color: var(--ink-4);
}

.note-meta .dot {
  color: var(--line-strong);
}

.unsaved {
  color: var(--warn, #a9743a);
}

.note-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
}

.note-actions .danger:hover {
  color: var(--err);
}

.notes-body {
  flex: 1 1 auto;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}

.pane {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.pane--view {
  border-left: 1px solid var(--line);
}

.pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 18px;
  font-size: var(--text-xs);
  letter-spacing: 0.08em;
  color: var(--ink-4);
  border-bottom: 1px solid var(--line);
}

.pane-switch {
  display: none;
}

.note-editor {
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
  padding: 22px 18px 64px;
  border: 0;
  background: none;
  resize: none;
  font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: 13.5px;
  line-height: 1.9;
  color: var(--ink-2);
  tab-size: 2;
}

.note-editor:focus {
  outline: none;
}

.note-preview {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 26px 64px;
}

.preview-empty {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--ink-4);
}

.notes-blank {
  flex: 1 1 auto;
  display: grid;
  place-items: center;
  padding-bottom: 12vh;
}

@media (max-width: 980px) {
  .notes-head {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }

  .note-actions {
    flex-wrap: wrap;
  }

  .notes-body {
    grid-template-columns: minmax(0, 1fr);
  }

  .notes-body[data-mode='edit'] .pane--view,
  .notes-body[data-mode='view'] .pane--edit {
    display: none;
  }

  .pane--view {
    border-left: 0;
  }

  /* 单栏时它是个切换按钮，得看得出能点。 */
  .pane-switch {
    display: inline-flex;
    align-items: center;
    padding: 4px 12px;
    border: 1px solid var(--line);
    border-radius: var(--r-full);
    background: var(--surface);
    color: var(--ink-2);
    font-size: var(--text-xs);
    letter-spacing: 0.04em;
  }

  .pane-switch:hover {
    background: var(--surface-2);
    color: var(--ink);
  }
}
</style>
