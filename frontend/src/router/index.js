import { createRouter, createWebHistory } from 'vue-router'

/**
 * 四个空间各有自己的地址，刷新后仍停在原处（旧版只用一个 ref 切视图，刷新即丢失）。
 * /atlas 与 /archive 的二级参数用于深链：星图定位到某颗星、知识库定位到某份文档。
 */
const routes = [
  { path: '/', redirect: '/inquiry' },
  {
    path: '/inquiry/:sessionId?',
    name: 'inquiry',
    component: () => import('../views/InquiryView.vue'),
    meta: { mode: 'inquiry', title: '问学' },
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
    component: () => import('../views/MemoryView.vue'),
    meta: { mode: 'memory', title: '记忆' },
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
    if (saved) return saved
    return { top: 0 }
  },
})

/** 星野只在停留期间关灯，离开后回到用户原本选择的材质。 */
router.afterEach((to) => {
  const root = document.documentElement
  if (to.meta?.forceNight) root.dataset.forceNight = 'on'
  else delete root.dataset.forceNight
})

export default router
