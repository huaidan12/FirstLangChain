# AI Code-Gen Agent (LangGraph + Milvus Lite)

一个基于 LangGraph 的代码自生成 / 自修复闭环 Demo：LLM 写代码 → 沙箱跑 → 失败就把报错喂回去重写，最多 3 次。
状态用 SqliteSaver 持久化，重试时从 Milvus Lite 检索相似的历史报错案例做 RAG 注入。

## 架构

```
┌──────────────┐      ┌──────────────┐      ┌────────────────────────┐
│  FastAPI     │─────▶│ LangGraph    │─────▶│ coder_node (LLM)       │
│  /run_task   │      │ StateGraph   │      │  └─ RAG: Milvus Lite   │
└──────────────┘      │              │      └────────────────────────┘
                      │ Checkpointer │                │
                      │  (SQLite)    │                ▼
                      │              │      ┌────────────────────────┐
                      │              │◀─────│ tester_node (sandbox)  │
                      └──────────────┘      └────────────────────────┘
```

- **coder_node**：LLM 生成 / 修复代码。重试分支会调 `retrieve_similar_cases()` 从 Milvus Lite 拉相似报错案例拼进 prompt。
- **tester_node**：把代码写到临时 `.py` 文件，用 `subprocess.run` 起子进程跑 5s 超时。
- **decide_next_step**：路由器。校验通过走 END；失败且未超 3 次回 coder；超阈值走 END(failed)。
- **Checkpointer**：`langgraph-checkpoint-sqlite` 落盘到 `data/checkpoint.sqlite`，按 `thread_id` 分会话。
- **知识库**：`pymilvus.MilvusClient` 直连 Milvus Lite，落盘到 `data/milvus_demo.db/`，5 条种子案例首次启动自动灌入。

## 目录结构

```
app/
  ├── main.py             FastAPI 入口
  ├── workflow.py         LangGraph StateGraph + SqliteSaver 挂载
  ├── nodes.py            coder_node / tester_node + LLM 客户端
  ├── sandbox.py          subprocess 沙箱
  └── knowledge_base.py   Milvus Lite 封装（建表/灌种子/检索）
data/                     运行时生成（已 gitignore）
  ├── checkpoint.sqlite   LangGraph 状态快照
  └── milvus_demo.db/     Milvus Lite 数据目录
requirements.txt
```

## 安装

> ⚠️ **macOS 用户注意架构**：本仓库的 venv 历史曾有部分 wheel 是 x86_64 的，在 Apple Silicon 上 import 会报 `incompatible architecture`。所有 pip / python 命令都建议显式 `arch -arm64` 前缀。

```bash
python3 -m venv venv
arch -arm64 ./venv/bin/pip install -r requirements.txt
```

如果遇到二进制包架构不匹配（`pydantic-core`、`xxhash`、`uvloop` 等），强制重装：

```bash
arch -arm64 ./venv/bin/pip install --force-reinstall --no-deps \
  "pydantic-core==2.46.4" \
  charset_normalizer jiter orjson ormsgpack regex tiktoken \
  uuid_utils uvloop watchfiles websockets xxhash PyYAML zstandard \
  protobuf grpcio numpy
```

## 运行

```bash
arch -arm64 ./venv/bin/python -m uvicorn app.main:app --reload
```

调用：

```bash
curl -X POST http://localhost:8000/run_task \
  -H 'Content-Type: application/json' \
  -d '{"requirement": "写一个 execute() 函数，打印从 1 加到 100 的结果"}'
```

返回：

```json
{
  "status": "COMPLETED",
  "iterations": 1,
  "final_code": "...",
  "error": "",
  "thread_id": "a1b2c3..."
}
```

带 `thread_id` 复用上次的会话状态：

```bash
curl -X POST http://localhost:8000/run_task \
  -H 'Content-Type: application/json' \
  -d '{"requirement": "...", "thread_id": "a1b2c3..."}'
```

## 向量库工作时序

`retrieve_similar_cases()` 每次被 `coder_node` 重试分支调用时实际发生的事：

```
首次启动 ────────────┐
  第 1 次检索请求    │
    ├─ has_collection? → False
    ├─ create_collection                    🐢 一次性
    ├─ embed 5 条种子（5 次 embedding 调用） 🐢 一次性
    ├─ insert 入库                           🐢 一次性
    ├─ load_collection（隐式）
    ├─ embed query（1 次 embedding 调用）    🚀 每次
    └─ search                                🚀 每次

  第 2 次检索请求 ──┐
    ├─ has_collection? → True → 直接 return
    ├─ load_collection（已 load，no-op）
    ├─ embed query（1 次 embedding 调用）    🚀
    └─ search                                🚀

  ... 重启服务 ...
  第 N 次检索请求 ──┐ (collection 仍在磁盘)
    ├─ has_collection? → True → 直接 return
    ├─ load_collection（这次是真 load，把磁盘数据装内存） ⚠️ 一次性几十毫秒
    ├─ embed query（1 次 embedding 调用）    🚀
    └─ search                                🚀
```

各步骤频率与开销：

| 操作 | 频率 | 开销 |
|---|---|---|
| `MilvusClient(uri=...)` 新建客户端 | 每次都新建 | 几毫秒 |
| `has_collection()` 幂等检查 | 每次 | 极小 |
| `create_collection()` 建表 | **只第一次** | 一次性 |
| `embed_documents([5 条种子])` | **只第一次** | 5 次 embedding API 调用 |
| `insert(...)` 灌种子数据 | **只第一次** | 一次性 |
| `load_collection()` 装入内存索引 | 每次调用，已 load 时 no-op | 同进程极小，新进程几十毫秒 |
| `embed_query(error_msg)` 查询向量化 | **每次都算** | 1 次 embedding API 调用 |
| `search(...)` ANN 检索 | 每次都搜 | 极快（5 条数据） |
| `client.close()` 关连接 | 每次 | 几毫秒 |

唯一每次都跑的"重活"是 `embed_query`——因为查询文本不一样，必须每次都让 embedding 模型重新算，这是 RAG 检索的固有成本，跟向量库本身无关。

**重启服务后再次触发**：
- `data/checkpoint.sqlite` 保留：所有 thread 的 checkpoint 还在，传同一 `thread_id` 可接续上次状态。
- `data/milvus_demo.db/` 保留：种子数据不会重灌，新进程第一次检索会触发一次真正的 `load_collection`（毫秒级开销）。
- 完全重置：`rm -rf data/`。

## 关键依赖

| 包 | 版本 | 作用 |
|---|---|---|
| `langgraph` | `>=0.2,<0.3` | 状态机编排 |
| `langgraph-checkpoint-sqlite` | `>=2.0,<3.0` | SQLite Checkpointer，替代 PostgresSaver 的轻量方案 |
| `langchain-core` / `langchain-openai` | `0.3.x` | LLM 客户端 + Embedding 客户端 |
| `pymilvus[milvus_lite]` | `>=2.4.2` | 嵌入式 Milvus Lite |
| `langchain-milvus` | `>=0.1,<0.2` | LangChain 集成（实际未使用其 VectorStore，见下方踩坑记录） |

## 配置

`app/nodes.py` 顶部硬编码了 DashScope（阿里通义）的 API Key 和 base URL，**生产环境请改用环境变量**。Embedding 复用同一端点的 `text-embedding-v3` 模型。

## 踩坑记录

### 1. macOS Apple Silicon 上 venv 二进制架构不匹配

`pip install` 在 Rosetta 模式下被触发会装 x86_64 wheel，arm64 Python 加载时报：

```
ImportError: dlopen(...): tried '...': (mach-o file, but is an incompatible architecture
(have 'x86_64', need 'arm64'))
```

解决：所有 pip / python 命令都用 `arch -arm64` 前缀，强制 arm64 wheel。

### 2. langchain-milvus 0.2+ 强制升级 langchain-core 到 1.x

`pip install langchain-milvus` 默认拉 0.3.x，会把 `langchain-core` 升到 1.4，与 `langchain-openai 0.3.x`、`langgraph 0.2.x` 全冲突。
锁版本：`langchain-milvus>=0.1.0,<0.2.0` + `langgraph-checkpoint-sqlite>=2.0,<3.0`。

### 3. fork 污染 pymilvus 全局连接

`tester_node` 调 `subprocess.run` 启动子进程，gRPC 抛 warning：

```
Other threads are currently calling into gRPC, skipping fork() handlers
```

之后再用 `langchain-milvus` 的 `Milvus` 实例做 `similarity_search` 100% 报：

```
ConnectionNotExistException: should create connection first.
```

`pymilvus.connections` 是一个全局注册表，`langchain-milvus` 默认复用 `default` alias，fork 后这个 alias 的 gRPC channel 状态损坏，`disconnect` 也救不回来。

**解决**：放弃 `langchain-milvus.Milvus`，改用 `pymilvus.MilvusClient` 直连，每次检索新建 client 实例。`MilvusClient` 内部用唯一 alias 隔离连接。

### 4. Milvus Lite 老 collection 默认 released 状态

复用已有 DB 时，新建 `MilvusClient` 拿到的 collection 是 "released"（数据在磁盘但没装内存索引），直接 `search` 报：

```
MilvusException: Collection 'agent_error_cases' is in state 'released';
call load() before search/get/query
```

只有首次 `create_collection` 那条路径会隐式 load，第二次启动 / 第二次连入就会踩这个雷。

**解决**：每次 search 前显式 `client.load_collection(COLLECTION_NAME)`。已 load 的 collection 重复 load 是空操作，不会有副作用。

### 5. DashScope embedding 不接受 token-id 数组

`OpenAIEmbeddings` 默认会用 tiktoken 在本地把字符串切成整数 token-id 数组发出去，DashScope 的 OpenAI 兼容端点只认字符串，报：

```
InvalidParameter: Value error, contents is neither str nor list of str
```

**解决**：构造 `OpenAIEmbeddings` 时加 `check_embedding_ctx_length=False`，关闭本地切词。

## 这些设计选择的来由

- **为什么 SqliteSaver 而不是 MemorySaver？** 原代码注释写"暂用内存状态，可外挂 PostgresSaver"。SqliteSaver 是 LangGraph 原生的轻量方案，零额外服务、单文件落盘，适合 demo 和单机部署。
- **为什么 Milvus Lite 而不是 PostgresSaver 之类做 KB？** Milvus Lite 是嵌入式向量库，专为 RAG 检索设计；PostgresSaver 是 checkpoint 持久化，两者职责不同。这里是给 RAG 上下文做 ANN 检索。
- **为什么不用 `langchain-milvus.Milvus`？** 见踩坑 3。在有 fork 的场景下连接复用不稳。
