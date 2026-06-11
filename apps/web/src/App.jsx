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
  const [scanning, setScanning] = useState(false);

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

  const triggerScan = async () => {
    setScanning(true);
    try {
      await api("/api/cloudreve/scan", { method: "POST" });
      setTimeout(load, 2000);
    } catch (e) { setErr(e.message); } finally { setScanning(false); }
  };

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
            {!auth.authorized && (
              <div className="sp-sub">
                <a href={`${BASE}/api/auth/cloudreve/start`}>点此前往授权 →</a>
              </div>
            )}
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
          <button className="btn btn-secondary btn-sm" onClick={triggerScan}
            disabled={scanning || isScanning}>
            {isScanning ? "扫描中" : "触发扫描"}
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Batch detail ─────────────────────────────────────────────────────────────

function BatchDetail({ batchId, onBack }) {
  const [batch, setBatch] = useState(null);
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() =>
    api(`/api/admin/candidates/${batchId}`).then(setBatch).catch((e) => setErr(e.message)),
  [batchId]);
  useEffect(() => { load(); }, [load]);

  const edit = async (itemId, status) => {
    setBusy(true);
    try {
      await api(`/api/admin/candidates/${batchId}`, {
        method: "PATCH",
        body: { edits: [{ item_id: itemId, status }] },
      });
      await load();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const doPreview = async () => {
    setBusy(true); setPreview(null); setErr("");
    try {
      setPreview(await api(`/api/admin/candidates/${batchId}/preview`, { method: "POST" }));
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const doCommit = async () => {
    // eslint-disable-next-line no-restricted-globals
    if (!confirm("确认将所有已接受条目写入知识图谱？")) return;
    setBusy(true); setErr("");
    try {
      setResult(await api(`/api/admin/candidates/${batchId}/commit`, { method: "POST" }));
      await load();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const items = batch?.items ?? [];
  const committed = batch?.status === "committed";
  const pendingCount = items.filter((i) => i.status === "candidate").length;
  const acceptedCount = items.filter((i) => i.status === "accepted").length;

  return (
    <div>
      <div className="btn-row" style={{ marginBottom: 14 }}>
        <button className="btn btn-ghost btn-sm" onClick={onBack}>← 返回列表</button>
        {batch && <StatusPill s={batch.status} />}
      </div>

      {err && <Alert style={{ marginBottom: 12 }}>{err}</Alert>}

      {batch && (
        <div className="card">
          <div className="card-header">
            <div>
              <div className="batch-uri" style={{ maxWidth: "none" }}>{batch.source_uri}</div>
              <div className="text-xs muted" style={{ marginTop: 4 }}>ID: {batch.id}</div>
            </div>
          </div>
          <div className="card-body">
            <div className="mini-stat-row">
              <div className="mini-stat">
                <div className="mini-stat-value">{items.length}</div>
                <div className="mini-stat-label">总条目</div>
              </div>
              <div className="mini-stat">
                <div className="mini-stat-value" style={{ color: "#b45309" }}>{pendingCount}</div>
                <div className="mini-stat-label">待审核</div>
              </div>
              <div className="mini-stat">
                <div className="mini-stat-value" style={{ color: "#15803d" }}>{acceptedCount}</div>
                <div className="mini-stat-label">已接受</div>
              </div>
            </div>

            <div className="item-list">
              {items.map((item) => (
                <div key={item.id} className={`item-card ${item.status}`}>
                  <div className="item-body">
                    <div className="item-title">
                      <span className="item-kind">[{item.kind}]</span>
                      {item.payload?.label ?? item.payload?.source ?? "—"}
                      {item.payload?.target && (
                        <span className="item-arrow"> → {item.payload.target}</span>
                      )}
                    </div>
                    <div className="item-meta">
                      {item.payload?.type && <span>类型: {item.payload.type}</span>}
                      {item.payload?.relation && <span>关系: {item.payload.relation}</span>}
                      {item.review_note && (
                        <span style={{ color: "#b45309" }}>{item.review_note}</span>
                      )}
                    </div>
                  </div>
                  <div className="item-actions">
                    <StatusPill s={item.status} />
                    {!committed && (
                      <>
                        <button className="btn btn-success btn-sm btn-icon"
                          title="接受" disabled={busy} onClick={() => edit(item.id, "accepted")}>✓</button>
                        <button className="btn btn-danger btn-sm btn-icon"
                          title="拒绝" disabled={busy} onClick={() => edit(item.id, "rejected")}>✗</button>
                      </>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {!committed && (
              <div className="btn-row" style={{ marginTop: 14 }}>
                <button className="btn btn-secondary" disabled={busy} onClick={doPreview}>
                  预览变更
                </button>
                <button className="btn btn-primary" disabled={busy || acceptedCount === 0}
                  onClick={doCommit}>
                  提交到图谱（{acceptedCount} 条）
                </button>
              </div>
            )}

            {preview && (
              <Alert type="info" style={{ marginTop: 12 }}>
                <strong>变更预览：</strong>
                {Object.entries(preview.summary ?? {}).map(([k, v]) => `${k}: ${v}`).join(" · ")}
                {preview.warnings?.map((w, i) => <div key={i}>{w}</div>)}
              </Alert>
            )}
            {result && (
              <Alert type="success" style={{ marginTop: 12 }}>
                ✓ 已提交 {result.committed_items} 个条目，创建 {result.evidence_created} 个证据记录
              </Alert>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Candidates tab ───────────────────────────────────────────────────────────

function CandidatesTab() {
  const [batches, setBatches] = useState([]);
  const [selected, setSelected] = useState(null);
  const [filter, setFilter] = useState("");
  const [extractUri, setExtractUri] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const d = await api("/api/admin/candidates?limit=100");
      setBatches(d.batches ?? []); setErr("");
    } catch (e) { setErr(e.message); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const extract = async () => {
    if (!extractUri.trim()) return;
    setBusy(true); setMsg(null);
    try {
      await api("/api/admin/candidates/extract", {
        method: "POST",
        body: { uri: extractUri, requested_by: "web-console" },
      });
      setMsg({ type: "success", text: "✓ 抽取已触发，约 1 分钟后可刷新查看" });
      setExtractUri("");
      setTimeout(load, 4000);
    } catch (e) {
      setMsg({ type: "error", text: e.message });
    } finally { setBusy(false); }
  };

  if (selected) {
    return <BatchDetail batchId={selected} onBack={() => { setSelected(null); load(); }} />;
  }

  const filtered = filter
    ? batches.filter((b) => b.source_uri?.includes(filter) || b.status?.includes(filter))
    : batches;

  return (
    <div>
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-header"><span className="card-title">触发文件抽取</span></div>
        <div className="card-body">
          <div className="input-row">
            <div className="form-group">
              <input className="form-control" value={extractUri}
                onChange={(e) => setExtractUri(e.target.value)}
                placeholder="cloudreve://path/to/文件.md"
                onKeyDown={(e) => e.key === "Enter" && extract()} />
            </div>
            <button className="btn btn-primary" onClick={extract}
              disabled={busy || !extractUri.trim()}>
              {busy ? "处理中…" : "触发抽取"}
            </button>
          </div>
          {msg && <Alert type={msg.type} style={{ marginTop: 10 }}>{msg.text}</Alert>}
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">候选批次（{filtered.length}）</span>
          <div className="btn-row">
            <input className="form-control" style={{ width: 180, marginTop: 0 }}
              placeholder="过滤 URI / 状态…"
              value={filter} onChange={(e) => setFilter(e.target.value)} />
            <button className="btn btn-secondary btn-sm" onClick={load}>刷新</button>
          </div>
        </div>
        <div className="card-body">
          {err && <Alert style={{ marginBottom: 12 }}>{err}</Alert>}
          {filtered.length === 0 ? (
            <p className="muted">暂无候选批次</p>
          ) : (
            <div className="batch-list">
              {filtered.map((b) => (
                <button key={b.id} className="batch-row" onClick={() => setSelected(b.id)}>
                  <StatusPill s={b.status} />
                  <div className="batch-info">
                    <div className="batch-uri">{b.source_uri}</div>
                    <div className="batch-meta">
                      {new Date(b.created_at).toLocaleString()} · {b.requested_by}
                    </div>
                  </div>
                  <span className="batch-count">→</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
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

// ─── Q&A tab ─────────────────────────────────────────────────────────────────

function QATab() {
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const ask = async () => {
    const q = question.trim();
    if (!q) return;
    setLoading(true); setErr(""); setQuestion("");
    try {
      const data = await api("/api/graph/ask", {
        method: "POST",
        body: { question: q, requested_by: "web-console" },
      });
      setHistory((h) => [...h, { q, a: data.answer ?? JSON.stringify(data, null, 2) }]);
    } catch (e) { setErr(e.message); setQuestion(q); } finally { setLoading(false); }
  };

  return (
    <div>
      {history.map((item, i) => (
        <div className="card" key={i} style={{ marginBottom: 12 }}>
          <div className="card-header" style={{ background: "#f8fafc" }}>
            <span className="qa-history-q">❓ {item.q}</span>
          </div>
          <div className="card-body">
            <div className="qa-answer">{item.a}</div>
          </div>
        </div>
      ))}

      {err && <Alert style={{ marginBottom: 12 }}>{err}</Alert>}

      <div className="card">
        <div className="card-body">
          <div className="form-group" style={{ marginBottom: 12 }}>
            <textarea className="form-control" style={{ minHeight: 80 }}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="向知识图谱提问，例如：智慧园区中有哪些传感器设备？"
              onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ask(); }}
            />
          </div>
          <div className="btn-row">
            <button className="btn btn-primary" disabled={loading || !question.trim()} onClick={ask}>
              {loading ? "思考中…" : "提问（⌘↵）"}
            </button>
            {history.length > 0 && (
              <button className="btn btn-ghost btn-sm" onClick={() => setHistory([])}>
                清空对话
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Cloudreve tab ────────────────────────────────────────────────────────────

function CloudreveTab() {
  const [config, setConfig] = useState(null);
  const [auth, setAuth] = useState(null);
  const [form, setForm] = useState({ cloudreve_base_url: "", client_id: "", client_secret: "" });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  useEffect(() => {
    Promise.all([
      api("/api/auth/cloudreve/config").then(setConfig),
      api("/api/auth/cloudreve/status").then(setAuth),
    ]).catch((e) => setMsg({ type: "error", text: e.message }));
  }, []);

  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      const redirectUri = new URL("/api/auth/cloudreve/callback", window.location.origin).toString();
      const c = await api("/api/auth/cloudreve/config", {
        method: "POST",
        body: { ...form, redirect_uri: redirectUri, scope: "openid profile offline_access Files.Read" },
      });
      setConfig(c);
      setMsg({ type: "success", text: "✓ 配置已保存" });
    } catch (e) { setMsg({ type: "error", text: e.message }); } finally { setBusy(false); }
  };

  return (
    <div>
      {auth && (
        <div className={`status-panel ${auth.authorized ? "ok" : "warn"}`}>
          <span className="sp-icon">{auth.authorized ? "✓" : "⚠"}</span>
          <div className="sp-content">
            <div className="sp-title">Cloudreve OAuth {auth.authorized ? "已授权" : "未授权"}</div>
            {config?.client_id && <div className="sp-sub">Client ID: {config.client_id}</div>}
          </div>
          <button className="btn btn-primary btn-sm"
            onClick={() => window.location.assign(`${BASE}/api/auth/cloudreve/start`)}
            disabled={!config?.configured}>
            {auth.authorized ? "重新授权" : "立即授权"}
          </button>
        </div>
      )}

      <div className="card">
        <div className="card-header"><span className="card-title">OAuth 应用配置</span></div>
        <div className="card-body">
          <div className="oauth-fields">
            <div className="form-group">
              <label className="form-label">Cloudreve 地址</label>
              <input className="form-control" value={form.cloudreve_base_url}
                onChange={(e) => setForm({ ...form, cloudreve_base_url: e.target.value })}
                placeholder="http://localhost:5212" />
            </div>
            <div className="form-group">
              <label className="form-label">Client ID</label>
              <input className="form-control" value={form.client_id}
                onChange={(e) => setForm({ ...form, client_id: e.target.value })} />
            </div>
            <div className="form-group">
              <label className="form-label">Client Secret</label>
              <input className="form-control" type="password" value={form.client_secret}
                onChange={(e) => setForm({ ...form, client_secret: e.target.value })} />
            </div>
          </div>
          <div className="btn-row" style={{ marginTop: 16 }}>
            <button className="btn btn-primary" onClick={save} disabled={busy}>
              {busy ? "保存中…" : "保存配置"}
            </button>
          </div>
          {msg && <Alert type={msg.type} style={{ marginTop: 12 }}>{msg.text}</Alert>}
        </div>
      </div>
    </div>
  );
}

// ─── App shell ────────────────────────────────────────────────────────────────

const TABS = [
  { id: "dashboard", label: "仪表盘" },
  { id: "candidates", label: "候选审核" },
  { id: "graph", label: "知识图谱" },
  { id: "qa", label: "图谱问答" },
  { id: "cloudreve", label: "Cloudreve" },
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
        {tab === "candidates" && <CandidatesTab />}
        {tab === "graph" && <GraphTab />}
        {tab === "qa" && <QATab />}
        {tab === "cloudreve" && <CloudreveTab />}
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);