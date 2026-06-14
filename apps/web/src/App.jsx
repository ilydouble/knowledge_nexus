import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import GraphView from "./GraphView.jsx";
import {
  deriveGraphFacets,
  deriveSourceDocumentsFromEdges,
  filterGraphData,
  formatNodeType,
  getNodeType,
} from "./graphData.js";

const BASE = import.meta.env.VITE_NEXUS_API_BASE || "";

async function api(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: opts.body != null ? { "Content-Type": "application/json" } : {},
    ...opts,
    body: opts.body != null ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
  return res.json();
}

function usePolling(fn, ms) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    const id = setInterval(() => ref.current(), ms);
    return () => clearInterval(id);
  }, [ms]);
}

function Alert({ children }) {
  return <div className="alert alert-error">{children}</div>;
}

function Pill({ children, active, onClick }) {
  return (
    <button className={`filter-pill${active ? " active" : ""}`} onClick={onClick}>
      {children}
    </button>
  );
}

function toggleValue(values, value) {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

function basename(uri = "") {
  const clean = uri.split("?")[0].replace(/\/$/, "");
  return clean.split("/").pop() || uri;
}

function GraphInspector({ node, nodes, edges, onClose, onFocus }) {
  if (!node) {
    return (
      <aside className="inspector empty">
        <h2>节点详情</h2>
        <p>点击图谱中的节点，查看它的属性和一跳关系。</p>
      </aside>
    );
  }

  const related = edges.filter((edge) => edge.source === node.id || edge.target === node.id);

  return (
    <aside className="inspector">
      <div className="inspector-head">
        <div>
          <span className="eyebrow">{formatNodeType(getNodeType(node))}</span>
          <h2>{node.label || node.id}</h2>
        </div>
        <button className="icon-btn" onClick={onClose} title="关闭详情">x</button>
      </div>
      {node.summary && <p className="node-summary">{node.summary}</p>}
      {node.uri && <p className="node-uri">{node.uri}</p>}
      <button className="btn btn-secondary btn-sm" onClick={() => onFocus(node.id)}>
        只看邻域
      </button>
      <h3>相关关系</h3>
      <div className="relation-list">
        {related.length === 0 && <p className="muted">当前过滤条件下没有关系。</p>}
        {related.map((edge) => {
          const otherId = edge.source === node.id ? edge.target : edge.source;
          const other = nodes.find((item) => item.id === otherId);
          return (
            <button key={edge.id} className="relation-row" onClick={() => other && onFocus(other.id)}>
              <span>{edge.source === node.id ? "->" : "<-"}</span>
              <strong>{edge.relation}</strong>
              <span>{other?.label || otherId}</span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

function DocumentTable({ docs, selectedUri, onSelect, onLoadGraph, query, onQueryChange, error }) {
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return docs;
    return docs.filter((doc) =>
      [doc.uri, doc.filename, doc.doc_type, doc.source_type, doc.summary, doc.status]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(q)
    );
  }, [docs, query]);

  return (
    <section className="data-panel">
      <div className="panel-head">
        <div>
          <span className="eyebrow">Postgres</span>
          <h2>关系库数据</h2>
        </div>
        <input
          className="search-input compact"
          placeholder="过滤文档、类型、摘要"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
        />
      </div>
      {error && <Alert>{error}</Alert>}
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>文档</th>
              <th>类型</th>
              <th>切片</th>
              <th>状态</th>
              <th>更新时间</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((doc) => (
              <tr key={doc.uri} className={selectedUri === doc.uri ? "selected" : ""}>
                <td>
                  <button className="link-cell" onClick={() => onSelect(doc.uri)}>
                    <strong>{doc.filename || basename(doc.uri)}</strong>
                    <span>{doc.uri}</span>
                  </button>
                </td>
                <td>{doc.graph_only ? "图谱来源" : (doc.doc_type || doc.source_type || "-")}</td>
                <td>{doc.chunk_count ?? 0}</td>
                <td><span className={`status ${doc.status || "active"}`}>{doc.status || "active"}</span></td>
                <td>{doc.created_at ? new Date(doc.created_at).toLocaleString() : "-"}</td>
                <td>
                  <button className="btn btn-secondary btn-sm" onClick={() => onLoadGraph(doc)}>
                    {doc.graph_only ? "筛选来源" : "定位图谱"}
                  </button>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan="6" className="empty-cell">没有匹配的文档记录。</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ChunkPanel({ docUri, chunks, loading, error }) {
  return (
    <section className="chunk-panel">
      <div className="panel-head">
        <div>
          <span className="eyebrow">semantic_chunks</span>
          <h2>{docUri ? basename(docUri) : "选择文档查看切片"}</h2>
        </div>
      </div>
      {error && <Alert>{error}</Alert>}
      {loading && <p className="muted">正在读取切片...</p>}
      {!docUri && <p className="muted">从下方表格选择一个文档，可以查看关系库里保存的切片摘要和实体标签。</p>}
      {docUri && !loading && chunks.length === 0 && <p className="muted">该文档没有切片记录。</p>}
      <div className="chunk-list">
        {chunks.map((chunk) => (
          <article key={chunk.id} className="chunk-item">
            <span className="chunk-index">#{chunk.chunk_index}</span>
            <div>
              {chunk.summary && <p className="chunk-summary">{chunk.summary}</p>}
              {Array.isArray(chunk.entities) && chunk.entities.length > 0 && (
                <div className="tag-row">
                  {chunk.entities.slice(0, 8).map((entity, index) => (
                    <span key={`${entity.id || entity.label}-${index}`} className="mini-tag">
                      {entity.label || entity.id}
                    </span>
                  ))}
                </div>
              )}
              <p className="chunk-text">{chunk.text?.slice(0, 360)}{chunk.text?.length > 360 ? "..." : ""}</p>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function NexusExplorer() {
  const [graphData, setGraphData] = useState({ nodes: [], edges: [] });
  const [docs, setDocs] = useState([]);
  const [chunks, setChunks] = useState([]);
  const [selectedNode, setSelectedNode] = useState(null);
  const [selectedDocUri, setSelectedDocUri] = useState("");
  const [graphQuery, setGraphQuery] = useState("");
  const [docQuery, setDocQuery] = useState("");
  const [uriInput, setUriInput] = useState("");
  const [nodeTypes, setNodeTypes] = useState([]);
  const [relationTypes, setRelationTypes] = useState([]);
  const [clusterMode, setClusterMode] = useState(false);
  const [neighborhoodOnly, setNeighborhoodOnly] = useState(false);
  const [focusNodeId, setFocusNodeId] = useState("");
  const [loadingGraph, setLoadingGraph] = useState(false);
  const [loadingChunks, setLoadingChunks] = useState(false);
  const [graphError, setGraphError] = useState("");
  const [docError, setDocError] = useState("");
  const [chunkError, setChunkError] = useState("");

  const loadGraph = useCallback(async (uri = "") => {
    setLoadingGraph(true);
    setGraphError("");
    const endpoint = uri ? `/api/graph?uri=${encodeURIComponent(uri)}` : "/api/graph?limit=800";
    try {
      const data = await api(endpoint);
      setGraphData({ nodes: data.nodes || [], edges: data.edges || [] });
      setSelectedNode(null);
      setFocusNodeId("");
      setNeighborhoodOnly(false);
      setUriInput(uri);
      if (uri) setSelectedDocUri(uri);
    } catch (error) {
      setGraphError(error.message);
    } finally {
      setLoadingGraph(false);
    }
  }, []);

  const loadDocs = useCallback(async () => {
    try {
      const data = await api("/api/admin/documents?limit=500");
      setDocs(data.documents || []);
      setDocError("");
    } catch (error) {
      setDocError(error.message);
    }
  }, []);

  const loadChunks = useCallback(async (uri) => {
    if (!uri) {
      setChunks([]);
      return;
    }
    setLoadingChunks(true);
    setChunkError("");
    try {
      const data = await api(`/api/admin/documents/chunks?uri=${encodeURIComponent(uri)}`);
      setChunks(data.chunks || []);
    } catch (error) {
      setChunkError(error.message);
      setChunks([]);
    } finally {
      setLoadingChunks(false);
    }
  }, []);

  useEffect(() => {
    loadGraph();
    loadDocs();
  }, [loadGraph, loadDocs]);
  usePolling(loadDocs, 15000);
  useEffect(() => { loadChunks(selectedDocUri); }, [loadChunks, selectedDocUri]);

  const facets = useMemo(
    () => deriveGraphFacets(graphData.nodes, graphData.edges),
    [graphData.edges, graphData.nodes]
  );
  const filteredGraph = useMemo(
    () => filterGraphData(graphData.nodes, graphData.edges, {
      query: graphQuery,
      nodeTypes,
      relationTypes,
      focusNodeId,
      neighborhoodOnly,
    }),
    [focusNodeId, graphData.edges, graphData.nodes, graphQuery, neighborhoodOnly, nodeTypes, relationTypes]
  );
  const graphSourceDocs = useMemo(
    () => deriveSourceDocumentsFromEdges(graphData.edges),
    [graphData.edges]
  );
  const visibleDocs = docs.length > 0 ? docs : graphSourceDocs;

  const handleSelectNode = (node) => {
    setSelectedNode(node);
    setFocusNodeId(node.id);
  };

  const focusNode = (nodeId) => {
    setFocusNodeId(nodeId);
    setNeighborhoodOnly(true);
  };

  const clearFilters = () => {
    setGraphQuery("");
    setNodeTypes([]);
    setRelationTypes([]);
    setNeighborhoodOnly(false);
    setFocusNodeId("");
  };

  const loadDocumentGraph = async (doc) => {
    setSelectedDocUri(doc.uri);
    if (doc.graph_only) {
      await loadGraph();
      setGraphQuery(doc.uri);
      return;
    }
    await loadGraph(doc.uri);
  };

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <span className="app-title">Knowledge Nexus</span>
          <p>图谱和关系库数据探索</p>
        </div>
        <div className="header-actions">
          <button className="btn btn-secondary btn-sm" onClick={() => loadGraph()} disabled={loadingGraph}>
            {loadingGraph ? "刷新中..." : "全量图谱"}
          </button>
          <button className="btn btn-primary btn-sm" onClick={() => loadDocs()}>
            刷新数据表
          </button>
        </div>
      </header>

      <main className="workspace">
        <section className="graph-workbench">
          <div className="toolbar">
            <input
              className="search-input"
              placeholder="搜索节点标签、URI、摘要、属性"
              value={graphQuery}
              onChange={(event) => setGraphQuery(event.target.value)}
            />
            <form
              className="uri-form"
              onSubmit={(event) => {
                event.preventDefault();
                loadGraph(uriInput.trim());
              }}
            >
              <input
                className="search-input compact"
                placeholder="输入文档 URI 定位子图"
                value={uriInput}
                onChange={(event) => setUriInput(event.target.value)}
              />
              <button className="btn btn-secondary btn-sm" type="submit" disabled={loadingGraph}>
                定位
              </button>
            </form>
            <label className="toggle">
              <input type="checkbox" checked={clusterMode} onChange={(event) => setClusterMode(event.target.checked)} />
              聚类
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={neighborhoodOnly}
                onChange={(event) => setNeighborhoodOnly(event.target.checked)}
                disabled={!focusNodeId}
              />
              邻域
            </label>
            <button className="btn btn-ghost btn-sm" onClick={clearFilters}>清除</button>
          </div>

          <div className="facet-row">
            <span>节点</span>
            {facets.nodeTypes.map((type) => (
              <Pill
                key={type}
                active={nodeTypes.includes(type)}
                onClick={() => setNodeTypes((values) => toggleValue(values, type))}
              >
                {formatNodeType(type)}
              </Pill>
            ))}
          </div>
          <div className="facet-row">
            <span>关系</span>
            {facets.relationTypes.map((relation) => (
              <Pill
                key={relation}
                active={relationTypes.includes(relation)}
                onClick={() => setRelationTypes((values) => toggleValue(values, relation))}
              >
                {relation}
              </Pill>
            ))}
          </div>

          {graphError && <Alert>{graphError}</Alert>}
          <div className="graph-meta">
            <span>{filteredGraph.nodes.length} / {graphData.nodes.length} 节点</span>
            <span>{filteredGraph.edges.length} / {graphData.edges.length} 关系</span>
            {(filteredGraph.hiddenNodes > 0 || filteredGraph.hiddenEdges > 0) && (
              <span>已隐藏 {filteredGraph.hiddenNodes} 节点、{filteredGraph.hiddenEdges} 关系</span>
            )}
          </div>

          <div className="graph-stage">
            <GraphView
              nodes={filteredGraph.nodes}
              edges={filteredGraph.edges}
              clusterMode={clusterMode}
              selectedNodeId={selectedNode?.id}
              focusNodeId={focusNodeId}
              onNodeClick={handleSelectNode}
            />
            <GraphInspector
              node={selectedNode}
              nodes={filteredGraph.nodes}
              edges={filteredGraph.edges}
              onClose={() => setSelectedNode(null)}
              onFocus={focusNode}
            />
          </div>
        </section>

        <div className="data-grid">
          <DocumentTable
            docs={visibleDocs}
            selectedUri={selectedDocUri}
            onSelect={setSelectedDocUri}
            onLoadGraph={loadDocumentGraph}
            query={docQuery}
            onQueryChange={setDocQuery}
            error={docError}
          />
          <ChunkPanel docUri={selectedDocUri} chunks={chunks} loading={loadingChunks} error={chunkError} />
        </div>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<NexusExplorer />);
