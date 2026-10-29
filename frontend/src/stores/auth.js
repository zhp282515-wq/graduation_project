import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { getIdentity, signIn, signUp, signOut } from '../api/auth'
import { setCsrfToken, invalidateRequests } from '../api/http'
import { useConversationStore } from './conversations'
import { useLibraryStore } from './library'
import { useMemoryStore } from './memory'
import { useAtlasStore } from './atlas'
import { useNotesStore } from './notes'
import { useUiStore } from './ui'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const ready = ref(false)
  const isAdmin = computed(() => user.value?.role === 'admin')
  let restoring = null

  function clear() {
    invalidateRequests()
    user.value = null
    setCsrfToken('')
    useConversationStore().reset()
    useLibraryStore().reset()
    useMemoryStore().reset()
    useAtlasStore().reset()
    // 笔记按账号隔离：换账号时必须清掉上一位用户的缓存，避免串号。
    useNotesStore().reset()
    const ui = useUiStore()
    ui.openLedger(false)
    ui.openPalette(false)
    ui.visited = {}
  }

  function accept(identity) {
    user.value = identity.user
    setCsrfToken(identity.csrf_token)
    ready.value = true
  }

  async function restore() {
    if (ready.value) return
    if (restoring) return restoring
    restoring = (async () => {
      try { accept(await getIdentity()) }
      catch (error) {
        if (error.status !== 401) throw error
        user.value = null
        setCsrfToken('')
        ready.value = true
      } finally { restoring = null }
    })()
    return restoring
  }

  async function authenticate(mode, credentials) {
    clear()
    accept(await (mode === 'register' ? signUp(credentials) : signIn(credentials)))
  }

  async function logout() {
    try { await signOut() } catch (error) { if (error.status !== 401) throw error }
    clear(); ready.value = true
  }

  return { user, ready, isAdmin, restore, authenticate, logout, clear }
})
