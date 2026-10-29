# 账号、权限与产品入口

公开首页为 `/`；`/login` 和 `/register` 使用同一产品入口页面，分别选择登录、注册表单。下方问答、引用和星图是标注的交互示例，不调用模型或读取真实业务数据。

## 首次启用

在项目 Python 环境中安装锁定依赖，配置 `.env`，随后重启后端：

```powershell
uv sync
```

新增配置：

```dotenv
AUTH_JWT_SECRET=至少32字节的随机密钥
AUTH_COOKIE_SECURE=false
AUTH_ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
```

生成密钥可使用 `python -c "import secrets; print(secrets.token_urlsafe(48))"`，仅写入本地 `.env`。当前开发环境已生成独立随机密钥；不要把它复制到仓库或前端。部署时使用 HTTPS，设置 `AUTH_COOKIE_SECURE=true`，可信来源改为实际前端 Origin（协议、主机、端口完全匹配）。前后端仍通过同源 `/api` 和 `/uploads` 代理通信。

## 初始化首个管理员和旧数据

先备份 PostgreSQL，再在仓库根目录运行：

```powershell
python -m auth.bootstrap
```

命令交互确认备份、输入用户名和隐藏密码，事务内创建首个管理员，将 `user_001` 与空归属的旧会话、个人记忆及可确认归属的历史图片迁给该管理员。用户名为3–32位字母、数字、下划线或连字符，密码为8–128个字符。会话、消息 ID 和 checkpoint 关联保持原样。

迁移记录为 `auth-bootstrap-v1`，再次运行不会覆盖账号密码或重新分配数据。已有管理员但没有迁移记录时拒绝自动接管，需检查数据库状态。无法确认归属的旧图片不对外开放。

本次开发已将迁移逻辑放在独立测试 schema 中验证；正式管理员密码需通过上述本地命令自行设置。实际数据库尚未执行该个人数据接管。开发前数据备份保存在忽略目录 `data/backups/before-auth-20261026.sql`，不提交到 Git。

## 角色边界

| 能力 | 普通用户 | 管理员 |
|---|---|---|
| 对话、深度思考、重新生成、个人记忆、图片 | 仅自己的数据 | 仅自己的数据 |
| 文档查看与 AI 自动检索 | public 且 ready 的文档 | 所有 ready 文档 |
| 星图节点、关联及文档统计 | 仅公开文档 | 全部可用文档 |
| 独立知识检索 `/admin/search` | 无 | 有 |
| 文档上传、同步、删除、可见性 | 无 | 有 |
| 账号管理 `/admin/users` | 无 | 有 |

`public` 指全体登录用户，匿名访问仍需登录。原有文档迁入时默认 public，新上传默认 admin。管理员在典藏详情中调整范围，查看、后续检索和星图立即遵守新权限。已经生成的历史回答不追溯改写，来源目标重新验证当前权限。

管理员没有读取他人会话、记忆和图片的专用接口。新增看板时只应聚合对话次数与用量，不返回个人内容。数据看板和系统日志管理页面不属于本轮。

## 认证接口

| 接口 | 用途 |
|---|---|
| `POST /api/auth/register` | `{username,password}`，固定注册为 user 并登录 |
| `POST /api/auth/login` | `{username,password}` |
| `GET /api/auth/me` | 返回 `{user,csrf_token}`，不返回密码哈希 |
| `POST /api/auth/logout` | 撤销当前登录并删除 Cookie |
| `POST /api/auth/password` | `{current_password,new_password}`，撤销全部登录 |
| `GET /api/admin/users?q=&page=1` | 每页20条账号 |
| `POST /api/admin/users` | `{username,password,role}`，创建临时密码账号 |
| `PATCH /api/admin/users/{id}` | `{role?,enabled?}`，撤销该账号现有登录 |
| `POST /api/admin/users/{id}/reset-password` | `{password}`，下次必须改密 |
| `POST /api/admin/knowledge/search` | `{query,mode?,top_k?,top_n?}`，管理员独立检索 |
| `GET /api/admin/model-settings` | 查看全站聊天模型选择、可选目录、密钥配置状态及失效提示 |
| `PUT /api/admin/model-settings` | `{provider,model}`，更新全站聊天模型选择 |
| `PATCH /api/knowledge/documents/{md5}/visibility` | `{visibility:"public"或"admin"}` |

JWT 经 HttpOnly、SameSite=Lax Cookie 保存，有效期8小时，不自动续期。每次鉴权检查签名、有效期、签发方、接收方、服务端会话及用户当前状态。写请求携带 `/auth/me` 或登录响应返回的 `X-CSRF-Token`，并校验可信 Origin。旧的 `x-user-id` 不再提供身份认证。

聊天模型目录由服务端 `config/chat_models.json` 维护，条目包含供应商、模型名称及 `images`、`reasoning` 能力。支持 DeepSeek、DashScope、OpenAI，密钥分别从 `DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY`、`OPENAI_API_KEY` 环境变量读取，接口只返回是否配置，不返回密钥，也不验证其有效性。全站选择保存在 PostgreSQL；未保存时使用 `deepseek/deepseek-flash`。已选模型被移出目录或缺少密钥时，接口的 `current_error` 提示管理员修正，聊天不会自动切换到其他模型。配置切换只影响之后开始的请求，摘要、记忆抽取、向量化和重排使用各自原有配置。

管理员检索的 `mode` 可选 `vector`、`hybrid`、`hybrid_rerank`，默认 `hybrid_rerank`；`top_k` 和 `top_n` 分别默认 20 和 5，范围均为 1–50，且 `top_n` 不得大于 `top_k`。响应保留 `items`，并返回 `mode`、`score_type`（`cosine`、`rrf` 或 `rerank`）、`candidate_count`、`elapsed_ms` 和 `rerank_status`。重排失败时状态为 `fallback`，结果及分数使用混合检索的 RRF 融合分；没有候选时重排状态为 `not_run`。候选数只包含返回前仍可访问的文档片段。

登录失败按来源 IP 与用户名组合限制为15分钟内5次。停用、角色变化、密码重置及改密使现有登录失效；账号管理通过数据库事务锁保留至少一名启用的管理员。临时密码登录仅允许查看本人身份、修改密码和退出，完成改密后重新登录。

`/uploads/{name}` 保留原地址格式，改为检查登录及图片归属的私有读取，并禁止缓存；聊天发送图片时再次检查归属。检索身份经 LangGraph 的请求级 Runtime context 传递，不存放在共享工具实例、对话消息或 checkpoint 中。

## 验证

```powershell
python -m unittest discover -s tests
cd frontend
npm test
npm run build
```

`tests/test_auth.py` 使用真实 PostgreSQL 的临时 schema，并在结束时删除该 schema，不修改正式账号。需要可用的 `LANGGRAPH_POSTGRES_URI`。Windows 使用 Conda 时，请先激活项目环境，确保 `Library/bin` 的数值库 DLL 路径可用；esbuild 临时文件受限时，可将本次进程的 `TEMP`、`TMP` 指向 `frontend/node_modules/.cache/esbuild-temp` 后构建。
