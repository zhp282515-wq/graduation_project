<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useUiStore } from '../../stores/ui'
import { useConversationStore } from '../../stores/conversations'
import Icon from '../ui/Icon.vue'
import sealUrl from '../../assets/school-seal.svg'

const ui = useUiStore()
const conversation = useConversationStore()
const route = useRoute()

const items = [
  { mode: 'inquiry', label: '问学', latin: 'Inquiry', icon: 'inquiry', to: '/inquiry', index: '01' },
  { mode: 'archive', label: '典藏', latin: 'Archive', icon: 'archive', to: '/archive', index: '02' },
  { mode: 'memory', label: '记忆', latin: 'Memory', icon: 'memory', to: '/memory', index: '03' },
  { mode: 'atlas', label: '星野', latin: 'Atlas', icon: 'atlas', to: '/atlas', index: '04' },
]

const currentMode = computed(() => route.meta?.mode || 'inquiry')
const historyCount = computed(() => conversation.sessions.length)
</script>

<template>
  <nav class="rail" aria-label="主导航">
    <RouterLink to="/inquiry" class="seal" aria-label="星野台，返回问学">
      <img class="seal-img" :src="sealUrl" alt="江西师范大学校徽" width="42" height="35" />
      <span class="seal-caption serif" aria-hidden="true">星野台</span>
    </RouterLink>

    <ul class="rail-nav">
      <li v-for="item in items" :key="item.mode">
        <RouterLink
          :to="item.to"
          class="rail-item"
          :class="{ 'is-active': currentMode === item.mode }"
          :aria-current="currentMode === item.mode ? 'page' : undefined"
        >
          <span class="rail-index mono">{{ item.index }}</span>
          <Icon :name="item.icon" :size="18" />
          <span class="rail-label">{{ item.label }}</span>
          <span class="rail-latin">{{ item.latin }}</span>
        </RouterLink>
      </li>
    </ul>

    <div class="rail-foot">
      <button
        type="button"
        class="rail-tool"
        :aria-expanded="ui.ledgerOpen"
        aria-controls="session-ledger"
        @click="ui.openLedger(!ui.ledgerOpen)"
      >
        <Icon name="message" :size="17" />
        <span class="tool-label">会话</span>
        <span v-if="historyCount" class="tool-count mono">{{ historyCount }}</span>
      </button>
      <button
        type="button"
        class="rail-tool rail-tool--theme"
        :aria-label="ui.isNight ? '切换到纸本' : '切换到星夜'"
        :title="ui.isNight ? '纸本' : '星夜'"
        @click="ui.toggleTheme()"
      >
        <Icon :name="ui.isNight ? 'sun' : 'moon'" :size="17" />
        <span class="tool-label">{{ ui.isNight ? '晨光' : '夜色' }}</span>
      </button>
      <button type="button" class="rail-tool rail-tool--hint" aria-label="打开命令面板" @click="ui.openPalette(true)">
        <span class="kbd">⌘</span><span class="kbd">K</span>
      </button>
    </div>
  </nav>
</template>

<style scoped>
.rail {
  position: relative;
  z-index: 30;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 26px;
  padding: 22px 0 18px;
  border-right: 1px solid var(--line);
  background: var(--bg);
}

.seal {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  text-decoration: none;
}

.seal-img {
  display: block;
  width: 42px;
  height: auto;
  opacity: 0.92;
  transition: opacity var(--t-base) var(--ease-out);
}

.seal:hover .seal-img {
  opacity: 1;
}

.seal-caption {
  font-size: 10px;
  letter-spacing: 0.3em;
  color: var(--ink-3);
  writing-mode: vertical-rl;
  text-orientation: upright;
  line-height: 1.2;
  max-height: 58px;
}

.rail-nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  list-style: none;
  width: 100%;
  padding: 0 10px;
  margin: 0;
  overflow-y: auto;
}

.rail-item {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 10px 2px 8px;
  border-radius: var(--r-sm);
  color: var(--ink-3);
  text-decoration: none;
  transition: color var(--t-fast), background var(--t-fast);
}

.rail-item::before {
  content: "";
  position: absolute;
  left: -5px;
  top: 50%;
  width: 2px;
  height: 0;
  background: var(--accent);
  transform: translateY(-50%);
  transition: height var(--t-base) var(--ease-out);
}

.rail-item:hover {
  color: var(--ink);
  background: var(--accent-soft);
}

.rail-item.is-active {
  color: var(--ink);
  background: var(--surface-2);
}

.rail-item.is-active::before {
  height: 20px;
}

.rail-index {
  font-size: 9px;
  letter-spacing: 0.14em;
  color: var(--ink-4);
}

.rail-item.is-active .rail-index {
  color: var(--accent);
}

.rail-label {
  font-family: var(--font-serif);
  font-size: 12px;
  letter-spacing: 0.16em;
  text-indent: 0.16em;
  line-height: 1;
}

.rail-latin {
  display: none;
}

.rail-foot {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  width: 100%;
}

.rail-tool {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  width: 100%;
  padding: 8px 0;
  border-radius: var(--r-sm);
  color: var(--ink-3);
  transition: color var(--t-fast), background var(--t-fast);
}

.rail-tool:hover {
  color: var(--ink);
  background: var(--surface-2);
}

.tool-label {
  font-size: 9.5px;
  letter-spacing: 0.18em;
}

.tool-count {
  position: absolute;
  top: 3px;
  right: 12px;
  min-width: 15px;
  height: 15px;
  padding: 0 3px;
  display: grid;
  place-items: center;
  border-radius: var(--r-full);
  background: var(--accent);
  color: var(--accent-ink);
  font-size: 9px;
  line-height: 1;
}

.rail-tool--hint {
  flex-direction: row;
  justify-content: center;
  gap: 3px;
  padding: 6px 0;
}

.rail-tool--hint:hover {
  background: transparent;
}

@media (max-width: 900px) {
  .rail {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 40;
    flex-direction: row;
    align-items: stretch;
    gap: 0;
    padding: 6px 6px calc(6px + env(safe-area-inset-bottom));
    border-right: 0;
    border-top: 1px solid var(--line);
    background: var(--surface-glass);
    backdrop-filter: blur(14px);
  }

  .seal,
  .rail-tool--hint,
  .rail-tool--theme {
    display: none;
  }

  .rail-nav {
    flex-direction: row;
    gap: 2px;
    padding: 0;
    overflow-x: auto;
  }

  .rail-item {
    flex: 1;
    min-width: 58px;
    padding: 6px 2px;
  }

  .rail-item::before {
    left: 50%;
    top: -6px;
    transform: translateX(-50%);
    width: 0;
    height: 2px;
  }

  .rail-item.is-active::before {
    width: 18px;
    height: 2px;
  }

  .rail-index {
    display: none;
  }

  .rail-foot {
    flex-direction: row;
    width: auto;
    gap: 0;
    padding: 0;
  }

  .rail-tool {
    width: 64px;
    padding: 6px 0;
  }

  .tool-label {
    display: inline;
    font-size: 9px;
    letter-spacing: 0.08em;
  }

  .tool-count {
    top: 0;
    right: 8px;
  }
}
</style>
