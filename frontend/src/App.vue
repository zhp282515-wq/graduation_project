<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppRail from './components/shell/AppRail.vue'
import SessionLedger from './components/shell/SessionLedger.vue'
import CommandPalette from './components/shell/CommandPalette.vue'
import ToastStack from './components/ui/ToastStack.vue'
import ConfirmDialog from './components/ui/ConfirmDialog.vue'
import { useUiStore } from './stores/ui'
import { useConversationStore } from './stores/conversations'

const ui = useUiStore()
const conversation = useConversationStore()
const route = useRoute()

const viewportWidth = ref(typeof window === 'undefined' ? 1440 : window.innerWidth)
const inlineLedger = computed(() => ui.ledgerPinned && viewportWidth.value >= 1100)
function onResize() {
  viewportWidth.value = window.innerWidth
}

watch(
  () => route.meta?.mode,
  (mode) => {
    if (mode) ui.setMode(mode)
    ui.mobileNavOpen = false
  },
  { immediate: true },
)

function onKeydown(event) {
  const mod = event.metaKey || event.ctrlKey
  if (mod && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    ui.openPalette(!ui.paletteOpen)
    return
  }
  if (mod && event.key.toLowerCase() === 'j') {
    event.preventDefault()
    if (inlineLedger.value) {
      document.querySelector('.ledger--inline input[type="search"]')?.focus()
      return
    }
    if (ui.ledgerPinned) {
      ui.openLedger(true, true)
      return
    }
    ui.openLedger(!ui.ledgerOpen)
    return
  }
  if (event.key === 'Escape') {
    if (ui.paletteOpen) ui.openPalette(false)
    else if (ui.ledgerOpen) ui.openLedger(false)
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', onResize)
  conversation.fetchSessions({ silent: conversation.sessions.length > 0 })
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', onResize)
})
</script>

<template>
  <div class="shell" :class="{ 'has-ledger': inlineLedger }">
    <AppRail />
    <SessionLedger :inline="inlineLedger" />
    <main class="main">
      <RouterView v-slot="{ Component }">
        <Transition name="view" mode="out-in">
          <component :is="Component" />
        </Transition>
      </RouterView>
    </main>

    <CommandPalette />
    <ToastStack />
    <ConfirmDialog />
  </div>
</template>
