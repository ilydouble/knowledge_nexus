# 项目目录结构

当前目录树按“产品层、服务层、领域包、基础设施、数据资产、测试”组织。

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
├── knowledge-graph/         # 已有知识图谱能力与脚本
├── packages/
│   ├── domain/              # 领域模型：文件、节点、边、本体、权限
│   ├── shared/              # 通用工具、类型、配置、错误码
│   └── ui/                  # 可复用 UI 组件
├── scripts/                 # 开发、数据导入、运维和实验脚本
├── services/
│   ├── autolinker/          # 自动链接推荐与候选关系生成
│   ├── graphrag/            # GraphRAG 检索增强生成
│   ├── ingestion/           # 文件录入、解析任务调度、索引流水线
│   └── semantic/            # 多模态解析、实体抽取、摘要、标签
└── tests/
    ├── e2e/                 # 端到端测试
    ├── integration/         # 服务集成测试
    └── unit/                # 单元测试
```

## 目录职责

`apps` 放用户可见的入口。`apps/web` 承载前端交互，`apps/api` 承载统一 API 与权限入口。

`services` 放 AI 语义网盘的核心业务能力。这里刻意拆成 ingestion、semantic、autolinker、graphrag，方便后续按任务队列和算力需求独立扩展。

`packages` 放跨应用共享的领域模型与基础能力，避免每个服务重复定义文件、节点、关系、本体和权限概念。

`data` 放本体、Schema 和样例资产。Knowledge Nexus 的长期价值会沉淀在这些可版本化知识资产里。

`infrastructure` 放运行环境。MVP 可以先用 Docker Compose，本地组合 MinIO、Neo4j、Milvus/Qdrant 和 PostgreSQL；生产环境再迁移到 Kubernetes 与 Terraform。

`docs` 是项目的设计记忆。当前已经包含产品架构文档和核心架构蓝图，后续每个阶段计划都可以继续进入 `docs/plans`。

