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

## MVP 开发启动

运行后端测试：

```bash
python3 -m pytest
```

启动本地演示栈：

```bash
docker compose -f infrastructure/docker/docker-compose.yml up --build
```

默认入口：

- Cloudreve: http://localhost:5212
- Nexus API: http://localhost:8000
- Nexus Web Console: http://localhost:5173

当前实现是 Phase 0/1 的可运行骨架：Cloudreve 作为物理网盘底座，Nexus 提供 FastAPI 语义后端、文件事件入队、文本解析/摘要/标签、个人 L3 链接、自动链接候选、权限过滤和 GraphRAG 演示接口。
