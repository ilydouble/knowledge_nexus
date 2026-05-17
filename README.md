# Knowledge Nexus

Knowledge Nexus 是一个从“文件管理”进化为“知识构建”的 AI 语义网盘系统。

核心原则：

- 物理存储受控：原始文件、下载、预览和权限仍由组织文件夹与对象存储严格管理。
- 逻辑链接自由：知识关系、个人笔记、双向链接和语义图谱可以在权限边界之上形成独立叠加层。
- 三层本体协作：L1 顶层知识定义秩序，L2 团队知识沉淀共识，L3 个人认知保留偏恋。

主要文档：

- [架构设计文档](./docs/architecture_design.md)
- [核心架构蓝图](./docs/core_architecture.md)
- [项目目录结构](./docs/project_structure.md)
- [本地开发指南](./docs/local-development.md)

## MVP 开发启动

当前推荐复用你本机已有的 `kg-*` Docker 基础设施，不重复启动数据库、图数据库、向量库或 MinIO。

### Host 开发模式

推荐使用 Conda 环境：

```bash
conda activate nexus
python --version  # Python 3.11.x
```

复制本地环境配置：

```bash
cp .env.local.example .env
```

确保这些容器已在运行：

- `kg-postgres`
- `kg-neo4j`
- `kg-redis`
- `kg-milvus`
- `kg-minio`

运行 API：

```bash
uvicorn apps.api.main:app --reload
```

运行 Web 控制台：

```bash
cd apps/web
npm run dev
```

### Docker Sidecar 模式

复制容器环境配置：

```bash
cp .env.docker.example .env
```

启动 Nexus sidecar 服务：

```bash
docker compose -f infrastructure/docker/docker-compose.yml up --build
```

默认 Compose 只启动 `nexus-api`、`nexus-worker`、`nexus-web`，并接入已有的外部 Docker network：`kg-network`。

### 验证

```bash
python3 -m pytest
npm run build --prefix apps/web
docker compose -f infrastructure/docker/docker-compose.yml config
```

真实外部组件集成测试需要显式开启：

```bash
RUN_INTEGRATION=1 DATABASE_URL=postgresql://admin:admin123@localhost:5433/smart_building python3 -m pytest tests/integration/test_postgres_repository.py
RUN_INTEGRATION=1 NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=admin123 python3 -m pytest tests/integration/test_neo4j_store.py
RUN_INTEGRATION=1 MILVUS_HOST=localhost MILVUS_PORT=19530 python3 -m pytest tests/integration/test_milvus_store.py
```

默认入口：

- Nexus API: http://localhost:8000
- Nexus Web Console: http://localhost:5173
- MinIO Console: http://localhost:9001

MinIO 本地开发登录：

- User: `minioadmin`
- Password: `minioadmin`

这些都是本地开发凭据，不能用于生产。

当前实现是 Phase 0/1 的可运行骨架：Cloudreve 作为可选物理网盘底座，Nexus 提供 FastAPI 语义后端、文件事件入队、文本解析/摘要/标签、个人 L3 链接、自动链接候选、权限过滤、Postgres 持久化、Neo4j 图谱适配器、Milvus 向量适配器和 GraphRAG 演示接口。

已知状态：Postgres 和 Neo4j 真实集成测试已通过；Milvus adapter 已实现，但当前 `kg-milvus` 实例在 collection 写入/加载时返回 DML channel/loading 错误，需要单独修复或重建 Milvus 实例后再验收。

Python 版本建议：当前推荐在 `nexus` Conda 环境使用 Python 3.11。原因是本机 Milvus 服务为 `milvusdb/milvus:v2.3.3`，对应 `pymilvus 2.3.x` 在 Python 3.11 上依赖组合更稳。

## 语义处理管道

完整的知识抽取流程：文件上传 → 内容解析 → 知识抽取 → 入库存储。

### 启动语义处理 Worker

```bash
# 1. 配置环境变量
# 编辑 .env 文件，设置：
# - CLOUDREVE_TOKEN (从 Cloudreve 获取)
# - OPENAI_API_KEY (用于 LLM 知识抽取，可选)

# 2. 启动 Worker
python -m nexus.worker
```

### 流程说明

```
Cloudreve 上传文件 → SSE 事件 → Worker 接收 → 下载文件 → 解析内容 → LLM 抽取知识 → Neo4j/Milvus 入库
```

### 支持的文件格式

| 格式 | 解析器 | 说明 |
|------|--------|------|
| PDF | pdfplumber | 提取文本，保留页面结构 |
| DOCX | python-docx | Word 文档 |
| TXT/MD/CSV/JSON | 内置 | 纯文本格式 |

### 知识抽取模板

系统根据文档类型自动选择抽取模板：

- **学术论文**: 研究问题、方法、实验、结论
- **技术文档**: 架构、组件、接口、依赖
- **会议纪要**: 决议、待办、参与者
- **报告**: 指标、进展、风险、建议

### 详细文档

- [语义处理管道](./docs/semantic_pipeline.md)
- [知识抽取 Skill](./knowledge-graph/SKILL.md)

## 测试

```bash
# 测试语义处理模块
python test_pipeline.py

# 运行单元测试
python -m pytest tests/
```

## 开发进度

详细进度请查看 [开发进度文档](./docs/progress.md)。

### 当前状态：Phase 1 完成 ✅

| 模块 | 状态 |
|------|------|
| Cloudreve SSE 事件监听 | ✅ |
| 文件下载 | ✅ |
| 内容解析 (PDF/DOCX/TXT) | ✅ |
| LLM 知识抽取 | ✅ |
| Neo4j 图谱存储 | ✅ |
| Milvus 向量存储 | ✅ |

### 快速测试

```bash
# 1. 确保 Cloudreve 和数据库服务运行
# 2. 配置 .env 中的 CLOUDREVE_TOKEN
# 3. 启动 Worker
python -m nexus.worker

# 4. 在 Cloudreve 上传文件
# 5. 观察 Worker 日志输出
```

预期日志输出：
```
INFO:nexus.worker:Processing file: cloudreve://my/document.pdf (event: create)
INFO:nexus.pipeline:Downloading file: cloudreve://my/document.pdf
INFO:nexus.pipeline:Parsing content: document.pdf
INFO:nexus.pipeline:Extracting knowledge (type: general)
INFO:nexus.worker:Successfully processed: entities=8, relations=5, chunks=12
```
