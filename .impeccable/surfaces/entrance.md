# 饭饭产品入口

模式：Persuade + Operate。受众为准备注册或登录的校园用户；首要行动为进入自己的问学空间。

## Direction contract

THESIS：从校园一问走到知识星图。身份表单与品牌叙事共同构成首屏，随后沿问题、回答、来源与知识关联展开纵向体验。

OWN-WORLD：暖白、深墨与低饱和森林绿；清晰的编辑式排版连接校园问答与知识空间。入口深绿主叙事与浅色身份区形成对照，星图保留深色空间。校徽与饭饭署名对齐；不添加虚构校园照片、紫蓝渐变或无意义粒子。

STORY：首页先完成登录或注册；向下用标注的示例理解多轮问答、引用原文和分片关联，再回到进入问学的行动。

FIRST VIEWPORT：1440宽桌面用大面积深绿叙事区与浅色表单分栏；左侧大标题、问到来源的线索及低对比中文字形，右侧直接输入。390宽先显示精简叙事，再完整呈现登录操作，保留自然滚动。

FORM：用户确认人文与空间结合、明亮工作区和代码原生校园视觉；代码直接实现，无新增位图。seed:8069ffe982551e1b

FINISH：unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Evidence

验收截图在 `_devtools/auth-entry-20261026/`，含 desktop、desktop-first、mobile、mobile-first、mobile-register 和 admin-users。使用既有 SVG 校徽，无新增交付位图。

约束：公开示例与正式业务 Store 隔离；先恢复身份再进入业务；入口不加载完整 Three.js；保留原生滚轮、键盘操作和减少动态效果支持。
