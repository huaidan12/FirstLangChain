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
main.py                   项目根聚合入口，mount 两个子应用
projects/
  ├── coder/              LangGraph 代码生成 Agent
  │   ├── main.py         FastAPI 子应用（/run_task）
  │   ├── workflow.py     StateGraph + SqliteSaver 挂载
  │   ├── nodes.py        coder_node / tester_node + LLM 客户端
  │   ├── sandbox.py      subprocess 沙箱
  │   └── knowledge_base.py  Milvus Lite 封装（建表/灌种子/检索）
  └── bookkeeper/         财务报销结构化提取
      └── main.py         FastAPI 子应用（/api/expense/extract）
data/                     运行时生成（已 gitignore）
  ├── checkpoint.sqlite   LangGraph 状态快照
  └── milvus_demo.db/     Milvus Lite 数据目录
requirements.txt
```

后文所有 `app/xxx.py` 的路径引用都对应 `projects/coder/xxx.py`，代码搬迁后没改字段/逻辑，行号也保持一致。

## 安装

> ⚠️ **macOS 用户注意架构**：本仓库的 venv 历史曾有部分 wheel 是 x86_64 的，在 Apple Silicon 上 import 会报 `incompatible architecture`。所有 pip / python 命令都建议显式 `arch -arm64` 前缀。

依赖分两份：

| 文件 | 场景 | 内容 |
|---|---|---|
| `requirements.txt` | **Vercel 部署**（自动读取） | 只装 bookkeeper 需要的包 |
| `requirements-local.txt` | **本地 / 长驻托管** | 完整依赖，含 LangGraph + Milvus Lite |

本地开发要跑 coder，装完整版：

```bash
python3 -m venv venv
arch -arm64 ./venv/bin/pip install -r requirements-local.txt
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

项目根 `main.py` 是聚合入口，一条命令启动：

```bash
arch -arm64 ./venv/bin/python -m uvicorn main:app --reload
```

**当前默认只挂载 bookkeeper**（为了兼容 Vercel Serverless）：

- `POST /bookkeeper/api/expense/extract` —— 财务报销结构化提取
- `GET /` —— 列出可用服务

> ⚠️ **coder 默认被注释掉了**。它依赖 SqliteSaver / Milvus Lite 写本地盘，Vercel 这类 Serverless 环境跑不了。换到长驻环境（Render / Railway / Fly.io / VM）后，在 `main.py` 里放开 `coder_app` 的 import 和 mount 两行即可恢复。届时新增的端点：
>
> - `POST /coder/run_task` —— LangGraph 代码生成 Agent

只想单独跑其中一个，也可以直接指到子应用：

```bash
# 只跑 coder
arch -arm64 ./venv/bin/python -m uvicorn projects.coder.main:app --reload
# 只跑 bookkeeper
arch -arm64 ./venv/bin/python -m uvicorn projects.bookkeeper.main:app --reload
```

调用：

```bash
curl -X POST http://localhost:8000/coder/run_task \
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
curl -X POST http://localhost:8000/coder/run_task \
  -H 'Content-Type: application/json' \
  -d '{"requirement": "...", "thread_id": "a1b2c3..."}'
```

## 部署到 Vercel（当前默认）

项目根有一份 `vercel.json`，把 `main.py` 声明为 Serverless 入口。**注意：只有 bookkeeper 能上 Vercel**，coder 依赖本地磁盘（SqliteSaver / Milvus Lite），在 Serverless 的只读文件系统里会崩在 import 阶段，所以 `main.py` 里 coder 的挂载已经注释掉了。

### 步骤

1. `git push` 触发 Vercel 自动构建，或用 `vercel` CLI 一键部署
2. Vercel 会自动读取根 `requirements.txt`（精简版）+ `vercel.json`
3. 在 Vercel 控制台 → Settings → Environment Variables 里配 API Key（如果你之前从 `nodes.py` 里改回环境变量的话）

### 部署后访问

```bash
# 服务索引
curl https://<project>.vercel.app/

# Bookkeeper
curl -X POST https://<project>.vercel.app/bookkeeper/api/expense/extract \
  -H 'Content-Type: application/json' \
  -d '{"raw_text": "昨天在星巴克花了 38 元买咖啡"}'
```

### Vercel 限制清单

- **超时**：Hobby 层 10s、Pro 60s。DashScope 慢时可能被切
- **打包体积**：解压后 250 MB 上限。当前精简 `requirements.txt` 稳妥在限内；如果为了跑 coder 把完整依赖塞进来，pymilvus 会把包撑爆
- **没有持久盘**：所以 coder 必须继续注释

### 如何恢复 coder（换到长驻环境后）

1. 把 `main.py` 里 `from projects.coder.main import app as coder_app` 和 `app.mount("/coder", coder_app)` 两行放开
2. 用 `requirements-local.txt` 替换 `requirements.txt`（或直接部署时指定完整依赖）
3. 部署到下面的 Render（或类似长驻环境）

## 部署到 Render

代码里 `PORT` / `reload` 判断就是照 Render 写的。Render 提供长驻容器 + Persistent Disk，正好匹配本项目对 `data/` 的可写、可持久要求；Vercel / Netlify 这类 Serverless 平台不适用（`/var/task` 只读、跨请求丢盘、冷启动会重灌 Milvus 种子）。

### 1. 建 Web Service

- **Runtime**: Python 3(与本地一致，建议 3.11+)
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**（二选一）：
  ```
  uvicorn main:app --host 0.0.0.0 --port $PORT
  ```
  或直接：
  ```
  python main.py
  ```
- **Environment Variables**: `PORT` 由 Render 自动注入，不用手填。API Key 目前是硬编码在 `projects/*/nodes.py` 里，先跑通没问题；上生产之前建议改成 `os.getenv("OPENAI_API_KEY")` 再在 Render 面板配环境变量。

### 2. 挂 Persistent Disk（必须）

`projects/coder/workflow.py` 的 `DATA_DIR` 会解析到**项目根目录**下的 `data/`，Render 部署时是 `/opt/render/project/src/data`。要让 `checkpoint.sqlite` 和 `milvus_demo.db/` 重启不丢，就把 Persistent Disk 挂到这个路径：

| 字段 | 值 |
|---|---|
| Mount Path | `/opt/render/project/src/data` |
| Size | 1 GB 起够用（Milvus Lite 种子极小，SQLite 也不大） |

不挂盘的后果：容器重启后 `thread_id` 全丢；每次冷启动都要重跑一次种子灌入，多花 5 次 embedding API 调用。

### 3. 验证

部署完 Render 给一个 `https://<name>.onrender.com` 域名：

```bash
# 服务索引（列出可用子应用）
curl https://<name>.onrender.com/

# Coder
curl -X POST https://<name>.onrender.com/coder/run_task \
  -H 'Content-Type: application/json' \
  -d '{"requirement": "写一个 execute() 函数，打印从 1 加到 100 的结果"}'

# Bookkeeper
curl -X POST https://<name>.onrender.com/bookkeeper/api/expense/extract \
  -H 'Content-Type: application/json' \
  -d '{"raw_text": "昨天在星巴克花了 38 元买咖啡"}'
```

Swagger 文档：`/coder/docs` 和 `/bookkeeper/docs`（根路径 `/docs` 是聚合 app 的空文档，没意义）。

### 4. Free 层的两个坑

- **Free 层没有 Persistent Disk**，只能用付费方案挂盘；否则容器重建即失忆。
- **Free 层 15 分钟空闲会休眠**，第一次请求触发冷启动 + Milvus load_collection + LangGraph 编译，可能 10~20 秒才响应。生产建议直接用 Starter 及以上并挂盘。

## RAG 数据流转

整条链路有三个独立角色，谁存什么、谁吃什么要分清楚：

| 角色 | 存储内容 | 在链路里干什么 |
|---|---|---|
| **业务 DB**（MySQL/PG，本 demo 用硬编码 `SEED_CASES` 模拟）| 历史报错案例的"权威原文" | 数据主权方，新增/修改在这里发生 |
| **向量数据库**（Milvus）| 同一份数据的"向量 + 原文冗余" | 语义召回索引，给 Agent 查相似 |
| **LLM**（DashScope）| 不存东西 | 拿召回的原文做推理 |

**关键点：LLM 从来不吃向量，吃的是文本。** 向量只是"找相似"的中间产物，召回后会被丢掉，只把对应的原文塞进 prompt。

### 写入阶段（离线/异步）

```
业务 DB 文本 ──► [Embedding 模型] ──► 向量 ──┐
                                              ├──► Milvus（同一行同时存 vector + text）
业务 DB 文本 ───────────────────────────────  ┘
```

对应代码 `app/knowledge_base.py:83`：

```python
rows = [{"vector": vec, "text": doc.page_content} for vec, doc in zip(...)]
#         ^^^^^^^^^^^^                              ^^^^^^^^^^^^^^^^^^^^^^^^
#         给搜索用                                   给 LLM 读
```

### 检索阶段（在线/热路径）

```
当前 error_msg ──► [Embedding 模型] ──► 查询向量 ──► Milvus 相似度搜索
                                                            │
                                          Top-K 命中行的「原文 text」
                                                            │
                                                            ▼
                                            ChatPromptTemplate 的 {rag_context}
                                                            │
                                                            ▼
                                                       LLM.invoke()
```

对应代码：

- `app/knowledge_base.py:103` `embed_query(error_msg)` —— 文本转查询向量
- `app/knowledge_base.py:104-109` `client.search(..., output_fields=["text"])` —— 注意拿的是 `text` 不是 `vector`
- `app/knowledge_base.py:119` 把命中原文拼成可读 block
- `app/nodes.py:54` `{rag_context}` 占位符把原文注入 prompt

### 写入和查询必须用同一个 embedding 模型

`app/knowledge_base.py:18-25` 写入和 `:103` 查询共用同一个 `OpenAIEmbeddings` 实例（`text-embedding-v3` / 1024 维）。**生产换模型必须重建 collection**，不能新旧向量混用——它们处在不同的向量空间，距离没有意义。

### 生产部署：同步要从推理热路径剥离

本 demo 把"建表 + 灌种子"塞在第一次检索的副作用里（`_ensure_collection_and_seed`），生产不能这样做：

```
                ┌────────────────────────┐
                │   业务 DB (MySQL/PG)    │  ← 数据主权方
                └───────────┬────────────┘
                            │
                            │ 定时/CDC 同步（独立进程或 CronJob）
                            ▼
                ┌────────────────────────┐
                │   Milvus Standalone     │  ← 持久化向量副本
                │   （挂 PVC / 对象存储） │     重启不丢
                └───────────┬────────────┘
                            │ 检索（热路径，只读）
                            ▼
                ┌────────────────────────┐
                │   Agent 服务            │  ← 重启不重灌
                │   (coder_node 等)       │
                └────────────────────────┘
```

- **同步任务**：定时全量（量小）/ 定时增量（基于 `updated_at` 水位）/ CDC 实时（Canal、Debezium）三选一。
- **重启不需要重灌**：Milvus 持久化在磁盘/对象存储上，`if client.has_collection: return` 这一守卫就够了（见 `app/knowledge_base.py:69`）。
- **检索热路径绝不碰业务 DB**：`retrieve_similar_cases` 只查 Milvus，不要每次请求都去 DB 校验差异。
- **容器化部署**：Milvus Lite 的 `data/milvus_demo.db` 必须挂持久卷，否则 Pod 重建即丢；生产建议直接换 Milvus Standalone/Cluster。

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
