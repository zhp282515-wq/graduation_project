import { describe, expect, it } from 'vitest'
import { CODE_LANGUAGES, renderInline, renderMarkdown } from '../src/utils/markdown'

describe('renderMarkdown', () => {
  it('renders headings, lists and emphasis', () => {
    const html = renderMarkdown('# 奖学金\n\n- 国家奖学金 8000 元\n- 励志奖学金 5000 元\n\n**注意**：以当年通知为准。')
    expect(html).toContain('<h1>奖学金</h1>')
    expect(html).toContain('<li>国家奖学金 8000 元</li>')
    expect(html).toContain('<strong>注意</strong>')
  })

  it('wraps fenced code with a copy affordance and language label', () => {
    const html = renderMarkdown('```python\nprint("hello")\n```')
    expect(html).toContain('class="code-block"')
    expect(html).toContain('data-lang="PYTHON"')
    expect(html).toContain('data-copy-code')
    expect(html).toContain('class="hljs')
    expect(html).toContain('print')
  })

  it('renders highlighting tags without showing their HTML as code', () => {
    const html = renderMarkdown('```python\ndef greet(name):\n    return "你好"\n```')
    expect(html).toContain('<span class="hljs-keyword">def</span>')
    expect(html).not.toContain('&lt;span')
    expect(html).toContain('    ')
  })

  it('keeps HTML examples inert and preserves their original text', () => {
    const html = renderMarkdown('```html\n<script>alert("x")</script>\n<p>A & B</p>\n```')
    expect(html).not.toContain('<script>')
    expect(html).not.toContain('<p>A')
    const code = html.match(/<code[^>]*>([\s\S]*?)<\/code>/)[1]
    const text = code.replace(/<[^>]*>/g, '')
      .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"').replace(/&amp;/g, '&')
    expect(text).toBe('<script>alert("x")</script>\n<p>A & B</p>\n')
  })

  it('renders code while its closing fence has not arrived in the stream', () => {
    const html = renderMarkdown('```js\nconst value = "还在生成"\n')
    expect(html).toContain('data-copy-code')
    expect(html).toContain('<span class="hljs-keyword">const</span>')
    expect(html).toContain('还在生成')
  })

  it('gives indented code the same copyable code frame', () => {
    const html = renderMarkdown('示例：\n\n    first()\n    second()')
    expect(html).toContain('class="code-block"')
    expect(html).toContain('data-copy-code')
    expect(html).toContain('first()\nsecond()\n')
  })

  it('keeps unknown languages readable without a label guess', () => {
    const html = renderMarkdown('```\n随便写点什么\n```')
    expect(html).toContain('code-block')
    expect(html).toContain('随便写点什么')
  })

  it('escapes unsupported code and untrusted language labels', () => {
    const html = renderMarkdown('```unknown"onclick="alert(1)\n<div>A & B</div>\n```')
    expect(html).toContain('&lt;div&gt;A &amp; B&lt;/div&gt;')
    expect(html).not.toContain('onclick="')
  })

  it('wraps tables so wide knowledge tables can scroll', () => {
    const html = renderMarkdown('| 单位 | 电话 |\n| --- | --- |\n| 图书馆 | 88120630 |')
    expect(html).toContain('class="table-wrap"')
    expect(html).toContain('<td>88120630</td>')
  })

  it('opens external links in a new tab and keeps images lazy', () => {
    const html = renderMarkdown('[校园网](https://www.jxnu.edu.cn)\n\n![图](https://example.com/a.png)')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('rel="noopener noreferrer"')
    expect(html).toContain('loading="lazy"')
  })

  it('escapes raw html instead of injecting it', () => {
    const html = renderMarkdown('<script>alert(1)</script>')
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
  })

  it('handles empty input', () => {
    expect(renderMarkdown('')).toBe('')
    expect(renderMarkdown(null)).toBe('')
  })
})

describe('renderInline', () => {
  it('renders a single line of markdown without a paragraph wrapper', () => {
    expect(renderInline('**粗体**')).toContain('<strong>粗体</strong>')
    expect(renderInline('**粗体**')).not.toContain('<p>')
  })
})

describe('CODE_LANGUAGES', () => {
  it('registers the languages the corpus and agent actually emit', () => {
    expect(CODE_LANGUAGES).toEqual(
      expect.arrayContaining(['javascript', 'typescript', 'python', 'bash', 'json', 'sql', 'yaml']),
    )
  })
})
