import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { ApiError, isAbortError } from '../api/http'
import * as api from '../api/notes'

/** 已保存的 Markdown 笔记。列表与当前正在编辑的那条共享一份 items。 */
export const useNotesStore = defineStore('notes', () => {
  const items = ref([])
  const status = ref('idle')
  const error = ref('')
  const saving = ref(false)
  const removingId = ref('')
  let loading = null

  const sorted = computed(() =>
    [...items.value].sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || ''))),
  )

  function indexOf(id) {
    return items.value.findIndex((note) => note.id === id)
  }

  function upsert(note) {
    const at = indexOf(note.id)
    if (at >= 0) items.value.splice(at, 1, note)
    else items.value.unshift(note)
  }

  async function fetchNotes({ silent = false } = {}) {
    if (loading) return loading
    if (!silent) status.value = items.value.length ? status.value : 'loading'
    loading = (async () => {
      try {
        const rows = await api.listNotes()
        items.value = Array.isArray(rows) ? rows : []
        status.value = 'ready'
        error.value = ''
        return items.value
      } catch (err) {
        if (isAbortError(err)) return items.value
        status.value = 'error'
        error.value = err instanceof ApiError ? err.message : '笔记读取失败'
        return items.value
      } finally {
        loading = null
      }
    })()
    return loading
  }

  async function create({ title, content, sourceSessionId = null }) {
    saving.value = true
    try {
      const note = await api.createNote({ title, content, sourceSessionId })
      upsert(note)
      status.value = 'ready'
      return note
    } finally {
      saving.value = false
    }
  }

  async function save(note) {
    saving.value = true
    try {
      const saved = await api.updateNote(note.id, { title: note.title, content: note.content })
      upsert(saved)
      return saved
    } finally {
      saving.value = false
    }
  }

  async function rename(id, title) {
    const note = items.value[indexOf(id)]
    if (!note) return null
    return save({ ...note, title })
  }

  async function remove(id) {
    removingId.value = id
    try {
      await api.deleteNote(id)
      items.value = items.value.filter((note) => note.id !== id)
      return true
    } finally {
      removingId.value = ''
    }
  }

  function find(id) {
    return items.value.find((note) => note.id === id) || null
  }

  function reset() {
    items.value = []
    status.value = 'idle'
    error.value = ''
  }

  return { items, sorted, status, error, saving, removingId, fetchNotes, create, save, rename, remove, find, reset }
})
