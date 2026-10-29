---
name: "饭饭 · 校园智能体"
description: "以白色阅读空间、黑灰夜色与校徽细节，连接校园问题、来源和知识星图。"
colors:
  paper-bg: "#fafafa"
  paper-bg-deep: "#f1f1f1"
  paper-surface: "#ffffff"
  paper-surface-2: "#f5f5f5"
  paper-surface-3: "#eaeaea"
  paper-ink: "#202020"
  paper-ink-2: "#444444"
  paper-ink-3: "#5c5c5c"
  paper-ink-4: "#6c6c6c"
  paper-line: "rgba(32, 32, 32, 0.14)"
  paper-line-strong: "rgba(32, 32, 32, 0.29)"
  paper-accent: "#303030"
  paper-accent-hover: "#111111"
  paper-on-accent: "#ffffff"
  paper-accent-soft: "rgba(48, 48, 48, 0.08)"
  paper-ok: "#37624a"
  paper-warn: "#85642a"
  paper-error: "#97281f"
  night-bg: "#111212"
  night-bg-deep: "#090a0a"
  night-surface: "#1b1c1c"
  night-surface-2: "#252626"
  night-surface-3: "#303131"
  night-ink: "#f1f1ef"
  night-ink-2: "#d1d2d0"
  night-ink-3: "#b8bab8"
  night-ink-4: "#aaadaa"
  night-line: "rgba(240, 240, 235, 0.14)"
  night-line-strong: "rgba(240, 240, 235, 0.3)"
  night-accent: "#d8ded8"
  night-accent-hover: "#f0f3ef"
  night-on-accent: "#181a18"
  entry-paper: "#fafafa"
  entry-sheet: "#ffffff"
  entry-ink: "#202020"
  entry-muted: "#5c5c5c"
  entry-accent: "#303030"
  entry-accent-hover: "#111111"
  entry-on-accent: "#ffffff"
  entry-line: "rgba(32, 32, 32, .16)"
  entry-rule: "rgba(32, 32, 32, .36)"
  entry-selection: "#e2e2e2"
  entry-hero: "#f5f5f5"
  entry-answer: "#f5f5f5"
  entry-night: "#151616"
  entry-night-text: "#f2f2ef"
  entry-night-muted: "#c2c4c1"
  entry-orbit: "rgba(220, 224, 218, .23)"
  entry-graph-line: "#999999"
  entry-star-accent: "#dfaa79"
typography:
  display:
    fontFamily: '"Songti SC", "Source Han Serif SC", "Noto Serif SC", "SimSun", serif'
    fontSize: "clamp(45px, 5.1vw, 78px)"
    fontWeight: 500
    lineHeight: 1.32
    letterSpacing: "-0.035em"
  headline:
    fontFamily: '"Songti SC", "Source Han Serif SC", "Noto Serif SC", "SimSun", serif'
    fontSize: "clamp(38px, 4.1vw, 62px)"
    fontWeight: 500
    lineHeight: 1.32
    letterSpacing: "-0.025em"
  body:
    fontFamily: '"Inter", "SF Pro Text", -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei UI", "Noto Sans SC", sans-serif'
    fontSize: "14px"
  entry-body:
    fontFamily: '"Inter", "SF Pro Text", -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei UI", "Noto Sans SC", sans-serif'
    fontSize: "16px"
    lineHeight: 1.75
  mono:
    fontFamily: '"JetBrains Mono Variable", "JetBrains Mono", ui-monospace, "SFMono-Regular", Consolas, monospace'
rounded:
  xs: "5px"
  sm: "9px"
  md: "12px"
  lg: "18px"
  full: "999px"
components:
  workspace-button-accent:
    backgroundColor: "{colors.paper-accent}"
    textColor: "{colors.paper-on-accent}"
    rounded: "{rounded.sm}"
    height: "34px"
    padding: "0 14px"
  workspace-panel:
    backgroundColor: "{colors.paper-surface}"
    rounded: "{rounded.md}"
  entry-submit:
    backgroundColor: "{colors.entry-accent}"
    textColor: "{colors.entry-on-accent}"
    rounded: "{rounded.md}"
    padding: "13px 20px"
    width: "100%"
  entry-submit-hover:
    backgroundColor: "{colors.entry-accent-hover}"
---

# Design System: 饭饭 · 校园智能体

## Overview

**Creative North Star: "明亮阅读室与黑色知识空间"**

以白色为主的阅读空间和中性黑灰文字构成清晰的日常工作区，深灰标记操作与选择。公开入口将校徽融入品牌构图，以浅灰圆角叙事区和白色身份区形成层次；知识星图转入黑灰空间。简洁排版、细线与轻柔转场共同建立质感。

**Key Characteristics:**

- 白色层次、中性黑灰正文与克制的深灰强调。
- 中文宋体标题配无衬线正文，等宽字体服务编号和辅助信息。
- 工作区使用明暗语义主题；暗色以黑灰为基础，星图保留独立空间。
- 校徽、圆角、细线与色面界定结构，来源纸页和知识关系承担内容表达。

依据：`frontend/src/styles/tokens.css`、`base.css`、`layout.css` 和 `frontend/src/views/EntranceView.vue`。CSS 变量 `--entry-red` 的历史名称仍保留，但当前值为深灰。

## Colors

### Primary

- **中性深灰**：浅色工作区的主要动作、选中和焦点；夜间使用浅灰强调。入口的同名历史变量用于按钮及强调。

### Neutral

- **白色纸面与纸页**：背景与分层 surface 承载阅读和操作；入口叙事区与回答示例使用浅灰纸面。
- **深墨与次级墨**：按正文、辅助信息和边界区分层次；入口占位文字使用与辅助文字相同的颜色。
- **黑灰星夜**：入口星图与工作区 night 主题各有独立色组；暖金标记入口星图的选中节点。
- **语义状态色**：成功、警告和错误用于实际状态；引用展开时使用浅灰选文色。

**The Theme Boundary Rule.** 工作区使用随主题变化的语义变量；公开入口使用独立的 `--entry-*` 变量，不受工作区主题或星图强制夜色影响。

## Typography

中文展示与标题使用宋体栈，正文和控件使用无衬线栈；编号、键帽及辅助信息可用等宽栈。实际字体均遵循代码中的回退，不假设首选字体已安装。

入口首屏标题与章节标题的桌面尺度见 frontmatter；移动首屏标题为 `clamp(33px, 8.5vw, 48px)`，章节标题为 34px。工作区字号阶梯从 10px 至 64px，正文基准 14px；入口正文基准 16px，字段输入为 16px。

## Layout

工作区为固定高度外壳：侧轨 78px，内容最大宽度 1280px，阅读宽度 720px；水平留白为 `clamp(18px, 3vw, 44px)`。900px 及以下侧轨转为底部导航；640px 及以下抽屉转为底部 sheet。

入口自然纵向滚动。桌面首屏的浅色圆角叙事区与至少 380px 的白色身份区并列；1100px 以下身份区最小宽度 340px，760px 以下上下排列，先叙事后表单。其余章节桌面内容最大宽度 1328px，760px 以下两侧各留 20px，章节与图谱改为单列。入口构图属于该表面，不应直接套用到业务页面。

## Elevation & Depth

工作区主要通过背景色差、1px 边线和小幅阴影区分层级；sheet 和浮层使用更明显的阴影，明暗主题各自定义。纸面噪点当前透明度为零。入口回答预览为浅灰平面，来源纸页使用轻投影和轻微旋转；星图通过暗底、轨道和连线表达关系。

首次进入时，入口首屏由上向下依次渐入；章节进入使用淡入和有限位移，登录与注册切换使用柔和过渡。星图卫星仅在可见且页面未隐藏时缓慢呼吸；滚动漂移最大 28px。页面切换和控件状态使用短暂、连贯的动效。减少动态效果时关闭或缩短过渡与位移，保证内容和操作立即可用。

**The Content Depth Rule.** 纸页层叠表达来源，轨道和连线表达知识关系；普通容器保持清晰、克制。

## Shapes

工作区圆角从 5px、9px、12px 至 18px，状态 chip 使用胶囊形。入口字段与主要按钮使用 12px 圆角，叙事区、回答预览和来源纸页使用更舒展的圆角；来源纸页与来源条轻微倾斜，展开时来源条回正。

## Components

### Buttons

工作区默认按钮高 34px、左右内边距 14px，提供描边、墨色实心、深灰强调、quiet 和 danger 状态；小号高 27px。悬停改变表面或边线，按下位移 1px，禁用时降低透明度。入口主按钮全宽、最小高 52px，悬停加深并使箭头右移；提交中显示状态并禁用。

### Chips and panels

工作区 chip 高 22px、左右内边距 9px，细线胶囊承载辅助状态；强调、成功、警告和错误样式对应真实状态。panel 使用 surface、细线和 12px 圆角。

### Inputs and navigation

入口字段保留可见标签和圆角边框，焦点时以深灰边框和柔和外环反馈。工作区保留侧轨及移动底栏；入口桌面章节锚点在移动端隐藏，登录与注册选择使用按钮和滑动底线。

### Knowledge graph and citation

入口示例图谱以实线表示文档顺序、虚线表示语义关联，选中节点用暖金强调；移动端另提供文字节点按钮。来源展开时，原文高亮且来源条回正。入口内容标记为示例，不应描述为实时回答。

## Do's and Don'ts

### Do:

- **Do** 先复用现有语义变量、字体栈、细线和组件状态。
- **Do** 保留入口固定色与工作区明暗主题的边界。
- **Do** 用来源和知识关系决定视觉强调，并尊重减少动态效果。
- **Do** 在窄屏保持可读标签、键盘焦点和星图文字选择控件。

### Don't:

- **Don't** 将入口局部深色星图、纸页旋转或首屏构图套用于所有业务页面。
- **Don't** 添加虚构统计、学校官方背书或把示例写成实时校园回答。
- **Don't** 用占位文字替代可见字段标签，或把知识空间描述成真实天体。
