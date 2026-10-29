import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

/**
 * 四个空间各有自己的地址，刷新后仍停在原处（旧版只用一个 ref 切视图，刷新即丢失）。
 * /atlas 与 /archive 的二级参数用于深链：星图定位到某颗星、知识库定位到某份文档。
 */
const routes = [
  { path: '/', name: 'home', component: () => import('../views/EntranceView.vue'), meta: { public: true } },
  { path: '/login', name: 'login', component: () => import('../views/EntranceView.vue'), meta: { public: true } },
  { path: '/register', name: 'register', component: () => import('../views/EntranceView.vue'), meta: { public: true } },
  { path: '/settings', name: 'settings', component: () => import('../views/SettingsView.vue'), meta: { mode: 'settings', title: '设置' } },
  { path: '/password', name: 'password', component: () => import('../views/SettingsView.vue'), meta: { mode: 'settings', title: '修改密码' } },
  { path: '/settings/model', name: 'model-settings', component: () => import('../views/SettingsView.vue'), meta: { mode: 'settings', title: '模型配置', admin: true } },
  { path: '/admin/users', component: () => import('../views/AdminUsersView.vue'), meta: { mode: 'users', title: '账号管理', admin: true } },
  { path: '/admin/search', component: () => import('../views/AdminSearchView.vue'), meta: { mode: 'search', title: '知识检索', admin: true } },
  {
    path: '/inquiry/:sessionId?',
    name: 'inquiry',
    component: () => import('../views/InquiryView.vue'),
    meta: { mode: 'inquiry', title: '问学' },
  },
  {
    path: '/notes/:noteId?',
    name: 'notes',
    component: () => import('../views/NotesView.vue'),
    meta: { mode: 'notes', title: '笔记' },
  },
  {
    path: '/archive/:fileMd5?',
    name: 'archive',
    component: () => import('../views/ArchiveView.vue'),
    meta: { mode: 'archive', title: '典藏' },
  },
  {
    path: '/memory',
    name: 'memory',
    component: () => import('../views/SettingsView.vue'),
    meta: { mode: 'settings', title: '长期记忆' },
  },
  {
    path: '/atlas/:chunkId?',
    name: 'atlas',
    component: () => import('../views/AtlasView.vue'),
    meta: { mode: 'atlas', title: '星野', forceNight: true },
  },
  { path: '/:pathMatch(.*)*', redirect: '/inquiry' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, saved) {
    if (to.meta.public && from.meta.public && to.path !== from.path) return false
    if (saved) return saved
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  try { await auth.restore() } catch { return to.meta.public ? true : { path: '/login', query: { redirect: to.fullPath } } }
  if (!to.meta.public && !auth.user) return { path: '/login', query: { redirect: to.fullPath } }
  if (auth.user?.must_change_password && to.path !== '/password') return '/password'
  if (to.meta.admin && !auth.isAdmin) return '/inquiry'
  if (auth.user && ['/login', '/register'].includes(to.path)) return '/inquiry'
})

/** 星野只在停留期间关灯，离开后回到用户原本选择的材质。 */
router.afterEach((to) => {
  document.title = '饭饭'
  const root = document.documentElement
  if (to.meta?.forceNight) root.dataset.forceNight = 'on'
  else delete root.dataset.forceNight
})

export default router
