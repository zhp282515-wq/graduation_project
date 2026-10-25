# 交付报告 · 星野台 JXNU OBSERVATORY

> 江西师范大学校园智能体 · Vue 3 前端全面重构 + 知识星图
> 对应任务书：校园智能体问答系统前端全面重构与知识星图开发

---

## 0. 结论与验证状态

前端已由单文件 `App.vue`（2901 行，Element Plus + 液态玻璃）重建为 Vue 3 + Router + Pinia 的四视图应用；后端保持原有 HTTP / SSE 契约不变，仅新增 4 个只读接口与 1 个仓储聚合方法。旧的会话、知识库（54 篇 / 1759 分片）、长期记忆数据均原地可用，没有清库、没有迁移。

| 验收项 | 状态 | 证据 |
| --- | --- | --- |
| 原有功能保留 | 通过（逐项见 §3） | 真实后端联调截图 + 代码对照 |
| 文字可读性（AA） | 通过（§5.7，纸本/夜色两套 + 星图叠层） | `_devtools/contrast.py` 实测 |
| 星图交互（自动旋转/精确拾取/镜头连续性/后台暂停） | 通过（§5.4、§9） | Playwright 坐标级验证 + 逐帧截图 |
| 系统「减少动态效果」下的可发现与可恢复 | 通过：默认静止 + 抬头提示，一键恢复（实测 autoSpeed 0 → 0.81） | `motion-muted.png` / `motion-enabled.png` |
| 前后端真实交互 | 通过 | §6 联调记录，全部走 8002 真实服务与真实模型 |
| 无 Mock / 演示数据 | 通过 | 所有列表、分片、来源、记忆均来自数据库 |
| 知识星图（真实分片映射） | 通过 | 1759/1759 星体、54 文档、坐标可追溯 |
| 构建 | 通过 | `✓ built in 1.18s`，131 modules |
| 单元测试 | 通过 | 后端 79 例、前端 58 例 |
| 桌面 / 移动端 | 通过 | 1440×900 与 390×844 实拍 |
| 主题（纸本 / 星夜） | 通过 | 星野强制夜色，离开还原 |
| 性能 | 通过 | 星图 ready 0.64 s，headless 240 fps，堆 21 MB |
| 未能验证的项 | 见 §11 | 例如真实多用户鉴权、跨标签并发写、低端 GPU 真机 |

---

## 1. 范围与约束

- 只重构 `frontend/`，后端只做「最小必要、向后兼容」扩展（新增只读接口 + 仓储聚合 + 分片迭代器）。
- 没有删除任何业务表、没有重建 Milvus 集合、没有改动 Agent 的提示词、工具行为、路由或落库语义。
- 演示截图全部来自真实服务：模型为 `qwen3.8-flash`，知识库为容器内 Milvus 中真实的 54 篇文档。
- 本机环境：Windows / Node 24 / conda 环境 `Graduation-Project`（Python 3.13）/ PostgreSQL 16 / Milvus 2.5（Docker）。

---

## 2. 产品与设计

### 2.1 命名与叙事

产品名 **星野台 / JXNU OBSERVATORY**。白天在纸本上问学与整理档案，夜里抬头看星野——知识星图就是校园知识库的夜空。四个视图对应四件事：

| 路由 | 视图 | 说明 |
| --- | --- | --- |
| `/inquiry/:sessionId?` | 问学 INQUIRY | 与 Agent 对话、看工具轨迹与出处 |
| `/archive/:fileMd5?` | 典藏 ARCHIVE | 文档、分片、上传与入库队列 |
| `/memory` | 记忆 MEMORY | 长期记忆的查看、改写、删除 |
| `/atlas/:chunkId?` | 星野 ATLAS | 知识星图 |

### 2.2 信息架构（与旧版的关键差别）

旧版是「左会话栏 + 中聊天 + 右快捷入口/进展」的固定五列，换页靠 `currentView`，刷新即丢失上下文，且没有移动端布局。新版：

- 左侧 78 px 竖排 rail：朱砂方印「师」、竖排「星野台」、四个模式、会话档案入口、主题切换、⌘K。
- 会话历史不再是常驻侧栏，而是全高「会话档案」抽屉（今天 / 昨天 / 本周 / 更早，可搜索、↑↓ 选择、⏎ 打开）。
- 顶部 60 px 上下文栏：当前会话标题或视图统计 + 视图动作。
- 对话改成编辑式排版：92 px 走栏（问 01 / 时间 / 进行中）+ 720 px 阅读列；工具体验内联为「工具轨迹」，出处为底部「出处」条 + 右侧抽屉。
- 扉页是双栏「目录页」：左栏标题 / 说明 / 真实文档驱动的建议问题，右栏「CAMPUS LINKS 校园入口」（学校官网、教务在线、图书馆、本科招生就业网、研究生院、学生处）与「或者直接问」；⌘K 里同样有一组「校园入口」。
- 移动端（≤900 px）：rail 变底部横条，抽屉变底部面板，知识库列表与详情互相接管。

### 2.3 设计语言

- **双材质**：纸本（默认）与星夜。纸本 `#f2eee4` 纸面、`#1c1813` 墨、`#a3352a` 朱砂；星夜 `#07070b` 底、`#ece6d8` 墨、`#e2684c` 强调；星体色相按文档序号取 `DOC_HUES`。
- **字体**：拉丁展示字 Instrument Serif、数据等宽 JetBrains Mono（均打包，无外链）；中文标题走宋体栈，正文走系统黑体栈，保证离线可用与中文观感。
- **品牌**：使用学校官方校徽 SVG（`src/assets/school-seal.svg`，原比例 `794×659`、`#B22222` 单色路径），只做尺寸缩放，不改配色与结构；出现在左侧栏（42 px）、扉页报头（28 px）与典藏空态（52 px），面积克制、不做水印堆叠。
- **图形语汇**：发丝线、mono 编号（01 / 02）、朱砂印章与发送键；刻度环、光晕、霓虹、渐变网格已从星图中移除，只保留星体、星云（不透明度 ≈0.1）、真实星链与文档名注记。
- **尺度系统**：圆角 `4 / 6 / 10 / 16`、按钮 `26 / 28 / 32`、发丝线 `1 px`、阴影只用两层极轻投影（`--shadow-soft` / `--shadow-sheet`），避免“到处浮起”的卡片感。
- **动效**：只做有含义的过渡——视图进出 12 px 位移、抽屉 260 ms 缓出、星图相机 900–1100 ms easeInOutCubic、运行点呼吸、骨架微光；全部尊重 `prefers-reduced-motion`。
- **可访问性**：所有可点区域有 `:focus-visible` 环、抽屉/面板有 Esc 关闭与焦点回收、对话框有焦点陷阱、图标按钮均有 `aria-label`、正文对比度按纸面/星夜分别校准。

---

## 3. 功能对照清单（旧 → 新）

状态说明：✅ 保留并实测；➕ 新增；🔁 重做后行为一致或更强。

| # | 旧版能力 | 新版实现 | 状态 |
| --- | --- | --- | --- |
| 1 | 发送消息，SSE 流式 | `api/conversation.streamChat` + `consumeSse` + 逐帧渲染 | ✅ |
| 2 | 新建会话（复用空会话） | 「新会话」不建空会话，首次发送才 `POST /api/sessions` | 🔁 |
| 3 | 历史会话列表、分组、搜索 | `SessionLedger`（今天/昨天/本周/更早、搜索、未读点） | ✅ |
| 4 | 切换与恢复历史 | 路由 `/inquiry/:sessionId` + `loadHistory`，刷新可恢复 | 🔁 |
| 5 | 删除会话（409 生成中） | 确认框 + `DELETE`，409 →「会话正在生成中，暂时不能删除」 | ✅ |
| 6 | 重新生成回答 | `regenerateChat`，422/404 分别给文案，失败回滚原文 | ✅ |
| 7 | 图片上传与多模态 | `uploadImage`（XHR 进度）→ `images:[path]`，缩略图可点开 | ✅ |
| 8 | 用户身份 `x-user-id` | `api/http.js` 统一注入 `user_001` | ✅ |
| 9 | Markdown + 代码高亮 | markdown-it + highlight.js 按需 14 种语言 | ✅ |
| 10 | 工具调用过程 | `RunTrace`：真实 `tool_started/tool_finished`、耗时、参数、引用数 | 🔁 |
| 11 | 来源汇总 | `SourceStrip`（**全部出处**横向滚动 + 滚轮转横向 + 加宽到 838 px）+ `SourceSheet`（逐条切换、正文、页码/章节、网页真实链接） | 🔁 |
| 12 | 自动滚动 / 回到最新 | 距底 <96 px 跟随，>320 px 出现「回到最新」 | ✅ |
| 13 | 草稿 | 旧版内存 Map → 新版按会话 `localStorage` | 🔁 |
| 14 | 未读标记 | `ui.visited` + `isUnread`，打开即标已读 | ✅ |
| 15 | 错误与断流提示 | 401/404/409/413/415/422/503 与「连接已中断」逐类文案 | ✅ |
| 16 | 知识库列表、搜索、筛选、分页 | 搜索 300 ms 防抖、格式 facet、排序、10/20/50 分页 | ✅ |
| 17 | 文档上传与进度 | XHR 进度、拖拽、类型/大小前置校验 | ✅ |
| 18 | 入库任务状态 | 2 s 轮询 `jobs/{md5}` + 阶段文案（解析/向量化/写入） | ✅ |
| 19 | 分片查看 | 20 条/页、`#0000`、章节、页码（仅 PDF）、字数、展开全文 | ✅ |
| 20 | 文档删除（处理中 409） | 详情页删除 + 确认框 | ✅ |
| 21 | 知识库同步 | `sync` 后提示 scanned/upserted/removed 并刷新统计 | ✅ |
| 22 | 长期记忆列表 / 改写 / 删除 | 卡片、行内编辑（Esc 取消、⌘⏎ 保存）、删除确认 | ✅ |
| 23 | 空态 / 加载 / 失败 | 每个视图与每个列表都有 | ✅ |
| 24 | 多会话并行后台流式 | `runs` 按 sessionId 存放运行态，可 A 会话生成中切到 B 继续提问 | 🔁 |
| 25 | 移动端 | 旧版无；新版底部导航 + 底部抽屉 + 390 px 实拍 | ➕ |
| 26 | 思考模式 | 「深度思考」开关 → `reasoning`，答案内「思考过程」折叠 | ➕ |
| 27 | 停止生成 | 关闭流并标注「这一段回答没有保存」 | ➕ |
| 28 | 命令面板 | ⌘K：新问学 / 星野 / 典藏 / 记忆 / 主题 / 同步 / 最近会话 | ➕ |
| 29 | 主题切换 | 纸本 ↔ 星夜，持久化；星野强制夜色 | ➕ |
| 30 | 代码块语言标签与复制 | 自定义 fence renderer + 事件委托复制 | ➕ |
| 31 | 消息耗时 / tokens | 答案底部 mono 元信息 | ➕ |
| 32 | 失败后「把问题放回书写台」 | 等价旧版「重新填写问题」，含图片还原 | 🔁 |
| 33 | 出处 → 打开文档 / 定位分片 | 出处抽屉：在典藏打开、在星图中定位、以此提问、复制 | ➕ |
| 34 | 知识库总览统计 | 新接口 `/api/knowledge/overview`，抬头「54 篇 · 1,759 片」 | ➕ |
| 35 | 知识星图 | 见 §5 | ➕ |
| 36 | 快捷入口（6 条校园外链） | 扉页右栏「CAMPUS LINKS」竖排 6 条 + ⌘K「校园入口」分组，真实外链、`target=_blank rel="noopener noreferrer"` | 🔁 |

Element Plus、旧 `glass/` 着色器、`ParticleDrift`、`directives/` 均不再使用；旧前端源码已备份于仓库同级 `_legacy_frontend_src/`，未删除原文件历史。

---

## 4. 接口契约

### 4.1 保留（未改动）

`GET/POST /api/sessions`、`GET /api/sessions/{id}/messages`、`DELETE /api/sessions/{id}`、`POST /api/chat`（SSE）、`POST /api/sessions/{id}/messages/{mid}/regenerate`（SSE）、`POST /api/upload`、`GET /uploads/{name}`、`GET/PUT/DELETE /api/memories`、知识库 documents / chunks / jobs / upload / sync / delete —— 方法、路径、请求体、状态码与响应字段均未变。

SSE 事件保持 `run_started / reasoning_delta / text_delta / tool_call / tool_started / tool_finished / done / run_failed`，前端按真实字段消费：

- `run_started`：`session_id`、`user_message_id`、`operation`、`message_id`、`started_at`
- `tool_finished`：`name`、`status`、`tool_call_id`、`elapsed_ms`、`sources`
- `done.final_answer`：`content`、`reasoning`、`finish_reason`、`token_usage`、`total_tokens`、`elapsed_ms`、`message_id`、`reply_to_message_id`、`sources`
- `run_failed`：`error_type`、`message`、`elapsed_ms`

### 4.2 新增（只读，向后兼容）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/knowledge/overview` | 文档数、分片总数、ready/processing/pending/failed、字节数、最近入库时间、facets |
| GET | `/api/knowledge/starmap` | 指纹、算法说明、每篇文档的质心/半径/分片数 |
| GET | `/api/knowledge/starmap/points?offset&limit&force` | 分片坐标与正文，返回 `next_offset` 供分批加载 |
| GET | `/api/knowledge/starmap/edges?limit&force` | 语义连边 + 算法元信息 |

实测响应（真实库）：

```json
GET /api/knowledge/overview
{"documents":54,"chunks":1759,"ready":54,"processing":0,"pending":0,"failed":0,
 "bytes":15289432,"latest_at":"2026-10-19T16:44:01.567460+00:00",
 "facets":{"all":54,"md":28,"doc":13,"docx":8,"pdf":5,"txt":0}}
```

`/starmap` 的 `documents[i]` 含 `file_md5 / file_name / file_type / file_size / chunk_count / center[3] / radius`；`points.items[i]` 含 `id`（Milvus 分片 id，等于引用里的 `chunk_id`）、`file_md5`、`chunk_index`、`x/y/z`、`text`、`preview`、`section_path`、`block_type`、`page`、`chars`、`size`。

后端改动文件：`knowledge/starmap.py`（新增）、`knowledge/documents.py`（`overview()`）、`milvus/client.py`（`iter_all_chunks`）、`api/main.py`（4 条路由）；测试 `tests/test_starmap.py`（14 例）、`tests/test_api.py`（+2 例）。

---

## 5. 知识星图

### 5.1 数据来源

- 数据源：Milvus 集合 `campus_knowledge` 的真实分片，字段 `id / file_md5 / file_name / file_type / file_size / chunk_index / text / section_path / block_type / page`。
- 覆盖：**全部 1759 个分片**，不抽样、不截断；前端按 `next_offset` 循环读完再建索引，HUD 显示 `loaded/total`。
- 每颗星可追溯到唯一 `chunk_id`，并可回查所属文档、`chunk_index`、章节、页码与字数。

### 5.2 空间布局（后端 `knowledge/starmap.py`）

1. 每篇文档的分片向量取质心；文档间用余弦距离做经典 MDS 得到 3D 质心。
2. 质心做径向压缩（`unit / r * r^0.58`），避免少数离群文档把尺度拉爆。
3. 用每篇文档真实半径（分片到质心的最大距离 ×1.02）做星群分离（`gap=0.9`，320 次迭代），保证星群不重叠。
4. 文档内部用 PCA 前三分量 + 半径约束 + 螺旋抖动排布分片。
5. 结果按指纹缓存到 `data/starmap/cache.json`，算法版本 `starmap-v3`。

冷启动构建 2.01 s，之后读缓存；指纹只含集合与版本，改算法必须 bump 版本。

### 5.3 四类关系（严格区分并在 UI 中声明）

| 关系 | 真实性 | 表现 |
| --- | --- | --- |
| 分片 → 文档归属 | **真实**（Milvus `file_md5`） | 星体颜色按文档、按文档筛选、星群光晕 |
| 分片顺序（`chunk_index` 相邻） | **真实** | 「星链」线段，仅连接同文档相邻序号 |
| 跨文档语义相似 | **算法推导**（余弦 ≥ 0.75，最多 900 条，RRF 之外的独立 kNN） | 「语义连线」图层，默认关闭，图例标注「算法推导」 |
| 空间邻接 | **仅视觉** | 说明面板明确：坐标是力学排布，不代表知识关联 |

说明面板原文可见于「关系与坐标说明」（可折叠），并说明坐标距离不构成语义关系。

### 5.3 会话档案常驻

- 会话档案默认是右侧浮层（⌘J / 顶部「会话档案」/ 侧栏「会话」）。抽屉右上角与常驻栏顶部各有一枚图钉：点一下就把档案变成 shell 的**第二列（312 px）**常驻，页面内容与所有视图（问学 / 典藏 / 记忆 / 星野）自动让位重排，不再是遮罩层。
- 状态写入 `localStorage['jxnu.ledger.pinned']`，刷新与跨页保持；窗口 < 1100 px 时自动退回浮层（避免挤压窄屏），此时 ⌘J、顶部按钮与侧栏按钮都改为打开浮层而不是静默失效。
- 常驻时 ⌘J 与顶部「会话档案」按钮改为聚焦档案搜索框；再点图钉即取消常驻。星野页的强制夜色会同时作用到常驻栏（实测面板背景 `rgb(7,7,11)`），不会出现“夜色星图 + 纸色侧栏”的割裂。

### 5.4 交互

- 缩放 / 平移 / 旋转（OrbitControls，带阻尼与惯量，光标在星群上时为 `grab / grabbing`）；双击空白复位。
- 复位视角：回到星图**首帧取景时的机位**（位置与朝向一起恢复，含 target），飞行 900 ms；
  连续两次复位的结果完全一致（方向向量偏差 0.000），不会因为用户旋转/平移后再按复位而落到另一个近似位置。
  任何镜头飞行期间自动旋转暂停，飞行结束后平滑恢复。
- 自动旋转：默认开启，绕当前视角中心自转（实测 **4.56°/s**，约 80 秒一周）。拖拽、滚轮、点击、悬停、打开详情都会在 0.6 s 内平滑减速到 0 并停住；停手后延迟 1.2 s（打开详情时保持静止），再缓入恢复。顶部「自动观测 / 已暂停」按钮可随时开关，状态写 `localStorage['jxnu.atlas.autorotate']`。
- 其他持续动效：星云按 0.42 rad/s 做 ±4.5% 的缩放呼吸与 ±0.022 的透明度呼吸；星体每颗独立闪烁；刻度环缓慢自转；被悬停的星体亮度与尺寸轻微起伏（无外环、无光晕膨胀）；页面顶部三块 UI 以 620 ms 上浮入场。
- **系统「减少动态效果」**：检测到 `prefers-reduced-motion: reduce` 时默认静止，并在抬头显示一枚朱砂色提示「动效已按系统关闭 · 开启」；点击后立刻恢复自转/呼吸/转场，写入 `localStorage['jxnu.atlas.motion']='on'`，同时在 `<html data-motion="on">` 上覆盖全局 CSS 降级，直到用户再次关闭系统偏好。
- 拾取：**真实 3D 拾取**——把鼠标射线转换到世界空间，按“射线到星体中心的垂直距离 ≤ max(视口对应 11 px, 1.6 世界单位)”筛选，再对候选做屏幕投影比较（距离 + 索引微权重），取代原先的二维屏幕距离近似；单击阈值 <6 px / <700 ms，拖拽不会误选。触屏 tap 同一套逻辑（pointerdown/up 配对，无 300 ms 延迟）。
- 悬停预览：指针停留即显示该分片卡片（文档名、`#序号`、章节、正文摘要前 110 字、字数），星体本身只做柔和的亮度/尺寸提升（已彻底移除大圆环与光晕）；`pointerleave`、拖拽、控件交互时隐藏。自动旋转在悬停时 0.6 s 内减速到 0，避免星体从指针下溜走。
- 选中反馈：点击（或从出处定位）一颗星时，镜头平滑飞向它，落点是**面板之后真正可见区域**的中心（桌面扣除左右面板宽度，手机抬到详情抽屉上方；实测 1440 宽落地 x=633，画布自由区中心 636）；距离按该分片所属文档的**真实分片分布**拟合（`extent × 2.25 + 8`，26–110），星体与其同文档星群同时入画，不再用后端分位数半径导致过近或过远。选中的星体带一枚约 38 px 的柔和光晕，明暗与尺寸以 2.3 rad/s 呼吸（实测中心亮度 40→45、最大值 82→109），同时其余星体压到 0.8 亮度，保证“克制但明显”；不新增任何圆环。
- 详情面板：固定在视口右侧，用从**被点星体屏幕坐标**换算出的百分比原点做 `clip-path: circle(0% → 160%)` 展开（原点在 4%–96% 之间钳制，修复了此前用像素值导致的大面积弧形裁切）；面板标题、元信息、可滚动正文、底部动作条互不遮挡；≤640 px 变成底部上浮。面板展示真实正文、文档、`#序号 / 总数`、字数、页码（仅 PDF）、章节路径；动作：在典藏打开、以此提问、复制、聚焦星群。
- 切换星体：相机从**此刻的真实机位**沿二次贝塞尔弧线飞向新目标（起点每帧读取，快速连点由最新目标接管，不跑完上一段、不瞬移），时长按空间距离伸缩 **520–1180 ms**（近距离实测 565 ms，跨星群 1180 ms），位置/朝向/距离逐帧插值；详情面板内容以 `mode="out-in"` 110 ms 退、260 ms 进交叉淡入，与新星体飞行同步。关闭详情回到打开面板前的机位（实测 98.42 → 98.42）。
- 默认取景：`fitRadius × 1.72`（实测距离 **75.2**）；首次进入从 **2.85 倍**远处用 sine 缓动 **3.2 s** 缓慢靠岸到该机位，接近镜头在远处停留更久，不抢戏。入场飞行未落定时暂不铺文档名（距离 > 2.05×fitRadius 时只发空标签），避免远处缩成一团时文字互压。
- 搜索：正文 / 章节 / 文档名，输入 260 ms 防抖，命中数 `m / total`，↑↓ 在命中间跳转，⏎ 定位首个并飞行。
- 筛选：文档 chips（按分片数排序）、格式 chips（MD/DOC/DOCX/PDF/TXT）；筛选只改颜色与透明度，不改几何。
- 深链：`/atlas?focus=md5:index`（`&chunk=<milvus id>` 作为兜底匹配键）、`?doc=md5`；从出处抽屉「在星图中定位」直达。
- **出处 → 星图（真实链路）**：出处抽屉的「在星图中定位」读取经过 `normalizeSources` 归一化后的 `fileMd5 / chunkIndex / chunkId`（此前实现按 snake_case 读取，字段恒为空，按钮静默失效——这是本轮修掉的真实缺陷）；星图优先按 `md5:index` 命中 `byStarKey`，失败再按 Milvus 分片 id 命中 `byId`，成功后执行与其他选中完全一致的「居中 → 最大尺度 → 呼吸」。
- **定位失败不静默**：两种身份都匹配不到时，星图中央弹出 `LOCATE FAILED` 卡片（说明“可能已被重新入库”），提供「在典藏打开该文档」与「关闭」；同时 toast 一次，URL 保留便于重试。
- **所属文档**：出处抽屉「所属文档」跳到 `/archive/<md5>?chunk=<index>`，典藏自动翻到该分片所在页、展开正文并给它加朱砂左侧标记（`.chunk.is-target`）；星图详情底部的「在典藏打开」走同一路径。两处都只使用后端返回的 `file_md5 / chunk_index`，不构造任何示例数据。
- 键盘：`/` 聚焦搜索（从页面任意位置可用）、Esc 清选并关闭详情；`Tab` 可进入三维视图（`role=application`），聚焦时中央出现 1.1 s 朱砂涟漪环（12 → 23 px）；`←/→` 在命中结果间浏览。
- 文档名（分类名称）可隐藏：抬头新增「文档名」开关（`eye/eyeOff`），状态写 `localStorage['jxnu.atlas.labels']`；桌面默认显示，**窄屏默认隐藏**，星图只剩星体与星云，需要时一键打开。标签已去掉胶囊底与边框，改为纯文字 + 柔和投影，按该文档分片数决定字号（10–12.6 px）与不透明度（0.5–1.0），重叠时保留分片更多的文档；标签整体 `pointer-events: none`，只是注记，绝不遮挡星体的悬停与点选（聚焦某篇文档走左侧文档 chips）。
- 移动端：面板默认收起，详情以全宽底部面板呈现；抬头按钮收起为纯图标；手势与桌面一致（单指旋转、双指缩放）。

### 5.5 渲染

Three.js `Points` + 自定义 ShaderMaterial：每颗星有独立尺寸、色相、闪烁相位与深度衰减，加色混合；另外用 `aEmphasis` 属性把“悬停 / 选中 / 搜索命中”合成在一个属性里做平滑过渡，不再叠加任何屏幕空间环或额外 Sprite。每篇文档一个星云 Sprite（透明度 0.105）；远景星场 700/1500 颗；**圆形时间轴**（三条同心发丝环 + 72 格刻度，半径 0.84×取景半径，绕星群 0.012 rad/s 缓慢自转，减少动效时静止）；星链与语义线为 `LineSegments`；相机飞行 520–1180 ms（easeInOutCubic；入场用 easeInOutSine 3.2 s；逐帧在渲染循环里推进，`dt` 上限 0.06 s，切标签页回来不会突跳）。

文档标签为 DOM 覆盖层（每 120 ms 投影一次，按屏幕包围盒避让、贴边钳制，新标签 420 ms 淡入上浮），中文排版与点击都由浏览器完成；关闭开关后引擎不再投影也不再推送，不产生多余的 DOM 与样式计算。

进入星图时：路由切换先播放 620 ms 的“关灯”遮蔽层（上下两条墨色幕布 + 一条发丝亮线从中间收拢），同时真实数据分页加载；加载完成后遮蔽层以 560 ms 反向退场，同时相机从 `1.55 × fitDistance` 缓推到标准取景，形成“星群从暗处浮现”的开场。`prefers-reduced-motion` 时不播遮罩动画。

星体亮度：闪烁幅度收窄到 0.88–1.0，点径系数 196/dist（普通上限 9.2 px、选中 12.6 px），片元 `glow 1.12 + halo 0.9`；同机位截图的亮像素（>140）从 2,571 增到 14,344、极亮像素（>200）从 410 增到 2,994，星群中心仍未整片过曝。

低性能设备（`hardwareConcurrency ≤ 4` 或 `deviceMemory ≤ 4`）降 `pixelRatio` 至 1.35；`prefers-reduced-motion` 时关闭闪烁与自动旋转。页面进入后台（`visibilitychange`）时停掉 rAF 与自动旋转，回到前台再恢复；帧率采样低于 52 fps 时按 0.12 一档下调 pixelRatio（最低 0.62×），高于 72 fps 再缓慢补回，避免高分屏上填充率过高。

### 5.6 验收对照

| 要求 | 结果 |
| --- | --- |
| 所有符合条件分片可访问 | 1759/1759，唯一 id 1759，无重复坐标 |
| 星体 ↔ 分片映射正确 | 详情正文与 `/chunks` 接口逐字一致 |
| 分片 ↔ 文档映射正确 | 面板显示文档名、类型、`index/count`，可跳转典藏 |
| 搜索与筛选正确 | 「图书馆」→ 52 / 1759 命中，结果与正文一致 |
| 文档增删后星图反映变化 | 上传 3 分片文档后抬头变 55 篇；删除后回到 54 篇；`force` 重建 |
| 大规模交互可用 | 1759 星体首屏 0.64 s，240 fps（headless），堆 21 MB |
| 失败可恢复 | 404/503 分别给出「后端旧版本」「知识库未就绪」与重试 |
| 空库 | 显示空态与「去上传」入口 |

### 5.7 文字可读性（WCAG 2.1 对比度）

`_devtools/contrast.py` 解析 `frontend/src/styles/tokens.css` 与星图面板实际使用的叠色，按 WCAG 相对亮度公式计算。纸本与星夜两套令牌下，正文与 UI 文案全部达到 AA（≥4.5:1）：

| 令牌 | 纸本（bg #f3efe6 / surface #faf7f0） | 星夜（bg #07070b / surface #0c0d13） |
| --- | --- | --- |
| `--ink` | 15.9 / 17.2 | 16.5 / 15.6 |
| `--ink-2` | 9.0 / 9.8 | 11.5 / 10.9 |
| `--ink-3`（次级说明） | 6.11 / 6.67 | 6.76 / 6.04 |
| `--ink-4`（最弱，仍用于可交互标签） | 4.58 / 5.01 | 5.42 / 4.84 |
| `--accent`（朱砂） | 6.0 / 6.5 | 5.4 / 5.1 |

另做了一轮**小字专项**：全站 8–10.5 px 的辅助文字统一抬到 **10–11 px**（分类、出处 pill、文档元信息、工具轨迹、章节路径、按钮文字、抬头提示等），星图深色面板上低于 0.6 alpha 的文字统一提到 **0.66–0.78**，并把面板底色加深到 0.9；星图星体色相饱和度从 0.55 降到 0.2、远景星改为暖灰，避免“霓虹小字”与彩色 HUD 观感。`kbd` 保持 9.5 px 但禁止换行，`Tab` 焦点环与按钮 `:focus-visible` 未改动。

星图上另做三层保障：面板底色提到 `.90`；文档标签改为纯文字 + 双层柔影（不再有半透明胶囊，阴影保证任何星云亮度下都可读）；悬停卡片 `.94` 并加 12 px 模糊。分片正文与出处正文均为纸面/夜色实底，长段落对比度 ≥10:1。

---

## 6. 真实联调验证记录

全部在 `http://localhost:5180`（Vite）→ `127.0.0.1:8002`（FastAPI）→ 真实 PostgreSQL / Milvus / DashScope 上完成；截图在 `../_devtools/`。

| # | 场景 | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | 提问「学校有哪些奖学金？申请需要什么条件？」 | 18 s 完成，24,851 tokens，14 条出处，标题自动生成为问题前 30 字 | `final/02-inquiry-thread.png` |
| 2 | 工具轨迹 | 四次真实 `knowledge_search`（每次约 0.5 s），每步带「知识库 · 5 条引用」 | `_devtools/parallel-a-live2.png` |
| 3 | 出处抽屉 | 打开真实分片正文、页码、章节、类型 | `final/03-inquiry-source-sheet.png` |
| 4 | 重新生成 | SSE 重新跑，答案替换，轮次数不变 | `_devtools/flow-chat-4-regenerate.png` |
| 5 | 停止生成 | 3.5 s 后停止 →「已停止生成，这一段回答没有保存」；刷新后 1 轮 0 回答 | `_devtools/flow_stop_theme.py` 日志 |
| 6 | 图片多模态 | 上传旧界面截图，模型准确描述「顶部导航栏 + 三栏主体」 | `_devtools/flow-image-2-answer.png` |
| 7 | 图片历史回显 | 刷新 `/inquiry/649ab1de…` 后缩略图仍在 | `_devtools/flow-image-3-history.png` |
| 8 | 多会话并行 | A（奖学金）生成中切到 B（图书馆）再提问，档案里两条同时「正在生成」；切回 A 仍在流式 | `_devtools/parallel-two-running.png`、`parallel-a-live2.png` |
| 9 | 知识库上传 | `upload-probe.md` → 2.5 s ready、3 分片；抬头 55 篇 / 1,762 片 | `_devtools/flow-archive-3-ingested.png` |
| 10 | 分片查看 | `#0000/#0001/#0002` 正文与真实文件一致；PDF 显示 `p.1/p.2` | `final/05-archive-detail.png` |
| 11 | 文档删除 | 确认框 → 删除 → 回到 54 篇 / 1,759 片 | `_devtools/flow-archive-10-deleted.png` |
| 12 | 知识库同步 | 返回 scanned/upserted/removed 并刷新统计 | 命令行 + toast |
| 13 | 记忆改写 / 删除 | 改写保存成功，Esc 取消删除仍 3 条 | `final/06-memory.png` |
| 14 | 会话档案 | 今天/昨天/本周分组、未读点、⌘J、↑↓/⏎ | `_devtools/flow-chat-5-ledger.png` |
| 15 | 命令面板 | ⌘K 12 项，首项「开始一段新的问学」 | `_devtools/flow-chat-6-palette.png` |
| 16 | 主题 | 星夜 ↔ 纸本；星野强制夜色，离开还原 | `final/09/10/11-night-*.png` |
| 17 | 星图搜索 | 「图书馆」52 命中，选中显示真实分片 #0001 | `final/08-atlas-selected.png` |
| 18 | 星图画布拾取 | 点击星体选中、Esc 清除、图层开关可用 | `_devtools/flow-atlas-3-select.png` |
| 19 | 移动端 | 390×844 四页可用，底部导航、底部抽屉、星图渲染 | `_devtools/mobile-*.png`、`atlas-mobile-390b.png` |
| 20 | 快捷入口 | 扉页 6 条真实外链；⌘K 输入「图书馆」命中「校园入口 · 图书馆」并在新标签打开 `tsg.jxnu.edu.cn` | `final/18-command-palette.png`、`final/19-inquiry-campus-links.png` |
| 22 | 出处全量浏览 | 出处条按文档/网页归并全部引用并标 `×N`，横向可滚、滚轮转横向（scrollWidth 1,050 > 739）；「核对 15」列出 15 条可切换；网页出处渲染真实 `https://…` 并在新标签成功打开 `www.jxnu.edu.cn` | `final/24-sources-all.png` |
| 23 | 星图文档名开关 | 关闭「文档名」→ 0 个标签、写入 `jxnu.atlas.labels=off`，刷新后仍关闭；重新打开恢复 11 个标签；窄屏默认 0 个 | `final/23-atlas-labels-off.png` |
| 21 | 控制台 | 上述流程 0 error / 0 warning | 各脚本 `ERRORS []` |
| 24 | 点星聚焦 | 点击星体：镜头 75.2 → 26.0，落点 x=633（自由区中心 636），选中光晕亮度 40→45、其余星体压到 0.8 | `final/08-atlas-selected.png` |
| 25 | 星体切换 | 同文档 A→B 落点仍 633，位置/朝向/距离连续插值，无瞬移；Esc 回到 75.24 | `flow_focus.py` 采样 |
| 26 | 出处 → 星图定位 | 出处抽屉「在星图中定位」→ `/atlas?focus=faa6f64b…:11`，`byStarKey` 命中并执行居中/最大尺度/呼吸；不存在时弹 `LOCATE FAILED` 卡片 | `final/08-atlas-selected.png`、`locate-failure.png` |
| 27 | 出处 → 所属文档 | 「所属文档」→ `/archive/faa6f64b…?chunk=11`，翻到第 2 页、展开该分片并加朱砂标记 | `final/27-archive-target-chunk.png` |

---

## 7. 构建与测试

### 7.1 构建

```bash
cd frontend
$env:TEMP="D:\1oveb\毕业设计\.tmp"; $env:TMP=$env:TEMP   # Windows 沙箱下 esbuild 临时文件需要
npm run build
```

结果：`✓ built in 1.21s`，131 modules。产物：

| 文件 | 原始 | gzip |
| --- | --- | --- |
| `index-*.js` | 163.05 kB | 63.12 kB |
| `InquiryView-*.js` | 222.08 kB | 82.79 kB |
| `AtlasView-*.js` | 45.87 kB | 17.86 kB |
| `three-*.js`（仅星图路由加载） | 548.62 kB | 136.03 kB |
| `ArchiveView / MemoryView` | 15.13 / 6.79 kB | — |
| CSS 合计 | ≈86 kB | ≈20 kB |
| `school-seal-*.svg`（校徽，按需缓存） | 135.84 kB | 39.21 kB |

Three.js 被拆到独立 chunk，只有进入 `/atlas` 才下载。构建仍会提示 `three` 体积 >500 kB，这是渲染库本身的成本。

### 7.2 测试

```bash
# 后端（项目根）
python -m unittest discover -s tests        # Ran 79 tests ... OK

# 前端（frontend/）
npm test                                    # 6 files, 58 tests passed
```

前端测试覆盖：SSE 分帧、Markdown/代码块/表格/链接安全、时间与数字格式化、引用归并与按文档分组、轮次配对（含孤儿回答）、星图 store 的筛选/搜索/链对生成。

后端新增测试覆盖星图布局（唯一性、覆盖、排序、缓存指纹、无向量退化、算法元信息）与总览接口（聚合、503）。

### 7.3 静态检查

- `npm run build` 无 Vue 编译警告；控制台无 hydration / 运行时告警。
- 旧版 Element Plus 依赖已移除，`package.json` 只保留运行所需依赖。
- 无外链字体与图片请求（全部本地打包），断网仍可渲染。

---

## 8. 视觉验收记录

截图目录：`../_devtools/final/`（2880×1800，DPR 2；共 25 张）。

| 文件 | 内容 |
| --- | --- |
| `01-inquiry-empty.png` | 问学扉页：官方校徽报头、宋体「问学」+ Instrument Serif 斜体、真实文档驱动的建议卡、右栏「CAMPUS LINKS 校园入口」、书写台 |
| `02-inquiry-thread.png` | 多轮回答：表格、标题层级、出处条、操作行、tokens/耗时 |
| `03-inquiry-source-sheet.png` | 出处抽屉：真实分片正文与文档元信息 |
| `04-archive-list.png` | 典藏双栏：搜索、facet、排序、分页、状态点 |
| `05-archive-detail.png` | 文档详情：元数据栅格、指纹、分片列表 |
| `06-memory.png` | 记忆卡片：类别、时间、改写/删除 |
| `07-atlas.png` | 星图总览：54 星群、文档名注记、文字式筛选、底部操作说明、「自动观测」开关 |
| `08-atlas-selected.png` | 选中真实分片：右侧详情（从星体 clip-path 展开）、章节、正文、动作 |
| `21-atlas-hover.png` | 悬停预览：星体旁的分片卡片（星体只提亮，无圆环） |
| `25-atlas-flight.png` | A→B 切换途中：面板内容交叉淡入、镜头沿弧线移动 |
| `22-atlas-motion-off.png` | 系统「减少动态效果」时的抬头提示「动效已按系统关闭 · 开启」 |
| `23-atlas-labels-off.png` | 关闭「文档名」后的纯星场：只剩星体与星云，状态持久化 |
| `24-sources-all.png` | 出处条展开到全部引用（横向可滚）与网页出处的真实链接 |
| `09/10/11-night-*.png` | 星夜模式下的问学 / 典藏 / 记忆 |
| `12-night-atlas.png` | 星夜星图（与纸本共用同一套 three.js 场景） |
| `13-mobile-inquiry.png` | 390 px 问学：扉页、会话档案入口、书写台、底部导航 |
| `14-mobile-ledger.png` | 移动端会话档案（底部面板） |
| `15-mobile-archive.png` | 移动端典藏列表 |
| `16-mobile-memory.png` | 移动端记忆卡片 |
| `17-mobile-atlas.png` | 移动端星图（面板默认收起、取景按宽高比拉远、只保留 4 个文档名） |
| `18-command-palette.png` | ⌘K 面板：「校园入口 · 图书馆」分组与最近会话 |
| `19-inquiry-campus-links.png` | 校园入口 6 条外链（hover 态：朱砂箭头）与「或者直接问」 |
| `20-mobile-campus-links.png` | 移动端「校园入口」竖排列表 |

与旧版对照：旧版为 `../_devtools/legacy-1440.png`（三栏玻璃面板 + 粒子网络背景）。新版去掉玻璃拟态与随机粒子，改用纸本纹理、发丝分隔与编辑式排版；星图承担「视觉冲击」，其余界面承担「可读与效率」。

---

## 9. 性能与兼容性

| 指标 | 数值 | 条件 |
| --- | --- | --- |
| 星图首屏 ready | 0.64 s | 1759 星体、Chrome headless、1440×900 |
| 星图帧率（静止/自转） | 240 fps（headless，DPR 1 与 2 均为上限 240） | 无 vsync；DPR 2 首次加载瞬时 43 fps，自适应像素比介入后回满 |
| 星体 A→B 飞行 | 565 ms（同星群）/ 1180 ms（跨星群） | 逐帧位移连续，最大单帧位移 2.78 世界单位 |
| 星图帧率（自动旋转中） | 240 fps | 同上，旋转不额外增加每帧计算 |
| 自动旋转角速度 | 4.56°/s（约 79 s 一周） | 1 s 间隔采样三点：4.56 / 4.57 |
| 悬停/点选一致性 | 投影点命中 → 提示卡 `#0281` → 详情 `CHUNK · #0281` | Playwright 精确坐标点击 |
| 关闭详情后机位 | 98.42 → 98.42（距离完全还原） | `saveCameraState / restoreCameraState` |
| 后台暂停 | 隐藏时 fps 计数器冻结、旋转角不变；恢复后继续 | 覆写 `document.hidden` + `visibilitychange` |
| JS 堆 | 21 MB | 同上 |
| 星图布局构建 | 2.01 s（冷） / 命中磁盘缓存 ~0.1 s | 54 文档 |
| 对话首字 | 与后端模型一致（实测 1–2 s 内出现工具轨迹） | qwen3.8-flash |
| 首屏 JS | 163 kB（gzip 63 kB） | three 延迟加载 |

兼容性：

- Chrome / Edge（Chromium 120+）实测；Safari 与 Firefox 使用标准 API（`ReadableStream`、`ResizeObserver`、CSS `color-mix`、`backdrop-filter`），未做真机验证。
- 390×844、768×1024、1440×900、1920×1080 均无横向滚动。
- WebGL 不可用时星图会显示错误态与「去典藏」入口，不阻塞其他页面。
- 键盘全流程可用（Tab、Esc、↑↓、⏎、⌘K、⌘J、`/`）。

---

## 10. 启动与部署

前置：Docker（PostgreSQL / Milvus / etcd / MinIO）、Python 3.13（conda 环境 `Graduation-Project`）、Node 20+。

```bash
# 1. 依赖服务
docker compose up -d

# 2. 后端（项目根）
uv run uvicorn api.main:app --host 127.0.0.1 --port 8002 --reload
#   Windows 本机若无 uv：
#   $env:PATH="D:\SoftWare\conda\envs\Graduation-Project;<...>\Library\bin;<...>\Scripts;" + $env:PATH
#   $env:PYTHONPATH="<repo root>"
#   python -m uvicorn main:app --host 127.0.0.1 --port 8002 --app-dir api

# 3. 前端
cd frontend
npm ci
npm run dev            # http://127.0.0.1:5173
# 端口冲突：npm run dev -- --port 5180 --strictPort
# 后端不同源：JXNU_API=http://127.0.0.1:8002 npm run dev

# 4. 生产构建
npm run build          # 产物在 frontend/dist，可交给任意静态服务器
```

星图首次打开会请求一次布局（约 2 s），缓存写入 `data/starmap/cache.json`；新增/删除文档后指纹变化会自动重建，也可在星图页点「重建」或在请求上加 `?force=true`。

详细前端说明见 `frontend/README.md`。

---

## 11. 未解决问题、风险与限制

1. **无真实鉴权**：仍按任务书保留 `x-user-id: user_001`，任何拿到页面的人都能读写同一份数据；知识库接口没有管理员校验，`/uploads` 公开可读。
2. **停止生成是客户端断开**：后端没有逐轮取消信号，断开后本轮不会落库，但模型侧的调用可能已经发生（计费与日志仍会记录）。
3. **工具轨迹与思考过程不持久化**：`complete_turn` 只保存正文、来源与 token；历史消息里的轨迹与推理不会回来。这是后端既有行为，本次未改动。
4. **多标签页并发**：同一会话在两个标签页同时发送时，第二个会收到 409 并显示提示；不同标签页的不同会话可以并行，但没有跨标签的运行态同步（刷新后仅能看到已落库的部分）。
5. **语义连边是启发式**：阈值 0.75 未用标注集校准，只作为探索线索；UI 已标注为算法推导，不作为「知识关联」结论。
6. **星图一次性载入全部分片**：当前 1759 点无压力；若库增长到 1 万级以上，需要把「全量可检索」与「视口内高精度渲染」进一步分开（接口已支持分页，渲染层尚未做 LOD 分块）。
7. **旧浏览器回归脚本失效**：`tests/browser_*.cjs` 针对旧版 DOM，已不适用于新前端；新版验证脚本是 `_devtools/*.py`，未纳入 `npm test`。
8. **未验证项**：Safari / Firefox 真机、低端 Android GPU、真实多用户并发、Milvus 大规模（>1 万）性能、弱网下 SSE 重连（当前只提示断流，不自动重试）。
9. **移动端细节**：iOS 安全区已处理（`env(safe-area-inset-bottom)`），但未在真机 Safari 上验证软键盘顶起输入框的行为。

---

## 12. 复现与文件索引

- 前端源码：`frontend/src/`（views / components / stores / api / three / styles / utils）
- 前端说明：`frontend/README.md`；单元测试：`frontend/tests/`
- 后端新增：`knowledge/starmap.py`、`knowledge/documents.py#overview`、`milvus/client.py#iter_all_chunks`、`api/main.py`（4 条路由）、`tests/test_starmap.py`、`tests/test_api.py`
- 旧版基线：`../Audit-LegacyFrontend.md`（旧前端逐项行为，含不存在的能力）
- 旧前端备份：`../_legacy_frontend_src/`
- 联调脚本与截图：`../_devtools/`（`flow_chat.py`、`flow_archive.py`、`flow_memory.py`、`flow_atlas.py`、`flow_image.py`、`flow_parallel*.py`、`shot.py`、`final/`）
- 星图探针：`../_devtools/probe_starmap.py`、`probe_pct.py`、`probe_spread.py`、`probe_sep.py`

复现一次完整验证：

```bash
docker compose ps                       # 三个库在线
python -m unittest discover -s tests    # 79 passed
cd frontend && npm test && npm run build
npm run dev -- --port 5180 --strictPort
# 另开终端
python ../_devtools/flow_chat.py
python ../_devtools/flow_archive.py
python ../_devtools/flow_atlas.py
python ../_devtools/flow_memory.py
```
