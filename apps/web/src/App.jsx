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

function GraphTab() {
  const [graphData, setGraphData] = useState({ nodes: [], edges: [] });
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [cluster, setCluster] = useState(false);
  const [selected, setSelected] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try { setGraphData(await api("/api/graph")); }
    catch (e) { setErr(e.message); } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const nodes = graphData.nodes || [];
  const edges = graphData.edges || [];

  return (
    <div className="graphTab">
      <div className="graphControls">
        <button className="btn btn-secondary btn-sm" onClick={load} disabled={loading}>
          {loading ? "加载中…" : "刷新图谱"}
        </button>
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

// ─── App shell ────────────────────────────────────────────────────────────────

const TABS = [
  { id: "dashboard", label: "仪表盘" },
  { id: "graph", label: "知识图谱" },
];

function App() {
  const [tab, setTab] = useState("dashboard");
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
        {tab === "graph" && <GraphTab />}
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);