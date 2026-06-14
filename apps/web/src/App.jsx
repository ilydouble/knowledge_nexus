import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import GraphView from "./GraphView.jsx";

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

// Stable polling — fn ref updated each render, interval never recreated
function usePolling(fn, ms) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    const id = setInterval(() => ref.current(), ms);
    return () => clearInterval(id);
  }, [ms]);
}

function StatusPill({ s }) {
  return <span className={`status ${s}`}>{s}</span>;
}

function Alert({ type = "error", children, style }) {
  return <div className={`alert alert-${type}`} style={style}>{children}</div>;
}

// ─── Dashboard ────────────────────────────────────────────────────────────────

function DashboardTab() {
  const [dash, setDash] = useState(null);
  const [scan, setScan] = useState(null);
  const [auth, setAuth] = useState(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const [d, s, a] = await Promise.all([
        api("/api/admin/dashboard"),
        api("/api/cloudreve/scan/status"),
        api("/api/auth/cloudreve/status"),
      ]);
      setDash(d); setScan(s); setAuth(a); setErr("");
    } catch (e) { setErr(e.message); }
  }, []);

  useEffect(() => { load(); }, [load]);
  usePolling(load, 10000);

  const { batches = {}, items = {}, stale_evidence = 0 } = dash || {};
  const isScanning = scan?.is_scanning;

  return (
    <div>
      {err && <Alert style={{ marginBottom: 16 }}>{err}</Alert>}

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-value">{batches.total ?? "—"}</div>
          <div className="stat-label">批次总数</div>
        </div>
        <div className="stat-card green">
          <div className="stat-value">{batches.committed ?? "—"}</div>
          <div className="stat-label">已提交图谱</div>
        </div>
        <div className="stat-card amber">
          <div className="stat-value">{items.candidate ?? "—"}</div>
          <div className="stat-label">待审核条目</div>
        </div>
        <div className="stat-card green">
          <div className="stat-value">{items.accepted ?? "—"}</div>
          <div className="stat-label">已接受条目</div>
        </div>
        <div className={stale_evidence > 0 ? "stat-card red" : "stat-card"}>
          <div className="stat-value">{stale_evidence ?? "—"}</div>
          <div className="stat-label">过期证据</div>
        </div>
      </div>

      {auth && (
        <div className={`status-panel ${auth.authorized ? "ok" : "warn"}`}>
          <span className="sp-icon">{auth.authorized ? "✓" : "⚠"}</span>
          <div className="sp-content">
            <div className="sp-title">Cloudreve {auth.authorized ? "已授权" : "未授权"}</div>
          </div>
        </div>
      )}

      {scan && (
        <div className={`status-panel ${isScanning ? "busy" : scan.error ? "warn" : "ok"}`}>
          <span className="sp-icon">{isScanning ? "↻" : scan.error ? "✗" : "✓"}</span>
          <div className="sp-content">
            <div className="sp-title">
              {isScanning
                ? "扫描中…"
                : scan.finished_at
                  ? `上次扫描：${new Date(scan.finished_at).toLocaleString()}`
                  : "从未扫描"}
            </div>
            {scan.files_found != null && (
              <div className="sp-sub">
                发现 {scan.files_found} 个文件，新增 {scan.files_queued ?? 0} 个
              </div>
            )}
            {scan.error && <div className="sp-sub">{scan.error}</div>}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Graph tab ────────────────────────────────────────────────────────────────

function paletteColor(type) {
  const p = {
    researcher: "#f59e0b", person: "#f59e0b",
    institution: "#10b981", organization: "#10b981",
    method: "#3b82f6", concept: "#8b5cf6", component: "#f97316",
  };
  return p[(type || "").toLowerCase()] || "#94a3b8";
}

function GraphTab({ initialUri, onUriConsumed }) {
  const [graphData, setGraphData] = useState({ nodes: [], edges: [] });
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [cluster, setCluster] = useState(false);
  const [selected, setSelected] = useState(null);
  const [filterUri, setFilterUri] = useState("");

  const load = useCallback(async (uri) => {
    setLoading(true); setErr("");
    const endpoint = uri ? `/api/graph?uri=${encodeURIComponent(uri)}` : "/api/graph";
    try { setGraphData(await api(endpoint)); }
    catch (e) { setErr(e.message); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  // When navigated from Documents tab, auto-load the file neighbourhood
  useEffect(() => {
    if (initialUri) {
      setFilterUri(initialUri);
      load(initialUri);
      onUriConsumed?.();
    }
  }, [initialUri]); // eslint-disable-line react-hooks/exhaustive-deps

  const nodes = graphData.nodes || [];
  const edges = graphData.edges || [];

  return (
    <div className="graphTab">
      <div className="graphControls">
        <button className="btn btn-secondary btn-sm" onClick={() => load(filterUri || undefined)} disabled={loading}>
          {loading ? "加载中…" : "刷新图谱"}
        </button>
        {filterUri && (
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => { setFilterUri(""); load(); }}
            title="清除文件过滤，显示完整图谱"
          >
            ✕ {filterUri.split("/").pop()}
          </button>
        )}
        <label style={{ display: "flex", alignItems: "center", gap: 6, margin: 0, fontSize: 13, fontWeight: 500, cursor: "pointer" }}>
          <input type="checkbox" checked={cluster} onChange={(e) => setCluster(e.target.checked)}
            style={{ width: "auto", margin: 0 }} />
          聚类视图
        </label>
        <span className="graphStats">{nodes.length} 节点 · {edges.length} 关系</span>
      </div>
      {err && <Alert>{err}</Alert>}
      <div className="graphMain">
        <GraphView nodes={nodes} edges={edges} clusterMode={cluster} onNodeClick={setSelected} />
        {selected && (
          <aside className="graphSidebar">
            <div className="graphSidebarHeader">
              <h3>{selected.label || selected.id}</h3>
              <button className="btn btn-ghost btn-sm btn-icon"
                onClick={() => setSelected(null)}>✕</button>
            </div>
            {selected.isCluster ? (
              <>
                <p className="graphNodeType">集群 · {selected.count} 个节点</p>
                <div className="graphRelList">
                  {selected.members?.map((m) => (
                    <div key={m.id} className="graphRelRow">
                      <span className="relType" style={{ color: paletteColor(m.properties?.type) }}>
                        {m.properties?.type || "节点"}
                      </span>
                      <span>{m.label || m.id}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <>
                {selected.properties?.type && (
                  <p className="graphNodeType">{selected.properties.type}</p>
                )}
                {selected.summary && <p className="summary">{selected.summary}</p>}
                {selected.uri && <span className="uri">{selected.uri}</span>}
                <h4>相关关系</h4>
                <div className="graphRelList">
                  {edges
                    .filter((e) => e.source === selected.id || e.target === selected.id)
                    .map((e) => {
                      const otherId = e.source === selected.id ? e.target : e.source;
                      const other = nodes.find((n) => n.id === otherId);
                      return (
                        <div key={e.id} className="graphRelRow">
                          <span className="relType">{e.relation}</span>
                          <span>{e.source === selected.id ? "→" : "←"} {other?.label || otherId}</span>
                        </div>
                      );
                    })}
                </div>
              </>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}

// ─── Documents tab ────────────────────────────────────────────────────────────

function DocRow({ doc, onViewGraph }) {
  const [open, setOpen] = useState(false);
  const [chunks, setChunks] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const toggle = async () => {
    if (open) { setOpen(false); return; }
    setOpen(true);
    if (chunks !== null) return;
    setLoading(true);
    try {
      const d = await api(`/api/admin/documents/chunks?uri=${encodeURIComponent(doc.uri)}`);
      setChunks(d.chunks ?? []);
    } catch (e) { setErr(e.message); } finally { setLoading(false); }
  };

  const tags = Array.isArray(doc.tags) ? doc.tags : [];
  const entities = Array.isArray(doc.entities) ? doc.entities : [];

  return (
    <div className={`doc-row ${open ? "open" : ""}`}>
      <div className="doc-row-header" onClick={toggle}>
        <div className="doc-row-left">
          <span className={`doc-status status ${doc.status || "active"}`}>{doc.status || "active"}</span>
          {doc.source_type && (
            <span className="doc-tag" style={{ background: "#e0f2fe", color: "#0369a1", marginRight: 4 }}>
              {doc.source_type}
            </span>
          )}
          {doc.doc_type && (
            <span className="doc-tag" style={{ background: "#f3e8ff", color: "#7e22ce", marginRight: 4 }}>
              {doc.doc_type}
            </span>
          )}
          <div className="doc-uri">{doc.filename || doc.uri}</div>
          <div className="doc-uri" style={{ fontSize: 11, color: "#64748b", marginTop: 1 }}>{doc.uri}</div>
          {tags.length > 0 && (
            <div className="doc-tags">
              {tags.map((t, i) => <span key={i} className="doc-tag">{t}</span>)}
            </div>
          )}
          {entities.length > 0 && (
            <div className="doc-tags" style={{ marginTop: 2 }}>
              {entities.slice(0, 8).map((e, i) => (
                <span key={i} className="doc-tag" style={{ background: "#fef3c7", color: "#92400e" }}>
                  {e.label || e.id}
                </span>
              ))}
              {entities.length > 8 && (
                <span className="doc-tag" style={{ background: "#f1f5f9", color: "#64748b" }}>
                  +{entities.length - 8}
                </span>
              )}
            </div>
          )}
        </div>
        <div className="doc-row-right">
          {doc.size_bytes && (
            <span className="doc-date" style={{ marginRight: 8 }}>
              {(doc.size_bytes / 1024).toFixed(1)} KB
            </span>
          )}
          {doc.chunk_count > 1 && (
            <span className="doc-date" style={{ marginRight: 8 }}>{doc.chunk_count} 片段</span>
          )}
          <span className="doc-date">{doc.created_at ? new Date(doc.created_at).toLocaleString() : "—"}</span>
          <button
            className="btn btn-ghost btn-sm"
            style={{ marginLeft: 8, fontSize: 12, padding: "2px 8px" }}
            onClick={(e) => { e.stopPropagation(); onViewGraph(doc.uri); }}
            title="在图谱中查看"
          >
            🔗 图谱
          </button>
          <span className="doc-toggle">{open ? "▲" : "▼"}</span>
        </div>
      </div>

      {doc.summary && (
        <div className="doc-summary">{doc.summary}</div>
      )}

      {open && (
        <div className="doc-chunks">
          {err && <Alert style={{ marginBottom: 8 }}>{err}</Alert>}
          {loading && <p className="muted">加载切片中…</p>}
          {chunks && chunks.length === 0 && <p className="muted">该文件暂无切片记录</p>}
          {chunks && chunks.map((c) => (
            <div key={c.id} className="chunk-card">
              <div className="chunk-idx">#{c.chunk_index}</div>
              {c.summary && <div className="doc-summary" style={{ fontSize: 13 }}>{c.summary}</div>}
              {Array.isArray(c.tags) && c.tags.length > 0 && (
                <div className="doc-tags" style={{ margin: "4px 0" }}>
                  {c.tags.map((t, i) => <span key={i} className="doc-tag">{t}</span>)}
                </div>
              )}
              {Array.isArray(c.entities) && c.entities.length > 0 && (
                <div className="doc-tags" style={{ margin: "4px 0" }}>
                  {c.entities.slice(0, 6).map((e, i) => (
                    <span key={i} className="doc-tag" style={{ background: "#fef3c7", color: "#92400e" }}>
                      {e.label || e.id}
                    </span>
                  ))}
                </div>
              )}
              <div className="chunk-text">{c.text?.slice(0, 300)}{c.text?.length > 300 ? "…" : ""}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function LocalAnalyzeForm({ onSuccess }) {
  const [path, setPath] = useState("");
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    if (!path.trim()) return;
    setBusy(true); setErr(""); setResult(null);
    try {
      const r = await api("/api/admin/candidates/extract/path", {
        method: "POST",
        body: { path: path.trim(), instructions: instructions.trim() || undefined },
      });
      setResult(r);
      onSuccess?.();
    } catch (ex) { setErr(ex.message); } finally { setBusy(false); }
  };

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-header"><span className="card-title">本地文件分析</span></div>
      <div className="card-body" style={{ padding: "12px 16px" }}>
        <form onSubmit={submit} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div style={{ flex: "1 1 300px" }}>
            <label style={{ display: "block", fontSize: 12, marginBottom: 4, fontWeight: 500 }}>文件路径（绝对路径）</label>
            <input
              className="form-control"
              style={{ marginTop: 0 }}
              placeholder="/data/reports/my-file.pdf"
              value={path}
              onChange={(e) => setPath(e.target.value)}
            />
          </div>
          <div style={{ flex: "1 1 200px" }}>
            <label style={{ display: "block", fontSize: 12, marginBottom: 4, fontWeight: 500 }}>提取指令（可选）</label>
            <input
              className="form-control"
              style={{ marginTop: 0 }}
              placeholder="聚焦于…"
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
            />
          </div>
          <button className="btn btn-primary btn-sm" type="submit" disabled={busy || !path.trim()}>
            {busy ? "分析中…" : "开始分析"}
          </button>
        </form>
        {err && <Alert style={{ marginTop: 8 }}>{err}</Alert>}
        {result && (
          <Alert type="success" style={{ marginTop: 8 }}>
            ✓ 分析完成 — 批次 {result.batch_id}，提取 {result.entity_count ?? 0} 实体，{result.relation_count ?? 0} 关系
            {result.warnings?.length > 0 && <div style={{ marginTop: 4, fontSize: 12 }}>{result.warnings.join("；")}</div>}
          </Alert>
        )}
      </div>
    </div>
  );
}

function DocumentsTab({ onViewGraph }) {
  const [docs, setDocs] = useState([]);
  const [err, setErr] = useState("");
  const [filter, setFilter] = useState("");

  const load = useCallback(async () => {
    try {
      const d = await api("/api/admin/documents?limit=200");
      setDocs(d.documents ?? []); setErr("");
    } catch (e) { setErr(e.message); }
  }, []);

  useEffect(() => { load(); }, [load]);
  usePolling(load, 15000);

  const filtered = filter
    ? docs.filter((d) =>
        d.uri?.includes(filter) ||
        d.status?.includes(filter) ||
        d.doc_type?.includes(filter) ||
        d.filename?.includes(filter)
      )
    : docs;

  return (
    <div>
      <LocalAnalyzeForm onSuccess={load} />
      <div className="card">
        <div className="card-header">
          <span className="card-title">文件库（{filtered.length} / {docs.length}）</span>
          <div className="btn-row">
            <input className="form-control" style={{ width: 220, marginTop: 0 }}
              placeholder="过滤 URI / 状态 / 类型…"
              value={filter} onChange={(e) => setFilter(e.target.value)} />
            <button className="btn btn-secondary btn-sm" onClick={load}>刷新</button>
          </div>
        </div>
        <div className="card-body" style={{ padding: "12px 16px" }}>
          {err && <Alert style={{ marginBottom: 12 }}>{err}</Alert>}
          {filtered.length === 0
            ? <p className="muted">暂无文件记录</p>
            : filtered.map((doc) => <DocRow key={doc.uri} doc={doc} onViewGraph={onViewGraph} />)
          }
        </div>
      </div>
    </div>
  );
}

// ─── App shell ────────────────────────────────────────────────────────────────

const TABS = [
  { id: "dashboard", label: "仪表盘" },
  { id: "documents", label: "文件库" },
  { id: "graph", label: "知识图谱" },
];

function App() {
  const [tab, setTab] = useState("dashboard");
  const [graphUri, setGraphUri] = useState(null);

  const handleViewGraph = (uri) => {
    setGraphUri(uri);
    setTab("graph");
  };

  return (
    <div className="app">
      <header className="app-header">
        <span className="app-title">Knowledge OS</span>
        <nav className="tab-nav">
          {TABS.map((t) => (
            <button key={t.id} className={`tab-btn${tab === t.id ? " active" : ""}`}
              onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </nav>
      </header>
      <main className="app-main">
        {tab === "dashboard" && <DashboardTab />}
        {tab === "documents" && <DocumentsTab onViewGraph={handleViewGraph} />}
        {tab === "graph" && <GraphTab initialUri={graphUri} onUriConsumed={() => setGraphUri(null)} />}
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);