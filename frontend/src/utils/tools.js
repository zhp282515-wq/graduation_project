/**
 * 工具调用的中文名。后端 tool_started / tool_finished 里的 name 是 Agent 注册的真实工具名，
 * 这里只做显示层映射，未收录的名字原样展示，绝不猜测。
 */
const TOOL_META = {
  knowledge_search: { label: '知识库检索', hint: '在校园知识库中召回相关分片' },
  web_search: { label: '网页检索', hint: '联网查找公开信息' },
  weather: { label: '天气查询', hint: '查询校园所在地天气' },
  get_weather: { label: '天气查询', hint: '查询校园所在地天气' },
  academic_calendar: { label: '校历查询', hint: '读取校历与学期安排' },
  calendar: { label: '校历查询', hint: '读取校历与学期安排' },
}

export function toolLabel(name) {
  return TOOL_META[name]?.label || name || '工具'
}

export function toolHint(name) {
  return TOOL_META[name]?.hint || ''
}

function parseArgs(args) {
  if (!args) return null
  if (typeof args === 'object') return args
  try {
    return JSON.parse(args)
  } catch {
    return null
  }
}

/** 把调用参数压成一行，方便在轨迹里扫一眼就知道这次查了什么。 */
export function toolArgsSummary(name, args) {
  const parsed = parseArgs(args)
  if (!parsed || typeof parsed !== 'object') {
    return typeof args === 'string' ? args.slice(0, 80) : ''
  }
  const preferred = parsed.query || parsed.q || parsed.keyword || parsed.city || parsed.date
  if (typeof preferred === 'string' && preferred.trim()) return preferred.trim()
  const first = Object.entries(parsed).find(([, value]) => typeof value === 'string' && value.trim())
  return first ? `${first[0]}: ${first[1]}`.slice(0, 80) : ''
}

export const STATUS_LABEL = {
  pending: '等待',
  running: '进行中',
  completed: '完成',
  failed: '失败',
  skipped: '跳过',
}
