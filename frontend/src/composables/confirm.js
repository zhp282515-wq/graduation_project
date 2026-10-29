import { reactive, readonly } from 'vue'

/**
 * 全局确认框。旧版是组件内自绘 modal，换页就消失；这里做成一个可 await 的服务，
 * 任何地方都能 `if (await confirm({...}))`。
 */
const state = reactive({
  open: false,
  title: '',
  body: '',
  detail: '',
  confirmText: '确认',
  cancelText: '取消',
  danger: false,
  requireText: '',
  typed: '',
  resolve: null,
})

export function useConfirm() {
  return { state: readonly(state), confirm, settle, setTyped }
}

export function setTyped(value) {
  state.typed = String(value ?? '')
}

export function confirm(options = {}) {
  return new Promise((resolve) => {
    // 前一对话框还没结束就让位给新的，避免 resolve 泄漏。
    if (state.resolve) state.resolve(false)
    state.open = true
    state.title = options.title || '请确认'
    state.body = options.body || options.message || ''
    state.detail = options.detail || ''
    state.confirmText = options.confirmText || '确认'
    state.cancelText = options.cancelText || '取消'
    // 两种写法都认：danger: true 或 tone: 'danger'。
    state.danger = Boolean(options.danger) || options.tone === 'danger'
    // 高危操作（例如注销账号）要求把名字打一遍，才算二次确认。
    state.requireText = options.requireText || ''
    state.typed = ''
    state.resolve = resolve
  })
}

export function settle(value) {
  if (state.resolve) {
    const resolve = state.resolve
    state.resolve = null
    resolve(value)
  }
  state.open = false
}
