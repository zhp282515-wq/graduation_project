<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import AppRail from './components/shell/AppRail.vue'
import SessionLedger from './components/shell/SessionLedger.vue'
import CommandPalette from './components/shell/CommandPalette.vue'
import ToastStack from './components/ui/ToastStack.vue'
import ConfirmDialog from './components/ui/ConfirmDialog.vue'
import { useUiStore } from './stores/ui'
import { useConversationStore } from './stores/conversations'

const auth = useAuthStore()
const router = useRouter()
const isPublic = computed(() => Boolean(route.meta.public))
const ui = useUiStore()
const conversation = useConversationStore()
const route = useRoute()
const isInquiry = computed(() => route.name === 'inquiry')
const ownsLedger = computed(() => isInquiry.value || route.name === 'notes')
const inlineLedger = computed(() => ownsLedger.value && ui.ledgerWide)

function onResize() {
  const next = window.innerWidth >= 1100
  if (next !== ui.ledgerWide) ui.openLedger(false)
  ui.ledgerWide = next
}

watch(
  () => route.meta?.mode,
  (mode) => {
    if (mode) ui.setMode(mode)
    ui.mobileNavOpen = false
    if (mode !== 'inquiry') ui.openLedger(false)
  },
  { immediate: true },
)

function onKeydown(event) {
  if (isPublic.value || !auth.user) return
  const mod = event.metaKey || event.ctrlKey
  if (mod && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    ui.openPalette(!ui.paletteOpen)
    return
  }
  if (mod && event.key.toLowerCase() === 'j' && isInquiry.value) {
    event.preventDefault()
    if (ui.ledgerWide) {
      const wasExpanded = ui.ledgerExpanded
      const previousFocus = document.activeElement
      ui.ledgerExpanded = true
      nextTick(() => {
        const focusSearch = () => {
          if (isInquiry.value && ui.ledgerWide && ui.ledgerExpanded &&
              (document.activeElement === previousFocus || document.activeElement === document.body)) {
            document.querySelector('#session-ledger input[type="search"]')?.focus()
          }
        }
        if (wasExpanded) focusSearch()
        else window.setTimeout(focusSearch, 340)
      })
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
  window.addEventListener('auth-expired', onExpired)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', onResize)
  window.removeEventListener('auth-expired', onExpired)
})
function onExpired() {
  const redirect = route.fullPath
  auth.clear()
  auth.ready = true
  router.replace({ path: '/login', query: { redirect } })
}
watch(() => auth.user?.id, (id) => {
  if (id) conversation.fetchSessions({ silent: true })
}, { immediate: true })
watch(isPublic, (value) => { document.documentElement.dataset.publicPage = value ? 'true' : 'false' }, { immediate: true })

/* 登录页 → 工作区：两张纸之间的一次显影。
   先铺一层同色纸幕遮住外壳切换，工作区从纸幕后面带着位移与散焦浮出来。 */
const arriving = ref(false)
let arrivalTimer = 0

watch(isPublic, (value, previous) => {
  window.clearTimeout(arrivalTimer)
  if (previous === true && value === false) {
    arriving.value = true
    arrivalTimer = window.setTimeout(() => { arriving.value = false }, 980)
  } else {
    arriving.value = false
  }
})

onBeforeUnmount(() => window.clearTimeout(arrivalTimer))
</script>

<template>
  <div v-if="isPublic" class="public-layout"><RouterView /><ToastStack /></div>
  <div v-else class="shell" :class="{ 'has-ledger': inlineLedger, 'ledger-collapsed': inlineLedger && !ui.ledgerExpanded, 'is-arriving': arriving }">
    <AppRail />
    <div v-if="ownsLedger" class="ledger-slot" :class="{ 'is-inline': inlineLedger, 'is-collapsed': inlineLedger && !ui.ledgerExpanded }" :inert="inlineLedger && !ui.ledgerExpanded ? true : undefined" :aria-hidden="inlineLedger && !ui.ledgerExpanded ? 'true' : undefined">
      <SessionLedger :inline="inlineLedger" />
    </div>
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

  <div v-if="arriving" class="swap-veil" aria-hidden="true" />
</template>

<style scoped>
/* 登录入口与工作区属于不同的外壳；切换外壳时只做一次轻柔显现。 */
.public-layout,
.shell {
  animation: layout-arrive 260ms cubic-bezier(0.16, 1, 0.3, 1) both;
}

@keyframes layout-arrive {
  from { opacity: 0.72; }
  to { opacity: 1; }
}

/* ------------------------------------------------------------
   登录页 → 工作区
   纸幕先盖住外壳切换，随后逐列显影：rail、会话账本、主区错峰落入。
   ------------------------------------------------------------ */

.swap-veil {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: var(--bg);
  pointer-events: none;
  animation: veil-dissolve 820ms cubic-bezier(0.16, 1, 0.3, 1) 90ms both;
}

/* 只在切换那一瞬盖住外壳，随后迅速化开，让下面的工作区显影。 */
@keyframes veil-dissolve {
  0% { opacity: 1; }
  22% { opacity: 0.72; }
  100% { opacity: 0; }
}

.shell.is-arriving {
  animation: shell-arrive 520ms var(--ease-out) both;
}

@keyframes shell-arrive {
  from { opacity: 0; }
  to { opacity: 1; }
}

.shell.is-arriving :deep(.rail),
.shell.is-arriving .ledger-slot,
.shell.is-arriving .main {
  animation: block-arrive 820ms cubic-bezier(0.16, 1, 0.3, 1) both;
}

.shell.is-arriving :deep(.rail) { animation-delay: 120ms; }
.shell.is-arriving .ledger-slot { animation-delay: 210ms; }
.shell.is-arriving .main { animation-delay: 300ms; }

@keyframes block-arrive {
  from {
    opacity: 0;
    transform: translate3d(0, 22px, 0);
    filter: blur(12px);
  }
  to {
    opacity: 1;
    transform: translate3d(0, 0, 0);
    filter: blur(0);
  }
}

/* 工作区页面保持短暂交接，避免整屏淡出造成闪白。 */
.main :deep(.view-enter-active) {
  transition: opacity 260ms cubic-bezier(0.16, 1, 0.3, 1),
    transform 260ms cubic-bezier(0.16, 1, 0.3, 1);
}

.main :deep(.view-leave-active) {
  transition: opacity 110ms ease, transform 110ms ease;
  pointer-events: none;
}

.main :deep(.view-enter-from) {
  opacity: 0.55;
  transform: translate3d(0, 8px, 0);
}

.main :deep(.view-leave-to) {
  opacity: 0.55;
  transform: translate3d(0, -4px, 0);
}

@media (prefers-reduced-motion: reduce) {
  .public-layout, .shell { animation: none; }
  .shell.is-arriving,
  .shell.is-arriving :deep(.rail),
  .shell.is-arriving .ledger-slot,
  .shell.is-arriving .main { animation: none; }
  .veil-leave-active { transition-duration: 1ms; }
  .main :deep(.view-enter-from),
  .main :deep(.view-leave-to) { transform: none; }
}
</style>
