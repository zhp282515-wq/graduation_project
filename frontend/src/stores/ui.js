import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

const THEME_KEY = 'jxnu.theme'
const VISITED_KEY = 'jxnu.visited-sessions'
const LEDGER_PIN_KEY = 'jxnu.ledger.pinned'

function readTheme() {
  try {
    const stored = localStorage.getItem(THEME_KEY)
    if (stored === 'paper' || stored === 'night') return stored
  } catch {
    // 隐私模式下 localStorage 可能不可用，退回浅色即可。
  }
  try {
    if (window.matchMedia?.('(prefers-color-scheme: dark)').matches) return 'night'
  } catch {
    /* noop */
  }
  return 'paper'
}

function readVisited() {
  try {
    const raw = localStorage.getItem(VISITED_KEY)
    const parsed = raw ? JSON.parse(raw) : {}
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function readLedgerPinned() {
  try {
    return localStorage.getItem(LEDGER_PIN_KEY) === 'on'
  } catch {
    return false
  }
}

let toastSeed = 0

export const useUiStore = defineStore('ui', () => {
  const theme = ref(readTheme())
  const mode = ref('inquiry')
  const ledgerOpen = ref(false)
  const ledgerPinned = ref(readLedgerPinned())
  const paletteOpen = ref(false)
  const mobileNavOpen = ref(false)
  const toasts = ref([])
  const visited = ref(readVisited())

  const isNight = computed(() => theme.value === 'night')

  function applyTheme() {
    const root = document.documentElement
    root.dataset.theme = theme.value
    root.style.colorScheme = theme.value === 'night' ? 'dark' : 'light'
    const meta = document.querySelector('meta[name="theme-color"]')
    if (meta) meta.setAttribute('content', theme.value === 'night' ? '#07070b' : '#f2eee4')
    try {
      localStorage.setItem(THEME_KEY, theme.value)
    } catch {
      /* noop */
    }
  }

  applyTheme()
  watch(theme, applyTheme)

  function setTheme(next) {
    theme.value = next === 'night' ? 'night' : 'paper'
  }

  function toggleTheme() {
    setTheme(theme.value === 'night' ? 'paper' : 'night')
  }

  function setMode(next) {
    mode.value = next
  }

  function openLedger(value = true, force = false) {
    if (value && ledgerPinned.value && !force) return
    ledgerOpen.value = value
  }

  function setLedgerPinned(value) {
    ledgerPinned.value = Boolean(value)
    if (ledgerPinned.value) ledgerOpen.value = false
    try {
      localStorage.setItem(LEDGER_PIN_KEY, ledgerPinned.value ? 'on' : 'off')
    } catch {
      /* noop */
    }
  }

  function toggleLedgerPinned() {
    setLedgerPinned(!ledgerPinned.value)
  }

  function toggleLedger() {
    ledgerOpen.value = !ledgerOpen.value
  }

  function openPalette(value = true) {
    paletteOpen.value = value
  }

  function notify(text, kind = 'info', options = {}) {
    if (!text) return null
    toastSeed += 1
    const toast = {
      id: `toast-${toastSeed}`,
      text: String(text),
      kind,
      action: options.action || null,
      sticky: Boolean(options.sticky),
    }
    toasts.value = [...toasts.value.slice(-3), toast]
    if (!toast.sticky) {
      window.setTimeout(() => dismissToast(toast.id), options.duration ?? 3600)
    }
    return toast.id
  }

  function dismissToast(id) {
    toasts.value = toasts.value.filter((item) => item.id !== id)
  }

  function markVisited(sessionId) {
    if (!sessionId) return
    visited.value = { ...visited.value, [sessionId]: Date.now() }
    try {
      localStorage.setItem(VISITED_KEY, JSON.stringify(visited.value))
    } catch {
      /* noop */
    }
  }

  function isUnread(session) {
    if (!session?.id || !session?.updated_at) return false
    const seen = visited.value[session.id]
    if (!seen) return false
    const stamp = new Date(session.updated_at).getTime()
    return Number.isFinite(stamp) && stamp > seen + 1500
  }

  return {
    theme,
    isNight,
    mode,
    ledgerOpen,
    paletteOpen,
    mobileNavOpen,
    toasts,
    visited,
    setTheme,
    toggleTheme,
    ledgerPinned,
    setLedgerPinned,
    toggleLedgerPinned,
    setMode,
    openLedger,
    toggleLedger,
    openPalette,
    notify,
    dismissToast,
    markVisited,
    isUnread,
  }
})
