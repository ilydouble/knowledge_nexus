# Knowledge Nexus 核心架构

## 1. 核心命题

Knowledge Nexus 的系统边界可以浓缩为一句话：

> 文件仍由组织管控，知识关系由语义层自由生长。

系统因此被拆成两条互相制衡的主线：

- 物理资产线：负责文件、目录、对象存储、预览、下载、审计和硬权限。
- 语义知识线：负责实体、标签、图谱、向量、双向链接、GraphRAG 和个人认知层。

## 2. 核心组件图

```mermaid
flowchart LR
    User["用户 / 团队 / 管理员"]
    Web["Web App<br/>文件树 + 知识检查器 + 图谱视图"]
    API["API Gateway<br/>认证 / 租户 / 权限 / 审计"]

    FileSvc["File Service<br/>上传 / 下载 / 预览 / 版本"]
    MetaSvc["Metadata Service<br/>文件元数据 / 实体索引"]
    OntologySvc["Ontology Service<br/>L1 标准本体 / 受控词表"]
    DomainSvc["Domain Knowledge Service<br/>L2 团队图谱 / 项目知识库"]
    PersonalSvc["Personal Cognition Service<br/>L3 私有链接 / 个人笔记"]

    Parser["Multi-modal Parser<br/>文本 / 图像 / 视频 / 表格解析"]
    Extractor["Semantic Extractor<br/>实体 / 事件 / 摘要 / 标签"]
    AutoLinker["Auto-Linker<br/>自动关联推荐"]
    GraphRAG["GraphRAG Engine<br/>图谱检索 + 向量检索 + 生成"]

    ObjectStore[("Object Storage<br/>S3 Compatible")]
    GraphDB[("Graph Database<br/>L1/L2 全局图 + L3 私有图分片")]
    VectorDB[("Vector Database<br/>Embedding / Semantic Search")]
    SearchIndex[("Search Index<br/>Keyword / Metadata")]

    User --> Web --> API
    API --> FileSvc
    API --> MetaSvc
    API --> OntologySvc
    API --> DomainSvc
    API --> PersonalSvc
    API --> GraphRAG

    FileSvc --> ObjectStore
    FileSvc --> Parser --> Extractor
    Extractor --> MetaSvc
    Extractor --> VectorDB
    Extractor --> GraphDB
    Extractor --> SearchIndex

    OntologySvc --> GraphDB
    DomainSvc --> GraphDB
    PersonalSvc --> GraphDB
    AutoLinker --> GraphDB
    AutoLinker --> VectorDB
    AutoLinker --> PersonalSvc

    GraphRAG --> GraphDB
    GraphRAG --> VectorDB
    GraphRAG --> SearchIndex
```

## 3. 三层本体映射

| 层级 | 产品含义 | 技术载体 | 写入方 | 默认可见性 |
| :--- | :--- | :--- | :--- | :--- |
| L1 Standard Ontology | 官方概念、实体类型、分类和模板 | 图数据库中的标准本体子图 | 管理员、领域专家 | 全组织可见 |
| L2 Collective Domain | 团队知识库、项目图谱、部门共识 | 图数据库中的团队/项目子图 | 授权团队成员 | 团队或项目空间可见 |
| L3 Personal Cognition | 私人笔记、双向链接、主观联想 | 用户私有图分片和个人向量索引 | 用户本人 | 仅本人可见 |

## 4. 数据流

```mermaid
sequenceDiagram
    participant U as 用户
    participant W as Web App
    participant A as API Gateway
    participant F as File Service
    participant P as Parser
    participant E as Semantic Extractor
    participant G as Graph DB
    participant V as Vector DB
    participant L as Auto-Linker

    U->>W: 上传文件
    W->>A: 提交文件与目标文件夹
    A->>F: 校验权限并创建文件记录
    F->>F: 写入对象存储
    F->>P: 触发异步解析任务
    P->>E: 输出文本、结构和多模态内容
    E->>G: 写入实体与关系候选
    E->>V: 写入语义向量
    L->>G: 对齐 L1/L2/L3 图谱
    L->>W: 返回自动关联建议
    W->>U: 请求确认是否建立链接
```

## 5. 权限过滤链路

所有 AI 上下文必须遵循先授权、后检索、再生成的顺序。

```mermaid
flowchart TD
    Query["用户查询"]
    Auth["认证与租户上下文"]
    Policy["权限策略计算<br/>文件权限 + 图谱权限 + L3 私有边界"]
    Retrieval["混合检索<br/>关键词 + 向量 + 图邻居"]
    Filter["结果过滤<br/>隐藏无权内容 / 保留安全关系轮廓"]
    Prompt["构造 GraphRAG 上下文"]
    Answer["AI 生成答案"]

    Query --> Auth --> Policy --> Retrieval --> Filter --> Prompt --> Answer
```

关键规则：

- 无文件权限时，不能返回文件正文、摘要、预览和敏感元数据。
- 可允许显示“加密节点”，但只能暴露经策略允许的节点类型、关系方向和非敏感关系。
- L3 私有链接不会进入他人的检索上下文。
- AI Agent 不拥有越权能力，只能消费已过滤后的上下文。

## 6. MVP 切片

第一阶段建议先做一个“小而硬”的闭环：

- 文件上传与对象存储抽象。
- 文件元数据表和权限模型。
- AI 自动标签与摘要。
- 个人 `[[Link]]` 双向链接。
- 基础图谱节点与边模型。
- 语义搜索接口。
- 右侧知识检查器原型。

这个切片能证明产品最关键的差异化：文件位置不变，但知识关系可以自由重组。

