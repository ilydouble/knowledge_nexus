import React, { useCallback, useEffect, useState } from "react";
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
  if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`);
  return res.json();
}

function useInterval(fn, ms) {
  useEffect(() => {
    const id = setInterval(fn, ms);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

function StatusPill({ s }) {
  return <span className={`status ${s}`}>{s}</span>;
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
  useInterval(load, 8000);

  const triggerScan = async () => {
    setScanning(true);
    try {
      await api("/api/cloudreve/scan", { method: "POST" });
      setTimeout(load, 2000);
    } catch (e) { setErr(e.message); } finally { setScanning(false); }
  };

  if (!dash && !err) return <p className="muted">加载中…</p>;

  const { batches = {}, items = {}, stale_evidence = 0 } = dash || {};

  return (
    <div>
      {err && <p className="error">{err}</p>}
      <section className="metrics">
        <article><span>{batches.total ?? 0}</span><small>候选批次</small></article>
        <article><span>{batches.committed ?? 0}</span><small>已提交</small></article>
        <article><span>{items.candidate ?? 0}</span><small>待审核</small></article>
        <article><span>{items.accepted ?? 0}</span><small>已接受</small></article>
        <article><span>{stale_evidence}</span><small>过期证据</small></article>
      </section>

      {auth && (
        <div className={`authState ${auth.authorized ? "ready" : ""}`} style={{ marginBottom: 12 }}>
          <strong>Cloudreve {auth.authorized ? "✓ 已授权" : "✗ 未授权"}</strong>
          {!auth.authorized && <small><a href={`${BASE}/api/auth/cloudreve/start`}>点此授权</a></small>}
        </div>
      )}

      {scan && (
        <div className={`scanPanel ${scan.is_scanning ? "scanning" : scan.error ? "error" : "done"}`}>
          <strong>文件扫描</strong>
          <small>{scan.is_scanning ? "扫描中…" : scan.finished_at ? `上次: ${new Date(scan.finished_at).toLocaleString()}` : "从未扫描"}</small>
          {scan.files_found != null && <small>发现 {scan.files_found} 个文件，本次新增 {scan.files_queued ?? 0} 个</small>}
          {scan.error && <small className="errorText">{scan.error}</small>}
        </div>
      )}
      <button className="miniButton primary" onClick={triggerScan}
        disabled={scanning || scan?.is_scanning} style={{ marginTop: 10 }}>
        {scan?.is_scanning ? "扫描中…" : "触发全量扫描"}
      </button>
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
      await api(`/api/admin/candidates/${batchId}`, { method: "PATCH", body: { edits: [{ item_id: itemId, status }] } });
      await load();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const doPreview = async () => {
    setBusy(true); setPreview(null); setErr("");
    try { setPreview(await api(`/api/admin/candidates/${batchId}/preview`, { method: "POST" })); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  const doCommit = async () => {
    setBusy(true); setErr("");
    try { setResult(await api(`/api/admin/candidates/${batchId}/commit`, { method: "POST" })); await load(); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  if (!batch && !err) return <p className="muted">加载中…</p>;

  const items = batch?.items ?? [];
  const committed = batch?.status === "committed";

  return (
    <div>
      <div className="panelHeader">
        <button className="miniButton" onClick={onBack}>← 返回</button>
        {batch && <StatusPill s={batch.status} />}
      </div>
      {err && <p className="error" style={{ marginTop: 8 }}>{err}</p>}
      {batch && (
        <>
          <h3 style={{ marginTop: 12, wordBreak: "break-all" }}>{batch.source_uri}</h3>
          <p className="muted" style={{ fontSize: 12 }}>ID: {batch.id}</p>
          <div className="detailGrid">
            <article><small>总条目</small><strong>{items.length}</strong></article>
            <article><small>待审核</small><strong>{items.filter(i => i.status === "candidate").length}</strong></article>
            <article><small>已接受</small><strong>{items.filter(i => i.status === "accepted").length}</strong></article>
          </div>
          <div className="list" style={{ maxHeight: 340, overflowY: "auto" }}>
            {items.map((item) => (
              <div key={item.id} className="listItem" style={{ display: "flex", gap: 8 }}>
                <div style={{ flex: 1 }}>
                  <StatusPill s={item.status} />
                  <strong style={{ fontSize: 12 }}>
                    [{item.kind}] {item.payload?.label ?? item.payload?.source ?? "—"}
                    {item.payload?.target ? ` → ${item.payload.target}` : ""}
                  </strong>
                  {item.payload?.type && <small>类型: {item.payload.type}</small>}
                  {item.payload?.relation && <small>关系: {item.payload.relation}</small>}
                  {item.review_note && <small className="warningText">{item.review_note}</small>}
                </div>
                {!committed && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 4, flexShrink: 0 }}>
                    <button className="miniButton primary" disabled={busy} onClick={() => edit(item.id, "accepted")}>✓</button>
                    <button className="miniButton" disabled={busy} onClick={() => edit(item.id, "rejected")}>✗</button>
                  </div>
                )}
              </div>
            ))}
          </div>
          {!committed && (
            <div className="jobActions" style={{ marginTop: 12 }}>
              <button className="miniButton" disabled={busy} onClick={doPreview}>预览变更</button>
              <button className="miniButton primary" disabled={busy} onClick={doCommit}>提交到图谱</button>
            </div>
          )}
          {preview && (
            <div className="preview-box" style={{ marginTop: 10 }}>
              <strong>变更预览：</strong>
              {Object.entries(preview.summary ?? {}).map(([k, v]) => `${k}: ${v}`).join(" · ")}
              {preview.warnings?.map((w, i) => <div key={i} className="warningText" style={{ marginTop: 4 }}>{w}</div>)}
            </div>
          )}
          {result && (
            <div className="preview-box" style={{ marginTop: 10 }}>
              ✓ 已提交 {result.committed_items} 个条目，创建 {result.evidence_created} 个证据
            </div>
          )}
        </>
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
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try { const d = await api("/api/admin/candidates?limit=100"); setBatches(d.batches ?? []); setErr(""); }
    catch (e) { setErr(e.message); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const extract = async () => {
    if (!extractUri.trim()) return;
    setBusy(true); setMsg("");
    try {
      await api("/api/admin/candidates/extract", { method: "POST", body: { uri: extractUri, requested_by: "web-console" } });
      setMsg("✓ 抽取已触发");
      await load();
    } catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };

  if (selected) return <BatchDetail batchId={selected} onBack={() => { setSelected(null); load(); }} />;

  const filtered = filter
    ? batches.filter((b) => b.source_uri?.includes(filter) || b.status?.includes(filter))
    : batches;

  return (
    <div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 12 }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <label style={{ margin: 0 }}>触发抽取 (URI)
            <input value={extractUri} onChange={(e) => setExtractUri(e.target.value)} placeholder="cloudreve://my/文件.md" />
          </label>
        </div>
        <button className="miniButton primary" onClick={extract} disabled={busy || !extractUri.trim()} style={{ marginTop: 22 }}>抽取</button>
        <button className="miniButton" onClick={load} style={{ marginTop: 22 }}>刷新</button>
      </div>
      {msg && <p className={msg.startsWith("✓") ? "preview-box" : "error"} style={{ marginBottom: 10 }}>{msg}</p>}
      {err && <p className="error">{err}</p>}
      <input placeholder="按 URI 或状态过滤…" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ marginBottom: 12 }} />
      {filtered.length === 0 ? (
        <p className="muted">暂无候选批次</p>
      ) : (
        <div className="list">
          {filtered.map((b) => (
            <button key={b.id} className="listItem"
              style={{ display: "block", width: "100%", textAlign: "left", background: "transparent", cursor: "pointer", border: "1px solid #dbe4ee", borderRadius: 8, padding: 12 }}
              onClick={() => setSelected(b.id)}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
                <StatusPill s={b.status} />
                <strong style={{ fontSize: 13, wordBreak: "break-all" }}>{b.source_uri}</strong>
              </div>
              <small style={{ color: "#6b7c8f" }}>{new Date(b.created_at).toLocaleString()} · {b.requested_by}</small>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Cloudreve OAuth tab ──────────────────────────────────────────────────────

function CloudreveTab() {
  const [config, setConfig] = useState(null);
  const [auth, setAuth] = useState(null);
  const [form, setForm] = useState({ cloudreve_base_url: "", client_id: "", client_secret: "" });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    Promise.all([
      api("/api/auth/cloudreve/config").then(setConfig),
      api("/api/auth/cloudreve/status").then(setAuth),
    ]).catch((e) => setMsg(e.message));
  }, []);

  const save = async () => {
    setBusy(true); setMsg("");
    try {
      const redirectUri = new URL("/api/auth/cloudreve/callback", window.location.origin).toString();
      const c = await api("/api/auth/cloudreve/config", {
        method: "POST",
        body: { ...form, redirect_uri: redirectUri, scope: "openid profile offline_access Files.Read" },
      });
      setConfig(c);
      setMsg("✓ 保存成功");
    } catch (e) { setMsg(e.message); } finally { setBusy(false); }
  };

  return (
    <div>
      <h2>Cloudreve OAuth 配置</h2>
      {auth && (
        <div className={`authState ${auth.authorized ? "ready" : ""}`} style={{ marginBottom: 12 }}>
          <strong>{auth.authorized ? "✓ 已授权" : "✗ 未授权"}</strong>
          {config?.client_id && <small>Client ID: {config.client_id}</small>}
        </div>
      )}
      <div className="oauthSetup">
        <strong>OAuth App 配置</strong>
        <label>Cloudreve 地址
          <input value={form.cloudreve_base_url} onChange={(e) => setForm({ ...form, cloudreve_base_url: e.target.value })} placeholder="http://localhost:5212" />
        </label>
        <label>Client ID
          <input value={form.client_id} onChange={(e) => setForm({ ...form, client_id: e.target.value })} />
        </label>
        <label>Client Secret
          <input type="password" value={form.client_secret} onChange={(e) => setForm({ ...form, client_secret: e.target.value })} />
        </label>
        <button className="miniButton primary" onClick={save} disabled={busy}>保存配置</button>
      </div>
      <button style={{ marginTop: 12, width: "auto" }}
        onClick={() => window.location.assign(`${BASE}/api/auth/cloudreve/start`)}
        disabled={!config?.configured}>
        打开 Cloudreve 授权
      </button>
      {msg && <p className={msg.startsWith("✓") ? "preview-box" : "error"} style={{ marginTop: 12 }}>{msg}</p>}
    </div>
  );
}

// ─── Graph tab ────────────────────────────────────────────────────────────────

function paletteColor(type) {
  const p = {
    researcher: "#f59e0b", person: "#f59e0b", institution: "#10b981",
    organization: "#10b981", method: "#3b82f6", concept: "#8b5cf6", component: "#f97316",
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
        <button className="miniButton" onClick={load} disabled={loading}>{loading ? "加载中…" : "刷新"}</button>
        <label style={{ margin: 0, display: "flex", alignItems: "center", gap: 6, fontWeight: "normal" }}>
          <input type="checkbox" checked={cluster} onChange={(e) => setCluster(e.target.checked)} style={{ width: "auto" }} />
          聚类视图
        </label>
        <span className="graphStats">{nodes.length} 节点 · {edges.length} 关系</span>
      </div>
      {err && <p className="error">{err}</p>}
      <div className="graphMain">
        <GraphView nodes={nodes} edges={edges} clusterMode={cluster} onNodeClick={setSelected} />
        {selected && (
          <aside className="graphSidebar">
            <div className="graphSidebarHeader">
              <h3>{selected.label || selected.id}</h3>
              <button className="miniButton" onClick={() => setSelected(null)}>✕</button>
            </div>
            {selected.isCluster ? (
              <>
                <p className="graphNodeType">集群 · {selected.count} 个节点</p>
                <div className="graphRelList">
                  {selected.members?.map((m) => (
                    <div key={m.id} className="graphRelRow">
                      <span className="relType" style={{ color: paletteColor(m.properties?.type) }}>{m.properties?.type || "节点"}</span>
                      <span>{m.label || m.id}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <>
                {selected.properties?.type && <p className="graphNodeType">{selected.properties.type}</p>}
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

// ─── Q&A tab ──────────────────────────────────────────────────────────────────

function QATab() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const ask = async () => {
    if (!question.trim()) return;
    setLoading(true); setErr(""); setAnswer("");
    try {
      const data = await api("/api/graph/ask", { method: "POST", body: { question, requested_by: "web-console" } });
      setAnswer(data.answer ?? JSON.stringify(data, null, 2));
    } catch (e) { setErr(e.message); } finally { setLoading(false); }
  };

  return (
    <div>
      <label>向知识图谱提问
        <textarea className="question" value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="例如：智慧园区中有哪些传感器设备？"
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ask(); }}
        />
      </label>
      <button style={{ width: "auto" }} disabled={loading || !question.trim()} onClick={ask}>
        {loading ? "思考中…" : "提问 (⌘Enter)"}
      </button>
      {err && <p className="error" style={{ marginTop: 12 }}>{err}</p>}
      {answer && <div className="answer" style={{ marginTop: 16, whiteSpace: "pre-wrap" }}>{answer}</div>}
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
        <span className="app-title">Knowledge OS Console</span>
        <nav className="tab-nav">
          {TABS.map((t) => (
            <button key={t.id} className={`tab-btn${tab === t.id ? " active" : ""}`} onClick={() => setTab(t.id)}>
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
