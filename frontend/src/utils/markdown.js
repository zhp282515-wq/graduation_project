import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'

/**
 * Markdown 渲染器。
 *
 * html: false 是关键 —— AI 输出虽然是可信来源，但内容里可能出现用户
 * 粘贴的原文。禁止原始 HTML 可以彻底避免注入。
 */
const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(code, { language: lang }).value}</code></pre>`
      } catch { /* 回退到转义 */ }
    }
    return `<pre class="hljs"><code>${md.utils.escapeHtml(code)}</code></pre>`
  },
})

// 所有外链在新标签打开
const defaultLinkOpen =
  md.renderer.rules.link_open ||
  ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options))

md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen(tokens, idx, options, env, self)
}

export function renderMarkdown(text) {
  if (!text) return ''
  return md.render(text)
}
