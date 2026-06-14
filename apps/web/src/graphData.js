export function isDocumentNode(node) {
  const uri = node?.uri || "";
  return Boolean(uri) && !uri.startsWith("entity://");
}

export function getNodeType(node) {
  if (node?.isCluster) return node.clusterType || "cluster";
  if (isDocumentNode(node)) return "document";
  const explicitType = node?.properties?.type || node?.type;
  if (explicitType) return String(explicitType).toLowerCase();
  const id = String(node?.id || node?.label || "");
  const prefix = id.includes("_") ? id.split("_")[0] : "";
  const knownPrefixes = new Set([
    "api",
    "concept",
    "database",
    "event",
    "institution",
    "location",
    "method",
    "object",
    "organization",
    "person",
    "product",
    "researcher",
    "system",
    "technology",
    "tool",
  ]);
  const type = knownPrefixes.has(prefix.toLowerCase()) ? prefix : "entity";
  return String(type).toLowerCase();
}

export function formatNodeType(type) {
  const labels = {
    document: "文档",
    entity: "实体",
    component: "组件",
    concept: "概念",
    database: "数据库",
    event: "事件",
    location: "位置",
    method: "方法",
    object: "对象",
    person: "人物",
    product: "产品",
    researcher: "研究者",
    organization: "组织",
    institution: "机构",
    dataset: "数据集",
    metric: "指标",
    api: "API",
    technology: "技术",
    tool: "工具",
    framework: "框架",
  };
  return labels[type] || type;
}

function textMatches(node, query) {
  if (!query) return true;
  const haystack = [
    node.id,
    node.uri,
    node.label,
    node.summary,
    ...Object.values(node.properties || {}),
  ]
    .filter((value) => value != null)
    .join(" ")
    .toLowerCase();
  return haystack.includes(query.toLowerCase());
}

function edgeMatches(edge, query) {
  if (!query) return true;
  const haystack = [
    edge.id,
    edge.relation,
    edge.source,
    edge.target,
    edge.source_file_uri,
    edge.owner_scope,
    edge.visibility,
    ...Object.values(edge.properties || {}),
  ]
    .filter((value) => value != null)
    .join(" ")
    .toLowerCase();
  return haystack.includes(query.toLowerCase());
}

function uniqueSorted(values) {
  return Array.from(new Set(values.filter(Boolean))).sort((a, b) => a.localeCompare(b));
}

export function deriveGraphFacets(nodes = [], edges = []) {
  return {
    nodeTypes: uniqueSorted(nodes.map(getNodeType)),
    relationTypes: uniqueSorted(edges.map((edge) => edge.relation || "RELATES_TO")),
  };
}

export function deriveSourceDocumentsFromEdges(edges = []) {
  const docs = new Map();
  for (const edge of edges) {
    const uri = edge.source_file_uri;
    if (!uri) continue;
    const existing = docs.get(uri);
    if (existing) {
      existing.chunk_count += 1;
      continue;
    }
    docs.set(uri, {
      uri,
      filename: uri.split("/").pop() || uri,
      source_type: "graph",
      doc_type: "graph_source",
      status: "graph-only",
      chunk_count: 1,
      graph_only: true,
      summary: "来自 Neo4j 边的 source_file_uri，Postgres 当前没有对应 semantic_documents 记录。",
    });
  }
  return Array.from(docs.values());
}

export function filterGraphData(nodes = [], edges = [], filters = {}) {
  const {
    query = "",
    nodeTypes = [],
    relationTypes = [],
    focusNodeId = "",
    neighborhoodOnly = false,
  } = filters;
  const nodeTypeSet = new Set(nodeTypes);
  const relationSet = new Set(relationTypes);
  const activeNodeTypeFilter = nodeTypeSet.size > 0;
  const activeRelationFilter = relationSet.size > 0;

  const cleanQuery = query.trim();
  const nodeMatches = new Set(
    nodes
      .filter((node) => !activeNodeTypeFilter || nodeTypeSet.has(getNodeType(node)))
      .filter((node) => textMatches(node, cleanQuery))
      .map((node) => node.id)
  );
  const edgeQueryMatches = new Set();
  for (const edge of edges) {
    if (!cleanQuery || !edgeMatches(edge, cleanQuery)) continue;
    edgeQueryMatches.add(edge.source);
    edgeQueryMatches.add(edge.target);
  }

  let visibleNodeIds = new Set(
    nodes
      .filter((node) => !activeNodeTypeFilter || nodeTypeSet.has(getNodeType(node)))
      .filter((node) => !cleanQuery || nodeMatches.has(node.id) || edgeQueryMatches.has(node.id))
      .map((node) => node.id)
  );

  if (neighborhoodOnly && focusNodeId) {
    const neighborhood = new Set([focusNodeId]);
    for (const edge of edges) {
      if (edge.source === focusNodeId) neighborhood.add(edge.target);
      if (edge.target === focusNodeId) neighborhood.add(edge.source);
    }
    visibleNodeIds = new Set([...visibleNodeIds].filter((id) => neighborhood.has(id)));
  }

  const visibleEdges = edges.filter((edge) => {
    const relation = edge.relation || "RELATES_TO";
    const matchesQuery = !cleanQuery || edgeMatches(edge, cleanQuery);
    const matchesNodeSearch = !cleanQuery || (nodeMatches.has(edge.source) && nodeMatches.has(edge.target));
    return (
      visibleNodeIds.has(edge.source) &&
      visibleNodeIds.has(edge.target) &&
      (!activeRelationFilter || relationSet.has(relation)) &&
      (matchesQuery || matchesNodeSearch)
    );
  });

  const connectedIds = new Set();
  for (const edge of visibleEdges) {
    connectedIds.add(edge.source);
    connectedIds.add(edge.target);
  }
  if (cleanQuery || activeNodeTypeFilter || (neighborhoodOnly && focusNodeId)) {
    for (const id of visibleNodeIds) connectedIds.add(id);
  }

  const visibleNodes = nodes.filter((node) => connectedIds.has(node.id));

  return {
    nodes: visibleNodes,
    edges: visibleEdges,
    hiddenNodes: Math.max(0, nodes.length - visibleNodes.length),
    hiddenEdges: Math.max(0, edges.length - visibleEdges.length),
  };
}
