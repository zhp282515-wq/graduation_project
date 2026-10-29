<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import MemoryView from './MemoryView.vue'
import PasswordView from './PasswordView.vue'
import ModelSettingsView from './ModelSettingsView.vue'

const route = useRoute()
const auth = useAuthStore()
const section = computed(() => route.path === '/password' ? 'password' : route.path === '/settings/model' ? 'model' : 'memory')
</script>

<template>
  <section class="settings-view" aria-label="设置">
    <aside class="settings-nav">
      <p class="nav-label">设置</p>
      <p class="nav-owner mono">{{ auth.user?.username }}</p>
      <nav aria-label="设置栏目">
        <RouterLink v-if="!auth.user?.must_change_password" to="/settings" :class="{ selected: section === 'memory' }" :aria-current="section === 'memory' ? 'page' : undefined">长期记忆</RouterLink>
        <RouterLink to="/password" :class="{ selected: section === 'password' }" :aria-current="section === 'password' ? 'page' : undefined">修改密码</RouterLink>
        <RouterLink v-if="auth.isAdmin && !auth.user?.must_change_password" to="/settings/model" :class="{ selected: section === 'model' }" :aria-current="section === 'model' ? 'page' : undefined">模型配置</RouterLink>
      </nav>
    </aside>
    <div class="settings-content">
      <Transition name="settings-section" mode="out-in">
        <PasswordView v-if="section === 'password'" key="password" />
        <ModelSettingsView v-else-if="section === 'model' && auth.isAdmin" key="model" />
        <MemoryView v-else key="memory" />
      </Transition>
    </div>
  </section>
</template>

<style scoped>
/* 页面抬头由子视图的 .view-head 提供，这里只留一条栏目导航。 */
.settings-view {
  display: grid;
  grid-template-columns: var(--nav-w) minmax(0, 1fr);
  flex: 1;
  min-height: 0;
  width: 100%;
}

.settings-nav {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 28px 14px 24px 20px;
  border-right: 1px solid var(--line);
  background: var(--surface-2);
}

.nav-label {
  margin: 0;
  padding: 0 12px 2px;
  font-size: var(--text-xs);
  letter-spacing: 0.16em;
  color: var(--ink-3);
}

.nav-owner {
  margin: 0;
  padding: 0 12px;
  font-size: var(--text-xs);
  letter-spacing: 0.06em;
  color: var(--ink-4);
  overflow-wrap: anywhere;
}

.settings-nav nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.settings-nav a {
  padding: 9px 12px;
  border-left: 2px solid transparent;
  border-radius: var(--r-md);
  font-size: var(--text-base);
  color: var(--ink-2);
  text-decoration: none;
  transition: background var(--t-fast) var(--ease-out), color var(--t-fast) var(--ease-out);
}

.settings-nav a:hover {
  background: var(--surface-3);
  color: var(--ink);
}

/* 选中态只换底色与左侧指标，不动字重，避免点击时行宽跳动。 */
.settings-nav a.selected {
  background: var(--accent-soft);
  border-left-color: var(--accent);
  color: var(--ink);
}

.settings-content {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.settings-section-enter-active {
  transition: opacity var(--t-base) var(--ease-out), transform var(--t-base) var(--ease-out);
}

.settings-section-leave-active {
  transition: opacity var(--t-fast) var(--ease-out), transform var(--t-fast) var(--ease-out);
  pointer-events: none;
}

.settings-section-enter-from {
  opacity: 0.7;
  transform: translate3d(0, 6px, 0);
}

.settings-section-leave-to {
  opacity: 0.7;
  transform: translate3d(0, -2px, 0);
}

@media (prefers-reduced-motion: reduce) {
  .settings-section-enter-from,
  .settings-section-leave-to {
    transform: none;
  }
}

@media (max-width: 900px) {
  .settings-view {
    display: flex;
    flex-direction: column;
  }

  .settings-nav {
    flex-direction: row;
    align-items: center;
    gap: 10px;
    padding: 12px var(--gutter);
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .nav-label,
  .nav-owner {
    display: none;
  }

  .settings-nav a {
    padding: 8px 12px;
    border-left: 0;
    border-bottom: 2px solid transparent;
    white-space: nowrap;
  }

  .settings-nav a.selected {
    border-bottom-color: var(--accent);
  }

  .settings-nav nav {
    flex-direction: row;
    gap: 4px;
    overflow-x: auto;
  }

  .settings-content {
    flex: 1;
  }
}
</style>
