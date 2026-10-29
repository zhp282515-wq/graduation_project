/** 兼容非 HTTPS 部署及 Clipboard API 被禁用的浏览器。 */
export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return
  } catch {
    // 非安全上下文或权限限制时，退回用户点击触发的原生复制命令。
  }

  const focused = document.activeElement
  const selection = document.getSelection()
  const ranges = selection
    ? Array.from({ length: selection.rangeCount }, (_, index) => selection.getRangeAt(index).cloneRange())
    : []
  const field = document.createElement('textarea')
  field.value = text
  field.readOnly = true
  field.style.cssText = 'position:fixed;top:0;left:0;opacity:0;pointer-events:none;'
  document.body.appendChild(field)
  try {
    field.select()
    if (!document.execCommand('copy')) throw new Error('复制失败，请选中代码后手动复制')
  } finally {
    field.remove()
    focused?.focus({ preventScroll: true })
    if (selection) {
      selection.removeAllRanges()
      ranges.forEach((range) => selection.addRange(range))
    }
  }
}
