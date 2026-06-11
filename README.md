# Knowledge OS

Knowledge OS 是以知识生命周期为中心的 AI 知识管理系统。以 Cloudreve 为物理文件底座，以 Neo4j 知识图谱为语义层，通过受控的**候选→审核→入库**工作流保证知识质量，并通过 MCP 协议将图谱开放给 Pi-Agent / Claude Code 等 AI 智能体。

核心原则：

- **知识可控写入**：所有提取结果先进入候选池，经人工或 Agent 审核后才真正写入图谱。
- **物理存储受控**：原始文件、下载、预览和权限仍由 Cloudreve 与对象存储管理。
- **图谱优先，嵌入可选**：默认只做图谱提取（零额外 API 成本），向量嵌入按需开启。
- **分层架构**：`knowledge_os`（业务逻辑） / `core`（基础设施） / `apps`（入口） 三层分离。

---

## 快速启动

### 前置要求

确保以下容器正在运行：

```bash
docker ps --filter name=kg-   # 需要 kg-postgres、kg-neo4j
```

激活 Python 环境：

```bash
conda activate nexus
```

首次配置：

```bash
cp .env.local.example .env
# 至少设置：
#   ZHIPU_API_KEY=your_key   ← LLM 知识抽取（必须）
#   CLOUDREVE_TOKEN=...       ← 从 Cloudreve 获取
```

### 一键启动

```bash
./start.sh            # 启动全部服务
./start.sh --no-mcp   # 不启动 MCP Server
./start.sh --no-web   # 不启动前端
./stop.sh             # 停止所有服务
```

### 手动启动各服务

**① FastAPI 后端**

```bash
uvicorn apps.api.main:app --reload
# → http://localhost:8000
```

**② Web 控制台**

```bash
cd apps/web && npm run dev
# → http://localhost:5173
```

**③ Worker（Cloudreve 事件监听 + 定时扫描）**

```bash
python -m apps.worker.main
```

**④ MCP Server（供 Pi-Agent / Claude Code 接入）**

```bash
python -m apps.mcp.server
```

Claude Code 配置（`~/.claude/claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "knowledge-os": {
      "command": "/opt/miniconda3/envs/nexus/bin/python",
      "args": ["-m", "apps.mcp.server"],
      "cwd": "/path/to/knowledge_nexus"
    }
  }
}
```

详细说明见 [docs/mcp_setup.md](./docs/mcp_setup.md)。

---

## 架构概览

```
Cloudreve（文件存储）
    ↓ SSE 事件 / 周期扫描
apps/worker/main.py
    ↓ FileGate（格式过滤）
    ↓ ContentParser（PDF / DOCX / Excel / TXT / MD）
    ↓ DocumentClassifier（7 类自动分类）
    ↓ KnowledgeExtractor（富本体模板 + LLM + Map-Reduce）
    ↓
knowledge_os/application/extraction_pipeline.py
    → 候选批次（Postgres candidate_batches / candidate_items）
    ↓ 人工 / Pi-Agent 审核
knowledge_os/application/services.py  commit_candidate_batch()
    ↓
Neo4j（实体 + 关系图谱）   Postgres（graph_evidence + 文档元数据）
    ↑                              ↑
    └──── apps/mcp/server.py ──────┘
                 ↑
     Pi-Agent / Claude Code 等 AI 智能体
```

### 目录结构

```
knowledge_nexus/
├── knowledge_os/          ← 主系统（业务逻辑，不依赖具体存储实现）
│   ├── domain/            (领域模型：CandidateBatch, CandidateItem, GraphEvidence)
│   ├── application/       (services, governance, graph_qa, extraction_pipeline)
│   ├── infrastructure/    (KnowledgeOSStore 实现：memory / postgres)
│   └── interfaces/        (api.py → Admin REST, mcp.py → MCP Tools)
├── core/                  ← 纯基础设施（存储驱动、服务库）
│   ├── cloudreve/         (OAuth 客户端)
│   ├── graph/             (Neo4j 驱动封装)
│   ├── vector/            (Milvus 驱动封装)
│   ├── repositories/      (NexusRepository：memory / postgres)
│   ├── services/          (pipeline, scanner, embedding, parser, extractor…)
│   ├── agents/            (Strands Agents：graph_qa, classifier, schema, completion)
│   ├── models.py          (IngestionJob, SemanticDocument…)
│   └── settings.py
├── apps/
│   ├── api/               (factory.py: create_application(), main.py: FastAPI 入口)
│   ├── worker/            (main.py: Worker, 三循环：SSE + 扫描 + 批处理)
│   ├── mcp/               (server.py: MCP Server 入口)
│   └── web/               (React 前端：仪表盘 + 候选审核 + 图谱 + Cloudreve)
├── tests/
│   ├── unit/
│   └── integration/
└── scripts/
    └── init_postgres.py
```

---

## Pi-Agent 典型工作流

```
# 1. 触发抽取
run_candidate_extraction("cloudreve://my/report.pdf", instructions="...")

# 2. 审查候选
get_candidate_batch(batch_id)
update_candidate_items(batch_id, [...])   # 逐条接受/拒绝

# 3. 预览变更
preview_graph_changes(batch_id)           # 查看即将写入的 diff

# 4. 写入图谱
commit_candidate_batch(batch_id)          # 幂等 MERGE → Neo4j + graph_evidence

# 5. 问答
ask_knowledge_graph("谁和某公司签了合同?")

# 6. 治理
get_knowledge_dashboard()
list_candidate_batches(status="pending")
bulk_review_batch(batch_id, action="accept")
```

---

## Admin REST API

| 端点 | 描述 |
|---|---|
| `GET  /api/admin/dashboard` | 批次/条目/证据聚合统计 + 告警 |
| `GET  /api/admin/candidates` | 候选批次列表（可过滤 status/source_uri） |
| `POST /api/admin/candidates/extract` | 触发文件抽取，生成候选批次 |
| `GET  /api/admin/candidates/{id}` | 批次详情（含所有条目） |
| `POST /api/admin/candidates/{id}/accept-all` | 批量接受所有 pending 条目 |
| `POST /api/admin/candidates/{id}/reject-all` | 批量拒绝所有 pending 条目 |
| `POST /api/admin/candidates/{id}/preview` | 预览图谱变更（不写入） |
| `POST /api/admin/candidates/{id}/commit` | 提交入库（Neo4j + graph_evidence） |
| `GET  /api/admin/graph/stale` | 陈旧证据报告 |
| `GET  /api/graph` | Neo4j 全图 / 文档邻域 |
| `GET  /health` | 健康检查 |

---

## 语义处理管道

### 文档分类（7 种类型）

| 类型 | 触发条件 | 提取策略 |
|---|---|---|
| `academic_paper` | 含 abstract/doi/论文 | LLM + Map-Reduce |
| `technical_doc` | 含 api/readme/架构 | LLM + Map-Reduce |
| `meeting_minutes` | 含 会议/纪要/minutes | LLM |
| `report` | 含 报告/月报/review | LLM + Map-Reduce |
| `contract` | 含 合同/协议/甲方 | LLM |
| `email` | 含 From:/Subject: | LLM |
| `tabular_data` | `.xlsx/.xls` 或大型 CSV | 结构摘要 |
| `general` | 兜底 | LLM |

### 支持的文件格式

| 格式 | 解析器 |
|---|---|
| PDF | pdfplumber |
| DOCX | python-docx |
| XLSX / XLS | openpyxl（只提取表头 + 样本行） |
| TXT / MD / CSV / JSON / YAML | TextParser |

### 向量嵌入（可选）

```bash
VECTOR_BACKEND=milvus   # 重启 API + Worker 生效（默认 none）
```

---

## 测试

```bash
# 单元测试（不依赖外部服务，约 5 秒）
python -m pytest tests/unit/ -q --ignore=tests/unit/test_cloudreve_client.py

# 集成测试（需要真实数据库）
RUN_INTEGRATION=1 python -m pytest tests/integration/test_postgres_repository.py
RUN_INTEGRATION=1 python -m pytest tests/integration/test_neo4j_store.py
```

---

## 当前状态

| 模块 | 状态 |
|---|---|
| Cloudreve OAuth + SSE 事件监听 | ✅ |
| 周期全盘扫描（每 10 分钟）+ 批处理队列 | ✅ |
| FileGate 格式过滤 | ✅ |
| 内容解析（PDF / DOCX / Excel / TXT） | ✅ |
| 文档自动分类（7 类） | ✅ |
| kgraph 上下文 + 来源证据 | ✅ |
| 富本体知识图谱提取（LLM + Map-Reduce） | ✅ |
| **候选抽取 → 审核 → 预览 → 入库工作流** | ✅ |
| Neo4j 图谱存储（幂等 MERGE + Stub 补全） | ✅ |
| Postgres 候选批次 + 证据存储 | ✅ |
| Admin REST API（仪表盘 + 批次管理） | ✅ |
| MCP Server（Pi-Agent 工具集） | ✅ |
| 图谱问答（GraphQA，关键词 → Neo4j 邻域） | ✅ |
| 治理服务（dashboard、批量审核、陈旧报告） | ✅ |
| 向量嵌入（BigModel embedding-3，可选） | ✅ 按需开启 |
| Web 控制台（仪表盘 + 候选审核 + 图谱可视化） | ✅ |

Knowledge Nexus 是一个从“文件管理”进化为“知识构建”的 AI 语义网盘系统。以 Cloudreve 为物理文件底座，以 Neo4j 知识图谱为语义叠加层，通过 MCP 协议将图谱开放给 Claude Code 等 AI 智能体。

核心原则：

- **物理存储受控**：原始文件、下载、预览和权限仍由 Cloudreve 与对象存储管理。
- **逻辑链接自由**：知识关系、实体图谱在权限边界之上作为独立叠加层生长。
- **图谱优先，嵌入可选**：默认只做图谱提取（零额外 API 成本），向量嵌入按需开启。
- **三层本体协作**：L1 顶层知识定义秩序，L2 团队知识沉淀共识，L3 个人认知保留偏恋。

主要文档：

- [架构状态看板](./docs/architecture-status.html)
- [本地开发指南](./docs/local-development.md)
- [语义处理管道](./docs/semantic_pipeline.md)
- [MCP Server 接入指南](./docs/mcp_setup.md)

---

## 快速启动

### 前置要求

确保以下容器正在运行（复用 `kg-*` 基础设施）：

```bash
docker ps --filter name=kg-   # 需要 kg-postgres、kg-neo4j、kg-redis
```

激活 Python 环境：

```bash
conda activate nexus
```

首次配置（复制后编辑 `.env`）：

```bash
cp .env.local.example .env
# 至少设置：
#   ZHIPU_API_KEY=your_key   ← LLM 知识抽取（必须）
#   CLOUDREVE_TOKEN=...       ← 从 Cloudreve 获取
```

### 启动各服务

**① FastAPI 后端**

```bash
uvicorn apps.api.main:app --reload
# → http://localhost:8000
```

**② Web 控制台**

```bash
cd apps/web && npm run dev
# → http://localhost:5173
```

**③ Worker（文件处理核心）**

```bash
python -m nexus.worker
# 启动后自动：SSE 监听 + 每 10 分钟全盘扫描 + 每 30 秒处理队列（每批 3 个）
```

**④ MCP Server（供 Claude Code 等 AI 智能体接入）**

```bash
python -m nexus.mcp_server
```

Claude Code 配置（`~/.claude/claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "knowledge-nexus": {
      "command": "/opt/miniconda3/envs/nexus/bin/python",
      "args": ["-m", "nexus.mcp_server"],
      "cwd": "/path/to/knowledge_nexus"
    }
  }
}
```

详细说明见 [docs/mcp_setup.md](./docs/mcp_setup.md)。

---

## 架构概览

```
Cloudreve（文件存储 + 全文检索）
    ↓ SSE 事件 / 周期扫描
Worker
    ↓ FileGate（格式过滤）
    ↓ ContentParser（PDF / DOCX / Excel / TXT / MD / CSV）
    ↓ DocumentClassifier（7 类自动分类）
    ↓ KGraphContextBuilder（高相关 section/window + 来源证据 JSON）
    ↓ KnowledgeExtractor（富本体模板 + LLM + Map-Reduce）
    ↓
Neo4j（实体 + 关系图谱）        Postgres（文档摘要 + 标签 + 状态）
    ↑                                ↑
    └──────────── MCP Server ────────┘
                   ↑
           Claude Code / 其他 AI 智能体
```

### 模块连接方式

| 模块 | 输入 | 输出 | 连接协议 |
|---|---|---|---|
| Cloudreve → Worker | SSE 事件流 / OAuth Token | 文件 bytes | HTTP SSE + REST |
| FileGate → Pipeline | 文件名 | GateResult（处理/跳过） | 函数调用 |
| ContentParser → Classifier | 文件 bytes | 文本 + file_type + chunks | 函数调用 |
| Classifier → Extractor | 文本 + file_type | doc_type + strategy | 函数调用 |
| Classifier → KGraphContextBuilder | ParsedContent + 分类结果 | 可追踪 kgraph 上下文 JSON | 函数调用 |
| KGraphContextBuilder → Extractor | 高相关 sections/windows | 过滤后的抽取文本 + hints | 函数调用 |
| Extractor → Neo4j | 文本 + 本体模板 | 实体 + 关系 JSON | Bolt 协议 |
| Extractor → Postgres | 摘要 + 标签 + chunks | SemanticDocument | psycopg3 |
| MCP Server → Neo4j | 关键词 / URI | 图谱节点 + 边 | Bolt 协议 |
| MCP Server → Postgres | — | 文档列表 + 摘要 | psycopg3 |
| FastAPI → Postgres | HTTP 请求 | 任务状态 + 文档 | HTTP REST |
| FastAPI → Neo4j | URI 查询 | 图谱邻域 | Bolt 协议 |
| DocLinker → Repository | 文档实体重叠 | 文档间 typed links | 函数调用 |

---

## 语义处理管道

### 文档分类（7 种类型）

系统根据文件扩展名、文件名关键词、内容前 600 字自动分类：

| 类型 | 触发条件 | 提取策略 |
|---|---|---|
| `academic_paper` | 含 abstract/doi/论文 | LLM + Map-Reduce |
| `technical_doc` | 含 api/readme/架构 | LLM + Map-Reduce |
| `meeting_minutes` | 含 会议/纪要/minutes | LLM |
| `report` | 含 报告/月报/review | LLM + Map-Reduce |
| `contract` | 含 合同/协议/甲方 | LLM |
| `email` | 含 From:/Subject: | LLM |
| `tabular_data` | `.xlsx/.xls` 或大型 CSV | 结构摘要（不读数据行） |
| `general` | 无匹配时兜底 | LLM |

### 支持的文件格式

| 格式 | 解析器 | 说明 |
|---|---|---|
| PDF | pdfplumber | 提取文本，按段落分块 |
| DOCX | python-docx | Word 文档全文 |
| XLSX / XLS / XLSM | openpyxl | 只提取表头 + 行数 + 3 行样本，不读数据 |
| TXT / MD / CSV / JSON / YAML | TextParser | 纯文本，1,000 字/块 |

### 向量嵌入（可选）

默认关闭（`VECTOR_BACKEND=none`），开启只需修改 `.env`：

```bash
VECTOR_BACKEND=milvus   # 重启 API + Worker 生效
```

开启后使用 BigModel `embedding-3`（2048 维），每次处理文件自动批量嵌入所有文本块。

### 文档关联（按需触发）

处理完成后的文档可以通过共享实体自动建立文档间关联：

```bash
curl -X POST "http://localhost:8000/api/documents/link?min_shared_entities=1"
```

当前 `DocLinker` 默认使用实体重叠生成可解释链接，并将结果写入 repository 的 `knowledge_links`。如果调用方显式提供 LLM API key，服务层也支持把关系定型为 `引用`、`补充`、`扩展`、`冲突` 或 `相似`。

---

## 测试

```bash
# 单元测试（不依赖外部服务，约 1 秒）
conda run -n nexus python -m pytest tests/unit/ -q

# 集成测试（需要真实数据库）
RUN_INTEGRATION=1 python -m pytest tests/integration/test_postgres_repository.py
RUN_INTEGRATION=1 python -m pytest tests/integration/test_neo4j_store.py
```

---

## 当前状态：Phase 2 完成 ✅

| 模块 | 状态 |
|---|---|
| Cloudreve OAuth + SSE 事件监听 | ✅ |
| 周期全盘扫描（每 10 分钟） | ✅ |
| FileGate 格式过滤 | ✅ |
| 内容解析（PDF / DOCX / Excel / TXT） | ✅ |
| 文档自动分类（7 类） | ✅ |
| kgraph 上下文契约（来源证据 + section 过滤 + hints） | ✅ |
| 富本体知识图谱提取 | ✅ |
| 文档间实体重叠关联（DocLinker） | ✅ |
| Map-Reduce 长文处理 | ✅ |
| Neo4j 图谱存储（幂等 MERGE） | ✅ |
| Postgres 文档元数据存储 | ✅ |
| MCP Server（5 个工具，供 Claude Code 接入） | ✅ |
| 向量嵌入（BigModel embedding-3，可选） | ✅ 按需开启 |
| Web 控制台（文件状态、图谱可视化） | ✅ |
