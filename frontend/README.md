# 星野台 · 前端（Vue 3 重构版）

> 江西师范大学校园智能体的新一代前端：白天在「纸本」上问学、整理档案，夜里抬头看「星野」。
> 后端接口、SSE 事件、上传协议与数据库结构全部沿用原实现，前端只重写呈现与交互。

- 仓库内位置：`frontend/`
- 运行时后端：`http://127.0.0.1:8002`（Vite 代理 `/api` 与 `/uploads`）
- 设计文档与验收记录：仓库根目录 `DELIVERY.md`
- 旧界面源码存档：`frontend/.legacy-src/`（仅作对照，不参与构建）

---

## 1. 快速开始

```bash
cd frontend
npm ci            # 或 npm install
npm run dev       # http://127.0.0.1:5173
npm test          # vitest，58 例
npm run build     # 产物在 dist/
npm run preview   # 预览生产构建（http://127.0.0.1:4173）
```

后端需先启动（见仓库 README）。若 5173 被占用，可 `npm run dev -- --port 5180 --strictPort`；
后端地址不是 8002 时用 `JXNU_API=http://host:port npm run dev` 覆盖代理目标。

### Windows 构建注意

本机 `npm run build` 曾因 esbuild 清理大输入临时文件被拒（`remove C:\Users\...\Temp\esbuild-*: Access is denied`）而失败。
把临时目录指到工作区即可：

```powershell
New-Item -ItemType Directory -Force D:\1oveb\毕业设计\.tmp | Out-Null
$env:TEMP = "D:\1oveb\毕业设计\.tmp"; $env:TMP = $env:TEMP
npm run build
```

---

## 2. 信息架构

| 路由 | 名称 | 作用 |
| --- | --- | --- |
| `/inquiry/:sessionId?` | 问学 INQUIRY | 对话：提问、流式回答、工具轨迹、出处、重新生成、停止、图片输入、深思考开关 |
| `/archive/:fileMd5?` | 典藏 ARCHIVE | 知识库：搜索、类型筛选、排序、分页、上传队列、任务状态、分片浏览、删除、同步 |
| `/memory` | 记忆 MEMORY | 长期记忆：查看、行内改写、删除 |
| `/atlas/:chunkId?` | 星野 ATLAS | 知识星图：1,759 个真实分片的星体、星群、星链、语义连线、搜索定位与分片详情 |

全局外壳：左侧 78px 竖排 rail（印章 + 四模式 + 会话 / 主题 / ⌘K）→ 顶部上下文状态栏 → 内容区。
≤900px 时 rail 变底部横条，抽屉与面板改为底部 sheet。

会话不再常驻侧栏，而是全高抽屉「会话档案」（`⌘J` / 顶部按钮打开，按今天 / 昨天 / 本周 / 更早分组）。
命令面板 `⌘K`：新建问学、跳转四个模式、切主题、同步知识库、校园入口 6 条外链、最近会话。

问学扉页是双栏「目录页」：左栏标题 / 说明 / 知识库统计 / 建议问题；右栏「CAMPUS LINKS 校园入口」与「或者直接问」。
校园外链集中在 `src/config/campusLinks.js`（学校官网、教务在线、图书馆、本科招生就业网、研究生院、学生处，均为 `target="_blank" rel="noopener noreferrer"`），
`⌘K` 与扉页复用同一份数据。

---

## 3. 双材质设计语言

两套 token（`src/styles/tokens.css`），同一套组件：

| | 纸本 paper（默认） | 星夜 night |
| --- | --- | --- |
| 底 | `#f2eee4` 纸面 | `#07070b` |
| 面 | `#fbf8f1` | `#0c0d13` |
| 墨 | `#1c1813` | `#ece6d8` |
| 强调 | 朱砂 `#a3352a` | `#e2684c` |
| 线 | `rgba(28,24,19,.13)` | `rgba(237,231,218,.14)` |

- **字体**：展示用 `Instrument Serif`（打包 `@fontsource/instrument-serif`），元数据用 `JetBrains Mono Variable`，
  中文标题走系统宋体栈（`Songti SC / STSong / SimSun`），正文走系统黑体栈。不额外加载中文 webfont。
- **特征元素**：发丝线、四角刻度、mono 编号（`01 / 02`）、仪器式标注（`JXNU · OBSERVATORY`）、朱砂印章。
- **星野强制夜色**：路由 `meta.forceNight` 在 `router.afterEach` 给 `<html>` 打 `data-force-night`，
  离开后自动还原用户选择的主题（`ui.theme` 持久化在 `localStorage: jxnu.theme`）。
- 动效只服务于状态变化（页面过渡、抽屉滑入、流式光标、星体脉冲），`prefers-reduced-motion` 下全部降级。

---

## 4. 目录结构

```
frontend/
├── index.html                 # 首帧前定主题，避免闪白
├── vite.config.js             # /api、/uploads 代理；three 单独切 chunk
├── vitest.config.js
├── public/favicon.svg
├── tests/                     # 58 例 vitest（utils / SSE 解析 / atlas store）
└── src/
    ├── main.js  App.vue  router/index.js
    ├── api/                   # http 封装、SSE 解析、会话 / 对话 / 上传 / 知识库 / 记忆
    ├── stores/                # ui / conversations / library / memory / atlas（Pinia setup store）
    ├── utils/                 # 时间与字节格式、来源归一化、历史配对、Markdown 渲染、工具文案
    ├── composables/confirm.js # Promise 化确认框
    ├── three/starfield.js     # 星图引擎（three.js）
    ├── components/
    │   ├── shell/             # AppRail、SessionLedger、CommandPalette
    │   ├── ui/                # Icon、BaseSheet、ToastStack、ConfirmDialog
    │   └── chat/              # TurnItem、AnswerBlock、RunTrace、SourceStrip、SourceSheet、Composer
    ├── views/                 # InquiryView、ArchiveView、MemoryView、AtlasView
    └── styles/                # tokens / base / layout / markdown
```

状态分层：`api/*` 只做请求与解包；`stores/*` 持有状态与业务流程（发送、重试、轮询、筛选、选星）；
`views/*` 只负责布局与事件绑定；渲染型组件（Composer / AnswerBlock）保持无请求副作用。

---

## 5. 与后端的契约（未改动）

所有请求带 `x-user-id: user_001`（与旧前端一致，开发期身份方案，不是真实鉴权）。

| 用途 | 请求 |
| --- | --- |
| 会话列表 / 新建 / 删除 | `GET/POST /api/sessions`、`DELETE /api/sessions/{id}` |
| 历史消息 | `GET /api/sessions/{id}/messages` |
| 流式对话 | `POST /api/chat` → SSE（`{session_id,text,images,reasoning}`） |
| 重新生成 | `POST /api/sessions/{id}/messages/{message_id}/regenerate` → SSE |
| 图片上传 | `POST /api/upload`（multipart，≤10MB） |
| 记忆 | `GET /api/memories`、`PUT /api/memories/{id}`、`DELETE /api/memories/{id}` |
| 知识库 | `GET /api/knowledge/documents`、`/chunks`、`/jobs/{md5}`、`POST /upload`、`POST /sync`、`DELETE /documents/{md5}` |
| 知识库总览（新增） | `GET /api/knowledge/overview` |
| 星图（新增） | `GET /api/knowledge/starmap`、`/starmap/points`、`/starmap/edges` |

SSE 事件（`api/sse.js` 按 `\n\n` 切帧，逐帧 `JSON.parse`）：

```
run_started   {session_id,user_message_id,operation,message_id,started_at}
reasoning_delta {content}
text_delta    {content}
tool_call     {name,arguments,tool_call_id}
tool_started  {name,tool_call_id}
tool_finished {name,status,tool_call_id,elapsed_ms,sources[]}
done          {final_answer:{content,reasoning,finish_reason,token_usage,total_tokens,elapsed_ms,message_id,reply_to_message_id,sources[]}}
run_failed    {error_type,message,elapsed_ms}
```

前端行为：
- `run_started` 决定本轮是 `send` 还是 `regenerate`，并记录 `message_id`；
- `tool_started` / `tool_finished` 累积为**本轮工具轨迹**（答案内联展示，可折叠）；
- `tool_finished.sources` 与 `done.final_answer.sources` 按 `id` 去重合并；
- 只有 `done` 才把回答视为落库；`run_failed`、断流、用户中止都会显示明确的失败块，且不会伪造回答；
- 停止生成 = `AbortController.abort()`，界面提示「这一段回答没有保存」，刷新后该轮只有提问（与后端不落库行为一致）。

---

## 6. 知识星图（星野）

### 数据来源

- 星体 = Milvus `campus_knowledge` 集合中的**真实分片**，`id` 为分片主键，`file_md5 + chunk_index` 为稳定标识；
- 每批 400 条分页拉取（后端 `POINT_PAGE_DEFAULT=400 / MAX=800`），直到 `next_offset === null`，
  HUD 显示 `loaded / total`，**不做抽样**；
- 文档归属、`chunk_index` 顺序、`section_path`、`page`、`chars` 均为数据库/集合中的真实字段。

### 三类关系严格区分（界面上也写明）

| 关系 | 来源 | 呈现 |
| --- | --- | --- |
| 文档归属 | Milvus `file_md5` + 后端 `documents[]` | 星群光晕、文档筛选、标签 |
| 分片顺序 | 同文档 `chunk_index` 相邻 | 星链线（可开关，默认开） |
| 语义相似 | 后端对分片向量做跨文档 cosine kNN，阈值 `0.75`，最多 900 条 | 紫色连线（默认关，需手动开） |
| 空间位置 | 后端 MDS + 径向压缩 + 星群分离 + 文档内 PCA | 仅用于观看，不代表语义距离 |

算法版本 `starmap-v3`，坐标缓存于 `data/starmap/cache.json`，语料或版本变化自动失效重建。
「关系与坐标说明」面板把这四点原样写给用户，避免把「看起来挨着」误读成「知识相关」。

### 交互

- 拖拽旋转、滚轮缩放、右键平移（OrbitControls，带阻尼）；
- **自动旋转**：默认开启，约 4.56°/s；拖拽 / 缩放 / 悬停 / 点击 / 打开详情时 0.6s 内平滑停住，
  停手 2.2s 后缓入恢复（详情打开期间保持静止）。顶部「自动观测 / 已暂停」可手动开关，
  选择写入 `localStorage: jxnu.atlas.autorotate`；另有星云呼吸、星体闪烁、刻度环自转、
  被悬停星体的亮度起伏与 620ms 的 UI 上浮入场；
- **系统「减少动态效果」**：检测到 `prefers-reduced-motion: reduce` 时默认静止，抬头出现
  「动效已按系统关闭 · 开启」；一键恢复并写 `localStorage: jxnu.atlas.motion = on`，
  同时以 `<html data-motion="on">` 覆盖全局 CSS 降级；
- **精确拾取**：把指针射线换算到世界空间，按“射线到星体中心的垂直距离 ≤ 视口 11px”筛选候选，
  再做屏幕投影比较（替代二维距离近似）；单击判定 <6px / <700ms，触屏 tap 同一套逻辑；
- **悬停预览**：指针停留即出分片卡片（文档、`#序号`、章节、正文摘要、字数）；星体本身只做
  柔和的亮度 / 尺寸变化，没有圆环与光晕膨胀——悬停与选中共用同一个 `aEmphasis` 顶点属性做过渡；
- **文档名（分类名称）可隐藏**：抬头「文档名」开关写 `localStorage: jxnu.atlas.labels`；
  桌面默认显示、窄屏默认隐藏。标签是纯文字 + 柔影（无胶囊边框），字号 10–12.6px、
  不透明度 0.5–1.0 随该文档分片数变化；标签 `pointer-events: none`，只作注记，不会挡住星体拾取；
- 点击星体 / 搜索结果 / 视口内标签 → 选中并平滑飞向该星（相机从当前机位直接飞，不重置），
  详情面板用以被点星体屏幕坐标换算的百分比原点做 `clip-path` 圆形展开（原点钳制在 4%–96%，
  不再出现弧形裁切）；关闭后机位还原到打开前的距离；
- 右侧详情给出**真实分片正文**、文档名、类型、分片序号、字数、章节、页码（仅 PDF）、指纹；
- 详情可直接「在典藏打开」（`/archive/{md5}?chunk=n`）、「就此提问」（带 `?seed=` 回问学）、复制；
- 搜索在已加载的全部分片上做子串匹配（正文 + 章节 + 文档名），命中数分母是全库分片数，
  支持 `↑/↓` 或回车在命中之间循环定位；
- 文档 chips / 类型 chips 过滤只改颜色与透明度，不重排几何；筛选结果与星体一一对应；
- 图层开关：星链、语义连线；`Esc` 清选并关闭详情，`/` 聚焦搜索框；`Tab` 可聚焦三维视图
  （`role=application`，聚焦时中央出现 1.1s 涟漪环），`←/→` 在命中结果间切换；
- 移动端面板默认收起，星图可单指旋转、双指缩放；抬头按钮收为纯图标，文档标签默认隐藏并可一键打开。

### 性能

- 单 `Points` 承载全部星体（自定义 `ShaderMaterial`，逐点尺寸 / 颜色 / 闪烁相位），无 DOM 节点开销；
- 文档标签是屏幕空间 DOM 注记（每 120ms 更新一次投影坐标，重叠按分片数优先保留，新标签 420ms 淡入），
  比 sprite 方案更可控，也不会随缩放变大；
- 相机与自动旋转在渲染循环里用 `dt` 驱动（`dt` 上限 0.06s，`controls.update(dt)`），
  切标签页回来不会突跳；页面隐藏时 `visibilitychange` 停掉 rAF 与自动旋转，恢复后再继续；
- `hardwareConcurrency ≤ 4` 或 `deviceMemory ≤ 4` 自动降 `pixelRatio` 至 1.35；
  连续 3 次采样低于 32fps 时再降到 1.15；
- 卸载时释放几何、材质、贴图、renderer 与全部事件监听（`dispose()`）。

实测（本机 Chrome，1,759 星 / 54 文档 / 900 条语义线）：数据就绪 0.64s，headless rAF 240fps（旋转中同样 240），
JS 堆 21MB；关闭详情后相机距离精确还原（98.42 → 98.42）。详见 `DELIVERY.md`「性能与兼容性」。

---

## 7. 测试

```bash
cd frontend
npm test
```

6 个文件、58 例：
- `format.test.js` 时间 / 字节 / 时长 / 标题截断 / Markdown 纯文本化；
- `history.test.js` `reply_to_message_id` 配对、孤儿回答、图片路径、标题推导；
- `citations.test.js` 来源归一化、按文档分组、元信息文案；
- `sse.test.js` 跨 chunk 切帧、多事件一帧、残帧、注释行、`[DONE]` 容错；
- `markdown.test.js` 代码块外壳与语言标签、表格包裹、外链 `target`、`html:false`；
- `atlas-store.test.js` 筛选求交、搜索命中、星链配对、`selectByStarKey`、色相分配。

真实链路（SSE、上传、删除、记忆、图片、中止、主题、移动端）用 Playwright 对真实后端验收，
记录见 `DELIVERY.md`「联调验证记录」。

---

## 8. 可访问性与兜底

- 所有图标按钮有 `aria-label` / `title`，抽屉与 sheet 有焦点陷阱、`Esc` 关闭、关闭后焦点回收；
- 对比度：纸本正文 `#1c1813` / `#f2eee4`，夜色 `#ece6d8` / `#07070b`，弱化文字不低于 3:1（仅元数据）；
- 键盘：`⌘K` 命令面板、`⌘J` 会话档案、`↑↓` 选择、`⏎` 打开、`Esc` 逐层关闭、`/` 聚焦星图搜索；
- 空态 / 加载 / 失败 / 处理中 / 长文本截断都有专门样式；星图与典藏失败可原位重试；
- `prefers-reduced-motion: reduce` 时关闭位移与呼吸动效。
