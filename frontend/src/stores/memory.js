import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { deleteMemory, listMemories, updateMemory } from '../api/memory'
import { useUiStore } from './ui'

export const useMemoryStore = defineStore('memory', () => {
  const ui = useUiStore()

  const items = ref([])
  const status = ref('idle')
  const error = ref('')
  const editingId = ref('')
  const draft = ref('')
  const savingId = ref('')
  const removingId = ref('')

  const count = computed(() => items.value.length)

  async function fetchMemories({ silent = false } = {}) {
    if (!silent) status.value = 'loading'
    error.value = ''
    try {
      const data = await listMemories()
      items.value = Array.isArray(data) ? data : []
      status.value = 'ready'
    } catch (err) {
      status.value = 'error'
      error.value = err?.message || '记忆加载失败'
      if (!silent) ui.notify(error.value, 'err')
    }
  }

  function beginEdit(memory) {
    editingId.value = memory.id
    draft.value = memory.content
  }

  function cancelEdit() {
    editingId.value = ''
    draft.value = ''
  }

  async function save(memory) {
    const content = String(draft.value || '').trim()
    if (!content) {
      ui.notify('记忆内容不能为空', 'warn')
      return false
    }
    if (content === memory.content) {
      cancelEdit()
      return true
    }
    savingId.value = memory.id
    try {
      const updated = await updateMemory(memory.id, content)
      items.value = items.value.map((item) =>
        item.id === memory.id ? { ...item, ...(updated || {}), content } : item,
      )
      ui.notify('记忆已更新', 'ok')
      cancelEdit()
      return true
    } catch (err) {
      ui.notify(err?.message || '更新失败', 'err')
      return false
    } finally {
      savingId.value = ''
    }
  }

  async function remove(memory) {
    removingId.value = memory.id
    try {
      await deleteMemory(memory.id)
      items.value = items.value.filter((item) => item.id !== memory.id)
      ui.notify('记忆已删除', 'ok')
      return true
    } catch (err) {
      ui.notify(err?.message || '删除失败', 'err')
      return false
    } finally {
      removingId.value = ''
    }
  }

  return {
    items,
    status,
    error,
    editingId,
    draft,
    savingId,
    removingId,
    count,
    fetchMemories,
    beginEdit,
    cancelEdit,
    save,
    remove,
  }
})
