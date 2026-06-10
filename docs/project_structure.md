# 项目目录结构

当前目录树正在从“语义网盘工作台”过渡到“Knowledge OS 内核 + 旧实现适配层”。
新的代码优先进入 `nexus/knowledge_os/`，旧的 `nexus/services/` 暂时保留为兼容和迁移来源。

```text
knowledge_nexus/
├── apps/
│   ├── api/                 # 对外 API、认证、权限、租户、审计入口
│   └── web/                 # Web 客户端：文件树、知识检查器、图谱视图
├── data/
│   ├── ontology/            # L1 顶层本体、受控词表、概念模板
│   ├── samples/             # 示例文件、演示数据、测试知识库
│   └── schemas/             # 元数据、图谱、事件和接口 Schema
├── docs/
│   ├── diagrams/            # 架构图、流程图、部署图
│   ├── plans/               # 阶段性设计计划和实现计划
│   ├── architecture_design.md
│   ├── core_architecture.md
│   └── project_structure.md
├── infrastructure/
│   ├── docker/              # 本地开发编排，如 Neo4j、Milvus、MinIO
│   ├── k8s/                 # Kubernetes 部署资源
│   └── terraform/           # 云资源 IaC
├── knowledge-graph/         # 已有知识图谱 skill 与脚本
├── nexus/
│   ├── knowledge_os/        # 新 Knowledge OS 内核（未来替换旧 services）
│   ├── services/            # 旧语义网盘服务：解析、录入、抽取、GraphRAG
│   ├── agents/              # Strands / Pi-Agent 相关 agent 封装
│   ├── cloudreve/           # Cloudreve 适配器
│   ├── repositories/        # 旧元数据 repository
│   ├── graph/               # Neo4j 适配器
│   └── vector/              # Milvus 适配器
├── scripts/                 # 开发、数据导入、运维和实验脚本
└── tests/
    ├── e2e/                 # 端到端测试
    ├── integration/         # 服务集成测试
    └── unit/                # 单元测试
```

## 目录职责

`apps` 放用户可见的入口。`apps/web` 承载前端交互，`apps/api` 承载统一 API 与权限入口。

`nexus/knowledge_os` 是新内核。它采用分层目录，所有未来重构优先进入这里：

```text
nexus/knowledge_os/
├── domain/                  # OS 领域模型：候选批次、候选图谱、证据、提交结果
├── application/             # OS 用例服务：抽取、审核、预览、提交、删除治理
├── infrastructure/          # OS 持久化适配器：内存、Postgres、后续 Neo4j/Milvus
├── models.py                # 兼容旧平铺导入，转发到 domain
├── services.py              # 兼容旧平铺导入，转发到 application
├── store.py                 # 兼容旧平铺导入，转发到 infrastructure
└── postgres_store.py        # 兼容旧平铺导入，转发到 infrastructure
```

`nexus/services` 是旧语义网盘业务能力，包含 ingestion、semantic、autolinker、graphrag、parser、classifier、Hyper-Extract bridge 等。迁移期间不再向这里随意增加 OS 级治理逻辑；新治理能力应进入 `knowledge_os/application`，旧服务只作为被调用的 adapter 或迁移来源。

`nexus/app_factory.py` 和 `nexus/mcp_server.py` 目前仍是入口聚合层。后续若继续整理，建议把 Admin API router 和 MCP tool registration 迁入 `nexus/knowledge_os/interfaces/`，入口文件只负责装配。

`data` 放本体、Schema 和样例资产。Knowledge Nexus 的长期价值会沉淀在这些可版本化知识资产里。

`infrastructure` 放运行环境。MVP 可以先用 Docker Compose，本地组合 MinIO、Neo4j、Milvus/Qdrant 和 PostgreSQL；生产环境再迁移到 Kubernetes 与 Terraform。

`docs` 是项目的设计记忆。当前已经包含产品架构文档和核心架构蓝图，后续每个阶段计划都可以继续进入 `docs/plans`。
