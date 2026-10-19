/**
 * v-glass-tilt：液态玻璃指针跟随高光
 *
 * 只更新 CSS 变量 --mx / --my（百分比），不做任何布局计算，
 * 所以每帧开销极小；pointerleave 时复位到中心，过渡自然收束。
 */
const handlers = new WeakMap()

function attach(el) {
  if (handlers.has(el)) return

  const onMove = (e) => {
    const r = el.getBoundingClientRect()
    const x = ((e.clientX - r.left) / r.width) * 100
    const y = ((e.clientY - r.top) / r.height) * 100
    el.style.setProperty('--mx', `${x}%`)
    el.style.setProperty('--my', `${y}%`)
  }

  const onLeave = () => {
    el.style.setProperty('--mx', '50%')
    el.style.setProperty('--my', '50%')
  }

  el.addEventListener('pointermove', onMove, { passive: true })
  el.addEventListener('pointerleave', onLeave, { passive: true })
  handlers.set(el, { onMove, onLeave })
}

function detach(el) {
  const h = handlers.get(el)
  if (!h) return
  el.removeEventListener('pointermove', h.onMove)
  el.removeEventListener('pointerleave', h.onLeave)
  handlers.delete(el)
}

export const glassTilt = {
  mounted: attach,
  updated: attach,
  unmounted: detach,
}
