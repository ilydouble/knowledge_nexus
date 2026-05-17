# Knowledge Nexus 开发进度

## 当前状态：Phase 1 语义处理管道完成

**更新时间：** 2026-05-15

---

## 已完成功能

### 1. Cloudreve 集成 ✅

| 功能 | 状态 | 说明 |
|------|------|------|
| SSE 事件监听 | ✅ 完成 | 监听文件 create/update/delete 事件 |
| 文件下载 | ✅ 完成 | 通过 API 下载文件内容 |
| Token 认证 | ✅ 完成 | Bearer Token 认证 |

### 2. 内容解析服务 ✅

| 格式 | 状态 | 解析器 |
|------|------|--------|
| PDF | ✅ 完成 | pdfplumber |
| DOCX | ✅ 完成 | python-docx |
| TXT/MD | ✅ 完成 | 内置解析器 |
| CSV/JSON | ✅ 完成 | 内置解析器 |

**功能：**
- 自动格式检测
- 文本分块 (chunking)
- 元数据提取

### 3. 知识抽取服务 ✅

| 功能 | 状态 | 说明 |
|------|------|------|
| LLM 抽取 | ✅ 完成 | OpenAI GPT-4o-mini |
| 本体构建 | ✅ 完成 | 整合 knowledge-graph skill |
| 文档模板 | ✅ 完成 | 学术/技术/会议/报告 |
| Mock 抽取 | ✅ 完成 | 无 API Key 时的降级方案 |

**抽取内容：**
- 文档摘要
- 关键词标签
- 实体（人、组织、项目、技术等）
- 关系（依赖、引用、归属等）
- 关键观点

### 4. 存储层 ✅

| 存储系统 | 状态 | 用途 |
|----------|------|------|
| Neo4j | ✅ 完成 | 图谱存储（实体、关系） |
| Milvus | ✅ 完成 | 向量存储（文本块嵌入） |
| PostgreSQL | ✅ 完成 | 元数据存储 |
| Redis | ✅ 完成 | 队列/缓存 |

### 5. Worker 服务 ✅

| 功能 | 状态 |
|------|------|
| SSE 事件监听 | ✅ |
| 事件过滤 | ✅ |
| 文件处理管道 | ✅ |
| 错误处理 | ✅ |
| 日志输出 | ✅ |

### 6. API 接口 ✅

| 端点 | 功能 |
|------|------|
| `/health` | 健康检查 |
| `/api/ingestion/sync` | 手动触发处理 |
| `/api/ingestion/demo-index` | 演示索引 |
| `/api/files/knowledge` | 查询文件知识 |
| `/api/links` | 创建链接 |
| `/api/graph/neighborhood` | 图谱邻居查询 |
| `/api/search/semantic` | 语义搜索 |
| `/api/graphrag/ask` | GraphRAG 问答 |

---

## 待完成功能

### Phase 2 增强

| 功能 | 优先级 | 说明 |
|------|--------|------|
| OpenAI Embeddings | 高 | 替换确定性嵌入 |
| 图片 OCR | 中 | 图片文件内容提取 |
| 音频转写 | 中 | 音频文件转文本 |
| 增量更新 | 中 | 仅处理变更部分 |
| 自动链接推荐 | 中 | 基于相似度推荐 |

### Phase 3 AI Agent

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 知识问答 | 高 | GraphRAG 增强版 |
| 知识巡检 | 中 | 发现知识缺口 |
| 冲突检测 | 中 | 发现矛盾信息 |
| 跨项目复用 | 低 | 经验知识迁移 |

---

## 技术栈

### 后端
- **框架：** FastAPI
- **语言：** Python 3.11
- **LLM：** OpenAI API (GPT-4o-mini)
- **图谱：** Neo4j
- **向量：** Milvus
- **数据库：** PostgreSQL
- **缓存：** Redis

### 前端
- **框架：** React + Vite
- **UI：** Material-UI

### 集成
- **网盘：** Cloudreve (SSE 事件)
- **存储：** MinIO (S3 兼容)

---

## 运行指南

### 1. 配置环境

```bash
# 复制配置文件
cp .env.local.example .env

# 编辑 .env，配置：
# - CLOUDREVE_TOKEN
# - OPENAI_API_KEY (可选)
```

### 2. 启动服务

```bash
# 启动 Worker（语义处理）
python -m nexus.worker

# 启动 API
uvicorn apps.api.main:app --reload

# 启动 Web
cd apps/web && npm run dev
```

### 3. 测试

```bash
# 测试模块
python test_pipeline.py

# 单元测试
python -m pytest tests/
```

---

## 文件结构

```
nexus/
├── cloudreve/
│   └── client.py          # Cloudreve API 客户端
├── services/
│   ├── content_parser.py  # 内容解析服务
│   ├── knowledge_extractor.py  # 知识抽取服务
│   ├── pipeline.py        # 语义处理管道
│   ├── semantic.py        # 语义处理
│   └── ...
├── graph/
│   └── neo4j_store.py     # Neo4j 图谱存储
├── vector/
│   └── milvus_store.py    # Milvus 向量存储
└── worker.py              # 事件处理 Worker

knowledge-graph/
├── SKILL.md               # 知识抽取 Skill
└── scripts/
    ├── ontology_builder.py
    ├── graph_extractor.py
    └── ...
```

---

## 更新日志

### 2026-05-15
- ✅ 实现完整语义处理管道
- ✅ 整合 knowledge-graph skill
- ✅ 支持 PDF/DOCX/TXT 解析
- ✅ LLM 知识抽取
- ✅ Neo4j + Milvus 入库

### 2026-05-08
- ✅ Cloudreve SSE 事件监听
- ✅ 基础项目架构
- ✅ Docker 基础设施复用
