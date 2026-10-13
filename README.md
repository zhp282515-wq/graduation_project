# 饭饭 · 江西师范大学校园助手（毕业设计）

基于 LangGraph 构建的校园智能助手 Agent，支持多轮对话、工具调用、流式输出、会话持久化与知识库检索。

## 功能特性

- **多轮 Agent 循环**：LangGraph `StateGraph` 编排，LLM 自主决定是否调用工具，带最大轮次限制与兜底总结
- **流式输出**：`stream_mode="custom"` 逐 token 推送，前端可实时展示推理与回答
- **可插拔工具系统**：天气查询、联网搜索、校园知识库检索，内置 JSON Schema 参数校验与类型检查
- **会话持久化**：基于 LangGraph PostgreSQL Checkpointer，支持中断恢复
- **历史压缩**：长对话按 token 占用自动折叠早期轮次为滚动摘要，完整历史仍保留给前端展示
- **多模型接入**：抽象 `BaseProvider` 接口，已接入阿里云 DashScope（Qwen）与 OpenAI
- **文档解析**：集成 MinerU 解析 PDF / Word / Excel，为 RAG 提供语料
- **向量检索**：Milvus 向量库（etcd + MinIO + Attu 可视化面板）

## 技术栈

| 类别 | 选型 |
| --- | --- |
| Agent 编排 | LangGraph |
| 模型 | DashScope（Qwen）、OpenAI |
| 会话存储 | PostgreSQL 16 + langgraph-checkpoint-postgres |
| 向量库 | Milvus 2.5（etcd / MinIO / Attu） |
| 文档解析 | MinerU |
| 联网检索 | Firecrawl |
| 包管理 | uv（Python 3.13+） |
| 容器编排 | Docker Compose |

## 项目结构

```
Graduation-Project/
├── agent/                  # Agent 核心
│   ├── graph.py            # StateGraph 构建与编译
│   ├── nodes.py            # input / llm / tool / fallback / output / compact 节点
│   ├── routers.py          # llm 之后的条件路由
│   ├── runtime.py          # AgentRuntime 对外门面（stream / delete_thread）
│   ├── state.py            # AgentInput / AgentState / OutputState 状态定义
│   ├── summarizer.py       # 历史压缩与兜底总结
│   └── tools/              # 工具子系统
│       ├── base.py         # BaseTool 抽象基类
│       ├── registry.py     # 工具注册与 schema 校验
│       ├── executor.py     # 参数校验与工具执行
│       ├── weather.py      # 天气查询
│       ├── websearch.py    # Firecrawl 联网搜索
│       └── knowledge_search.py  # 校园知识库检索
├── models/                 # 模型 Provider 抽象与实现
│   ├── base.py             # BaseProvider / ChatMessage / ChatResponse / ToolCall
│   ├── dashscope/          # Qwen 对话与 embedding
│   └── openai/             # OpenAI 对话
├── knowledge/              # 知识库入库管线
│   ├── mineru_parser.py    # MinerU 云端解析（落盘 full.md / content_list.json）
│   ├── chunking.py         # 按标题栈切块，相邻块重叠
│   └── server.py           # KnowledgeService：解析入库与检索入口
├── milvus/                 # Milvus 客户端封装
│   └── client.py           # 知识块写入与稠密检索
├── checkpoint/             # PostgreSQL Checkpointer 上下文管理
├── session/                # 会话领域层（models / ports / repository / service）
├── prompts/                # system_prompt.md 等提示词
├── utils/                  # 日志、图片编码、提示词加载等工具
├── api/                    # HTTP 接口层（待实现）
├── docker-compose.yml      # etcd / MinIO / Milvus / Attu / PostgreSQL
└── pyproject.toml
```

## 运行流程

```mermaid
graph TD
    START([START]) --> input_node
    input_node --> llm_node
    llm_node -->|route_after_llm| tool_node
    llm_node -->|无工具调用| output_node
    llm_node -->|超出最大轮次| fallback_node
    tool_node --> llm_node
    output_node --> compact_node
    compact_node --> END([END])
    fallback_node --> END
```

- `input_node` 把用户 query 封装为 `ChatMessage`，补齐历史中悬空的 `tool_calls`，初始化轮次与超时
- `llm_node` 流式调用模型，通过 `get_stream_writer()` 推送增量事件；窗口 = 系统消息（含摘要）+ `messages[summary_upto:]`
- `route_after_llm` 决定：无工具调用 → 输出；有调用且未超轮次 → 执行工具后回到 `llm_node`；超轮次 → 兜底总结
- `compact_node` 在输出后检查本轮输入 token，超过上下文窗口约 60% 时把早期轮次折叠成滚动摘要
- `fallback_node` 无后继节点，LangGraph 在图无出边时自动收尾

## 快速开始

### 1. 启动依赖服务

```bash
docker compose up -d
```

会拉起 etcd、MinIO、Milvus（19530）、Attu（8000）、PostgreSQL（5432）。

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，填入自己的密钥。

### 3. 安装依赖

```bash
uv sync
```

### 4. 最小示例

```python
from agent.runtime import AgentRuntime
from agent.tools.weather import WeatherTool
from checkpoint.pg_checkpointer import postgres_checkpointer
from models.dashscope.Qwen_model import DashScopeProvider
from utils.prompts_loader import get_prompt

with postgres_checkpointer() as checkpointer:
    runtime = AgentRuntime(
        model=DashScopeProvider(model="qwen3.8-flash"),
        tools=[WeatherTool()],
        prompts=get_prompt(),
        checkpointer=checkpointer,
    )

    for event in runtime.stream(
        [{"type": "text", "text": "南昌今天天气怎么样？"}],
        session_id="demo-session",
    ):
        print(event)
```

`stream` 的第一个参数是**已组装好的模型内容块列表**（多模态时依次放 `image_url` 与 `text`），不是 `{"query": ...}` 包一层的 dict。

## 说明

- `.env` 中的密钥不会被提交，请参考 `.env.example` 自行配置
- `data/`、`logs/`、`test/`、`knowledge/parser_data/` 为本地调试样本、运行日志、调试脚本与解析产物，不纳入版本控制
- 仓库内暂无自动化测试；计划把不含私有数据的单元测试放入 `tests/` 提交
- 首次运行时 `postgres_checkpointer` 会自动创建 LangGraph 检查点表，可重复调用
- 会话表通过 `setup()` 幂等建表与补列，旧库会按 `legacy_user_id` 回填归属
- `api/` 为规划中的模块

## License

本项目为本科毕业设计，仅供学习交流。
