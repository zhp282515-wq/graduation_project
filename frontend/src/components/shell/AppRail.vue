<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import { useUiStore } from '../../stores/ui'
import Icon from '../ui/Icon.vue'

const auth = useAuthStore()
const router = useRouter()
const ui = useUiStore()
async function logout() {
  try { await auth.logout(); router.replace('/login') }
  catch (error) { ui.notify(error.message || '退出未完成，请重试', 'err') }
}

const route = useRoute()

const items = computed(() => [
  { mode: 'inquiry', label: '问学', latin: 'Inquiry', icon: 'inquiry', to: '/inquiry', index: '01' },
  { mode: 'archive', label: '典藏', latin: 'Archive', icon: 'archive', to: '/archive', index: '02' },
  { mode: 'atlas', label: '星野', latin: 'Atlas', icon: 'atlas', to: '/atlas', index: '03' },
  ...(auth.isAdmin ? [
    { mode: 'search', label: '检索', latin: 'Search', icon: 'search', to: '/admin/search', index: '04' },
    { mode: 'users', label: '账号', latin: 'Users', icon: 'users', to: '/admin/users', index: '05' },
  ] : []),
])

const currentMode = computed(() => route.meta?.mode || 'inquiry')
</script>

<template>
  <nav class="rail" aria-label="主导航">
    <RouterLink to="/inquiry" class="rail-brand" aria-label="星野台，返回问学">
      <span class="rail-wordmark serif" aria-hidden="true">星野台</span>
    </RouterLink>

    <ul class="rail-nav">
      <li v-for="item in items" :key="item.mode">
        <RouterLink
          :to="item.to"
          class="rail-item"
          :class="{ 'is-active': currentMode === item.mode }"
          :aria-current="currentMode === item.mode ? 'page' : undefined"
        >
          <Icon :name="item.icon" :size="18" />
          <span class="rail-label">{{ item.label }}</span>
        </RouterLink>
      </li>
    </ul>

    <div class="rail-foot">
      <RouterLink :to="auth.user?.must_change_password ? '/password' : '/settings'" class="rail-tool" :class="{ 'is-active': currentMode === 'settings' }" :aria-current="currentMode === 'settings' ? 'page' : undefined" :title="auth.user?.username + ' · 设置'" aria-label="设置"><Icon name="settings" :size="17" /><span class="tool-label">设置</span></RouterLink>
      <button type="button" class="rail-tool" @click="logout" aria-label="退出登录"><Icon name="logout" :size="17" /><span class="tool-label">退出</span></button>
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
  background: var(--surface);
}

.rail-brand {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 44px;
  min-height: 58px;
  text-decoration: none;
}

.rail-wordmark {
  font-size: 11px;
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
  gap: 7px;
  padding: 12px 2px 10px;
  border-radius: var(--r-md);
  color: var(--ink-3);
  text-decoration: none;
  transition: color var(--t-fast) var(--ease-out), background var(--t-fast) var(--ease-out),
    transform var(--t-fast) var(--ease-out);
}

.rail-item:active {
  transform: scale(0.97);
  transition-duration: 90ms;
}

.rail-item::before {
  content: "";
  position: absolute;
  left: -6px;
  top: 50%;
  width: 2px;
  height: 18px;
  border-radius: var(--r-full);
  background: var(--accent);
  opacity: 0;
  transform: translateY(-50%) scaleY(0.4);
  transition: opacity var(--t-base) var(--ease-out), transform var(--t-base) var(--ease-out);
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
  opacity: 1;
  transform: translateY(-50%) scaleY(1);
}

.rail-label {
  font-family: var(--font-serif);
  font-size: var(--text-xs);
  letter-spacing: 0.12em;
  text-indent: 0.12em;
  line-height: 1;
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
  border-radius: var(--r-md);
  color: var(--ink-3);
  transition: color var(--t-fast) var(--ease-out), background var(--t-fast) var(--ease-out),
    transform var(--t-fast) var(--ease-out);
}

.rail-tool.is-active {
  color: var(--accent);
  background: var(--surface-2);
}

.rail-tool:hover {
  color: var(--ink);
  background: var(--accent-soft);
}

.rail-tool:active {
  transform: scale(0.97);
  transition-duration: 90ms;
}

.tool-label {
  font-size: var(--text-xs);
  letter-spacing: 0.1em;
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
  font-size: 11px;
  line-height: 1;
}

.rail-tool--hint {
  flex-direction: row;
  justify-content: center;
  gap: 3px;
  padding: 6px 0;
  gap: 2px;
  white-space: nowrap;
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

  .rail-brand,
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
    font-size: 11px;
    letter-spacing: 0.08em;
  }

  .tool-count {
    top: 0;
    right: 8px;
  }
}
</style>
