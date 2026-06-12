# Knowledge OS

Knowledge OS 是以知识生命周期为中心的 AI 知识管理系统。以 Cloudreve 为物理文件底座，以 Neo4j 知识图谱为语义层，通过受控的**候选→审核→入库**工作流保证知识质量，并向 AI 智能体开放：Claude Code 等原生 MCP 客户端走 MCP Server，[pi coding agent](https://github.com/earendil-works/pi) 走自带的 pi Skill。

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

**④ MCP Server（供 Claude Code 等原生 MCP 客户端接入）**

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
    ↓ KnowledgeExtractor（本体模板 + LLM + Map-Reduce）
    ↓
knowledge_os/application/extraction_pipeline.py
    → 候选批次（Postgres candidate_batches / candidate_items）
    ↓ 人工 / Pi-Agent 审核
knowledge_os/application/services.py  GraphCommitService.commit()
    ↓
Neo4j（实体 + 关系图谱）   Postgres（graph_evidence）
    ↑                              ↑
    └──── apps/mcp/server.py ──────┘
                 ↑
     Pi-Agent / Claude Code 等 AI 智能体
```

### 目录结构

```
knowledge_nexus/
├── knowledge_os/          ← 主系统（业务逻辑，不依赖具体存储实现）
│   ├── domain/            (CandidateBatch, CandidateGraphItem, GraphEvidence…)
│   ├── application/       (extraction_pipeline, services, governance, graph_qa)
│   ├── infrastructure/    (KnowledgeOSStore 实现：memory / postgres)
│   └── interfaces/        (api.py → Admin REST, mcp.py → MCP Tools)
├── core/                  ← 纯基础设施（存储驱动、服务库）
│   ├── cloudreve/         (OAuth 客户端)
│   ├── graph/             (Neo4j 驱动封装)
│   ├── vector/            (Milvus 驱动封装)
│   ├── repositories/      (NexusRepository：jobs + links；memory / postgres)
│   ├── services/          (file_gate, scanner, embedding, content_parser,
│   │                       document_classifier, knowledge_extractor, template_adapter)
│   ├── agents/            (graph_qa_agent, classifier_agent)
│   ├── models.py          (IngestionJob, KnowledgeLink, KnowledgeLayer…)
│   └── settings.py
├── apps/
│   ├── api/               (factory.py: create_application(), main.py: FastAPI 入口)
│   ├── worker/            (main.py: Worker，三循环：SSE + 扫描 + 批处理)
│   ├── mcp/               (server.py: MCP Server 入口)
│   └── web/               (React 前端：仪表盘 / 候选审核 / 图谱 / 问答 / Cloudreve)
├── data/
│   ├── ontology/templates/ (YAML 本体模板，如 smart_campus.yaml)
│   └── runtime/            (Cloudreve OAuth tokens，运行时生成)
├── infrastructure/docker/  (docker-compose.yml 启动 Postgres / Neo4j / Redis)
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
| `GET  /health` | 健康检查 |
| `GET  /api/admin/dashboard` | 批次/条目/证据聚合统计 |
| `GET  /api/admin/candidates` | 候选批次列表（可过滤 status / source_uri） |
| `POST /api/admin/candidates/extract` | 触发文件抽取，生成候选批次 |
| `GET  /api/admin/candidates/{id}` | 批次详情（含所有 CandidateGraphItem） |
| `PATCH /api/admin/candidates/{id}` | 逐条审核（`{edits:[{item_id, status}]}`） |
| `POST /api/admin/candidates/{id}/preview` | 预览图谱变更（不写入） |
| `POST /api/admin/candidates/{id}/commit` | 提交入库（Neo4j MERGE + graph_evidence） |
| `GET  /api/admin/graph/evidence` | 查询图谱条目的证据溯源 |
| `GET  /api/admin/graph/stale` | 陈旧证据报告 |
| `GET  /api/graph` | Neo4j 全图 / 文档 1-hop 邻域 |
| `POST /api/graph/ask` | 图谱自然语言问答（Agent3） |
| `GET  /api/auth/cloudreve/status` | Cloudreve OAuth 授权状态 |
| `GET  /api/auth/cloudreve/start` | 发起 OAuth 授权跳转 |
| `GET  /api/cloudreve/scan/status` | 扫描状态 |
| `POST /api/cloudreve/scan` | 触发全量文件扫描 |

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
| 内容解析（PDF / DOCX / Excel / TXT / MD） | ✅ |
| 文档自动分类（7 类） | ✅ |
| 本体模板知识图谱提取（LLM + Map-Reduce） | ✅ |
| **候选抽取 → 审核 → 预览 → 入库工作流** | ✅ |
| Neo4j 图谱存储（幂等 MERGE） | ✅ |
| Postgres 候选批次 + 证据溯源存储 | ✅ |
| Admin REST API（仪表盘 + 批次管理） | ✅ |
| MCP Server（Pi-Agent 工具集） | ✅ |
| 图谱问答（Agent3，Neo4j 邻域 + 向量检索） | ✅ |
| 治理服务（dashboard、陈旧报告） | ✅ |
| 向量嵌入（BigModel embedding-3，可选） | ✅ 按需开启 |
| Web 控制台（仪表盘 / 候选审核 / 图谱 / 问答 / Cloudreve） | ✅ |

