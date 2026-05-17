# Knowledge Nexus MCP Server 接入指南

## 启动 MCP Server

```bash
conda run -n nexus python -m nexus.mcp_server
```

## 接入 Claude Code

编辑 `~/.claude/claude_desktop_config.json`，添加：

```json
{
  "mcpServers": {
    "knowledge-nexus": {
      "command": "/opt/miniconda3/envs/nexus/bin/python",
      "args": ["-m", "nexus.mcp_server"],
      "cwd": "/Users/liruirui/Documents/code/test/knowledge_nexus"
    }
  }
}
```

重启 Claude Code 后，在对话中即可使用以下工具：

## 可用工具

| 工具 | 作用 | 示例问法 |
|---|---|---|
| `list_documents` | 列出所有已处理文档（摘要+标签） | "有哪些文档被处理了？" |
| `get_document` | 获取某个文档的详细元数据 | "report.pdf 讲了什么？" |
| `search_entities` | 按关键词搜索知识图谱实体 | "找所有和张伟相关的节点" |
| `get_document_graph` | 获取某文档提取出的实体和关系 | "合同里提到了哪些义务？" |
| `find_documents_by_tag` | 按标签筛选文档 | "有哪些关于机器学习的文档？" |

## 数据流说明

```
Claude Code 问题
    ↓ MCP 工具调用
knowledge-nexus MCP Server
    ├── Neo4j   → search_entities / get_document_graph
    └── Postgres → list_documents / get_document / find_documents_by_tag
```

向量检索（Milvus）不是 GraphRAG 的必要条件，图遍历本身即可支持问答。
