import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import c from 'highlight.js/lib/languages/c'
import cpp from 'highlight.js/lib/languages/cpp'
import css from 'highlight.js/lib/languages/css'
import go from 'highlight.js/lib/languages/go'
import java from 'highlight.js/lib/languages/java'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import python from 'highlight.js/lib/languages/python'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'

const LANGUAGES = {
  bash,
  c,
  cpp,
  css,
  go,
  java,
  javascript,
  json,
  markdown,
  python,
  sql,
  typescript,
  xml,
  yaml,
}

const ALIASES = {
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  js: 'javascript',
  jsx: 'javascript',
  mjs: 'javascript',
  ts: 'typescript',
  tsx: 'typescript',
  py: 'python',
  yml: 'yaml',
  html: 'xml',
  vue: 'xml',
  golang: 'go',
  'c++': 'cpp',
}

for (const [name, definition] of Object.entries(LANGUAGES)) {
  hljs.registerLanguage(name, definition)
}

export const CODE_LANGUAGES = Object.keys(LANGUAGES)

function resolveLanguage(raw) {
  const key = String(raw || '').trim().toLowerCase()
  if (!key) return ''
  const name = ALIASES[key] || key
  return hljs.getLanguage(name) ? name : ''
}

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  typographer: false,
  highlight(code, language) {
    const name = resolveLanguage(language)
    if (!name) return ''
    try {
      return hljs.highlight(code, { language: name, ignoreIllegals: true }).value
    } catch {
      return ''
    }
  },
})

md.renderer.rules.fence = (tokens, idx) => {
  const token = tokens[idx]
  const info = token.info ? md.utils.unescapeAll(token.info).trim() : ''
  const declared = info.split(/\s+/)[0] || ''
  const name = resolveLanguage(declared)
  const highlighted = name
    ? md.utils.escapeHtml(hljs.highlight(token.content, { language: name, ignoreIllegals: true }).value)
    : md.utils.escapeHtml(token.content)
  const label = (declared || 'text').toUpperCase()
  const langClass = name ? ` language-${name}` : ''
  return (
    `<div class="code-block" data-lang="${md.utils.escapeHtml(label)}">` +
    '<div class="code-head">' +
    `<span class="code-lang">${md.utils.escapeHtml(label)}</span>` +
    '<button type="button" class="code-copy" data-copy-code>复制</button>' +
    '</div>' +
    `<pre class="code-body"><code class="hljs${langClass}">${highlighted}</code></pre>` +
    '</div>'
  )
}

md.renderer.rules.table_open = () => '<div class="table-wrap"><table>'
md.renderer.rules.table_close = () => '</table></div>'

const defaultLinkOpen =
  md.renderer.rules.link_open ||
  ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options))

md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  const token = tokens[idx]
  const href = token.attrGet('href') || ''
  if (/^https?:/i.test(href)) {
    token.attrSet('target', '_blank')
    token.attrSet('rel', 'noopener noreferrer')
  }
  return defaultLinkOpen(tokens, idx, options, env, self)
}

const defaultImage =
  md.renderer.rules.image ||
  ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options))

md.renderer.rules.image = (tokens, idx, options, env, self) => {
  const token = tokens[idx]
  token.attrSet('loading', 'lazy')
  token.attrSet('decoding', 'async')
  token.attrJoin('class', 'md-image')
  return defaultImage(tokens, idx, options, env, self)
}

export function renderMarkdown(text) {
  const source = String(text ?? '')
  if (!source.trim()) return ''
  try {
    return md.render(source)
  } catch (error) {
    // 渲染失败时退回纯文本，界面上宁可少排版也不能整段消失。
    return `<p>${md.utils.escapeHtml(source)}</p>`
  }
}

export function renderInline(text) {
  return md.renderInline(String(text ?? ''))
}

export { md }
