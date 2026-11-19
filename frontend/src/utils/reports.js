const number = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 })
const time = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
})
const clock = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
})
export const formatCount = value => value == null ? '—' : number.format(value)
export const formatPercent = value => value == null ? '—' : number.format(value) + '%'
export const shanghaiTime = value => value ? time.format(new Date(value)) : '—'
export const shanghaiClock = value => value ? clock.format(new Date(value)) : '—'
