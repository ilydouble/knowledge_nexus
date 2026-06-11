import React, { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import GraphView from "./GraphView.jsx";

const API_BASE = import.meta.env.VITE_NEXUS_API_BASE || "";

async function api(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`);
  return res.json();
}

function post(path, body) {
  return api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

// ─── Dashboard ────────────────────────────────────────────────────────────────
function Dashboard() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    api("/api/admin/dashboard").then(setData).catch((e) => setErr(e.message));
  }, []);
  if (err) return <p className="error">{err}</p>;
  if (!data) return <p>加载中…</p>;
  const { totals, alerts } = data;
  return (
    <div>
      <h2>知识库仪表盘</h2>
      <div className="metric-row">
        <div className="metric-card"><div className="metric-value">{totals.batches}</div><div className="metric-label">批次</div></div>
        <div className="metric-card"><div className="metric-value">{totals.items}</div><div className="metric-label">条目</div></div>
        <div className="metric-card"><div className="metric-value">{totals.committed_items}</div><div className="metric-label">已入库</div></div>
        <div className="metric-card"><div className="metric-value">{totals.evidence}</div><div className="metric-label">证据条数</div></div>
      </div>
      {alerts && alerts.length > 0 && (
        <div className="alerts">
          <h3>告警</h3>
          {alerts.map((a, i) => <div key={i} className="alert-item">⚠ {a}</div>)}
        </div>
      )}
    </div>
  );
}

// ─── Batch list + review ──────────────────────────────────────────────────────
function statusBadge(s) {
  const colors = { pending: "#f59e0b", committed: "#10b981", rejected: "#ef4444", accepted: "#3b82f6" };
  return <span style={{ background: colors[s] || "#6b7280", color: "#fff", borderRadius: 4, padding: "1px 6px", fontSize: 11 }}>{s}</span>;
}

function BatchDetail({ batchId, onBack }) {
  const [batch, setBatch] = useState(null);
  const [preview, setPreview] = useState(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => api(`/api/admin/candidates/${batchId}`).then(setBatch), [batchId]);
  useEffect(() => { load(); }, [load]);

  async function bulkAction(action) {
    setBusy(true); setMsg("");
    try { await post(`/api/admin/candidates/${batchId}/${action}-all`); await load(); setMsg(`✓ ${action === "accept" ? "全部接受" : "全部拒绝"}成功`); }
    catch (e) { setMsg("❌ " + e.message); }
    finally { setBusy(false); }
  }
  async function doPreview() {
    setBusy(true); setMsg(""); setPreview(null);
    try { const p = await post(`/api/admin/candidates/${batchId}/preview`); setPreview(p); }
    catch (e) { setMsg("❌ " + e.message); }
    finally { setBusy(false); }
  }
  async function doCommit() {
    if (!window.confirm("确认写入 Neo4j？")) return;
    setBusy(true); setMsg("");
    try { await post(`/api/admin/candidates/${batchId}/commit`); await load(); setMsg("✓ 已提交"); }
    catch (e) { setMsg("❌ " + e.message); }
    finally { setBusy(false); }
  }

  if (!batch) return <p>加载中…</p>;
  return (
    <div>
      <button onClick={onBack}>← 返回列表</button>
      <h3>批次 {batchId.slice(0, 8)}… — {statusBadge(batch.status)}</h3>
      <p style={{ color: "#94a3b8" }}>{batch.source_uri}</p>
      <div style={{ marginBottom: 8, display: "flex", gap: 8 }}>
        <button onClick={() => bulkAction("accept")} disabled={busy}>全部接受</button>
        <button onClick={() => bulkAction("reject")} disabled={busy}>全部拒绝</button>
        <button onClick={doPreview} disabled={busy}>预览变更</button>
        <button onClick={doCommit} disabled={busy || batch.status !== "accepted"} style={{ background: "#10b981" }}>提交入库</button>
      </div>
      {msg && <p>{msg}</p>}
      {preview && (
        <div className="preview-box">
          <b>变更预览：</b> +{preview.new_nodes} 节点 / +{preview.new_edges} 边 / ~{preview.updated_nodes} 更新
        </div>
      )}
      <table className="data-table">
        <thead><tr><th>类型</th><th>内容</th><th>状态</th></tr></thead>
        <tbody>
          {(batch.items || []).map((item) => (
            <tr key={item.id}>
              <td><span className="tag">{item.item_type}</span></td>
              <td style={{ fontSize: 12 }}>{item.item_type === "node" ? `${item.data?.label} (${item.data?.type})` : `${item.data?.source} → ${item.data?.target} [${item.data?.relation}]`}</td>
              <td>{statusBadge(item.status)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CandidatesPanel() {
  const [batches, setBatches] = useState([]);
  const [selected, setSelected] = useState(null);
  const [extractUri, setExtractUri] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const load = useCallback(() => api("/api/admin/candidates?limit=50").then((r) => setBatches(r.batches || r)), []);
  useEffect(() => { load(); }, [load]);

  async function extract() {
    if (!extractUri) return;
    setBusy(true); setMsg("");
    try { await post("/api/admin/candidates/extract", { uri: extractUri, requested_by: "web-ui" }); await load(); setMsg("✓ 抽取已触发"); }
    catch (e) { setMsg("❌ " + e.message); }
    finally { setBusy(false); }
  }

  if (selected) return <BatchDetail batchId={selected} onBack={() => { setSelected(null); load(); }} />;

  return (
    <div>
      <h2>候选批次管理</h2>
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <input value={extractUri} onChange={(e) => setExtractUri(e.target.value)} placeholder="cloudreve://my/文件路径" style={{ flex: 1 }} />
        <button onClick={extract} disabled={busy || !extractUri}>触发抽取</button>
      </div>
      {msg && <p>{msg}</p>}
      <table className="data-table">
        <thead><tr><th>来源</th><th>状态</th><th>条目</th><th>操作</th></tr></thead>
        <tbody>
          {batches.map((b) => (
            <tr key={b.id}>
              <td style={{ fontSize: 12, maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis" }}>{b.source_uri}</td>
              <td>{statusBadge(b.status)}</td>
              <td>{b.item_count ?? "—"}</td>
              <td><button onClick={() => setSelected(b.id)}>详情</button></td>
            </tr>
          ))}
          {batches.length === 0 && <tr><td colSpan={4} style={{ textAlign: "center", color: "#6b7280" }}>暂无批次</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

// ─── Cloudreve ────────────────────────────────────────────────────────────────
const REDIRECT_URI = new URL("/api/auth/cloudreve/callback", API_BASE || window.location.origin).toString();

function CloudrevePanel() {
  const [auth, setAuth] = useState({ authorized: false });
  const [config, setConfig] = useState({ configured: false });
  const [scan, setScan] = useState({ status: "idle", files_found: 0, files_queued: 0 });
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [cloudreveUrl, setCloudreveUrl] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([
      api("/api/auth/cloudreve/status").then(setAuth).catch(() => {}),
      api("/api/auth/cloudreve/config").then(setConfig).catch(() => {}),
      api("/api/cloudreve/scan/status").then(setScan).catch(() => {}),
    ]);
  }, []);

  async function saveConfig() {
    setBusy(true); setMsg("");
    try {
      const c = await post("/api/auth/cloudreve/config", { cloudreve_base_url: cloudreveUrl, client_id: clientId, client_secret: clientSecret, redirect_uri: REDIRECT_URI, scope: "openid profile offline_access Files.Read" });
      setConfig(c); setMsg("✓ 已保存");
    } catch (e) { setMsg("❌ " + e.message); }
    finally { setBusy(false); }
  }

  async function triggerScan() {
    setBusy(true); setMsg("");
    try { await post("/api/cloudreve/scan"); setMsg("✓ 扫描已启动，稍后刷新"); }
    catch (e) { setMsg("❌ " + e.message); }
    finally { setBusy(false); }
  }

  return (
    <div>
      <h2>Cloudreve 连接</h2>
      <div className="metric-row">
        <div className="metric-card"><div className="metric-value">{auth.authorized ? "✓ 已授权" : "✗ 未授权"}</div><div className="metric-label">授权状态</div></div>
        <div className="metric-card"><div className="metric-value">{scan.files_found}</div><div className="metric-label">发现文件</div></div>
        <div className="metric-card"><div className="metric-value">{scan.files_queued}</div><div className="metric-label">已排队</div></div>
      </div>
      <h3>OAuth 配置</h3>
      <div style={{ display: "grid", gap: 8, maxWidth: 500 }}>
        <input value={cloudreveUrl} onChange={(e) => setCloudreveUrl(e.target.value)} placeholder="Cloudreve 地址 (http://localhost:5212)" />
        <input value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="Client ID" />
        <input value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} placeholder="Client Secret" type="password" />
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={saveConfig} disabled={busy}>保存配置</button>
          <button onClick={() => window.location.assign(`${API_BASE}/api/auth/cloudreve/start`)} disabled={!config.configured}>授权登录</button>
          <button onClick={triggerScan} disabled={busy || !auth.authorized}>触发全量扫描</button>
        </div>
      </div>
      {msg && <p>{msg}</p>}
    </div>
  );
}

// ─── App shell ────────────────────────────────────────────────────────────────
const TABS = [
  { id: "dashboard", label: "仪表盘" },
  { id: "candidates", label: "候选审核" },
  { id: "graph", label: "知识图谱" },
  { id: "cloudreve", label: "Cloudreve" },
];

function App() {
  const [tab, setTab] = useState("dashboard");
  const [graphData, setGraphData] = useState({ nodes: [], edges: [] });
  const [graphLoading, setGraphLoading] = useState(false);

  useEffect(() => {
    if (tab !== "graph") return;
    setGraphLoading(true);
    api("/api/graph").then(setGraphData).catch(() => {}).finally(() => setGraphLoading(false));
  }, [tab]);

  return (
    <div className="app">
      <header className="app-header">
        <span className="app-title">Knowledge OS</span>
        <nav className="tab-nav">
          {TABS.map((t) => (
            <button key={t.id} className={`tab-btn${tab === t.id ? " active" : ""}`} onClick={() => setTab(t.id)}>{t.label}</button>
          ))}
        </nav>
      </header>
      <main className="app-main">
        {tab === "dashboard" && <Dashboard />}
        {tab === "candidates" && <CandidatesPanel />}
        {tab === "graph" && (graphLoading ? <p>图谱加载中…</p> : <GraphView nodes={graphData.nodes || []} edges={graphData.edges || []} />)}
        {tab === "cloudreve" && <CloudrevePanel />}
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
import { createRoot } from "react-dom/client";
import "./styles.css";
import GraphView from "./GraphView.jsx";

const API_BASE = import.meta.env.VITE_NEXUS_API_BASE || "";
const DEFAULT_OAUTH_REDIRECT_URI = new URL(
  "/api/auth/cloudreve/callback",
  API_BASE || window.location.origin,
).toString();

async function requestJson(path, options) {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json();
}

function paletteColor(type) {
  const palette = {
    researcher: "#f59e0b", person: "#f59e0b",
    institution: "#10b981", organization: "#10b981",
    method: "#3b82f6", concept: "#8b5cf6",
    dataset: "#ec4899", metric: "#14b8a6",
    component: "#f97316", api: "#06b6d4",
    technology: "#6366f1", tool: "#f59e0b", framework: "#8b5cf6",
  };
  return palette[(type || "").toLowerCase()] || "#94a3b8";
}

function statusLabel(status) {
  const labels = {
    pending: "等待中",
    processing: "处理中",
    processed: "已处理",
    running: "处理中",
    succeeded: "已完成",
    failed: "失败",
    skipped: "已跳过",
  };
  return labels[status] || status;
}

function stageLabel(stage) {
  const labels = {
    queued: "排队",
    gate: "格式过滤",
    download: "下载",
    parse: "解析",
    semantic_extract: "语义提取",
    persist: "入库",
  };
  return labels[stage] || stage || "未知";
}

function cloudreveAuthHint(authStatus) {
  if (authStatus.error === "refresh_failed") {
    return "refresh token 已失效，请重新授权";
  }
  if (authStatus.has_refresh_token) {
    return "refresh token 已验证";
  }
  return "尚未保存 refresh token";
}

function App() {
  const [tab, setTab] = useState("workbench"); // "workbench" | "graph"
  const [files, setFiles] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [selectedUri, setSelectedUri] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [knowledge, setKnowledge] = useState(null);
  const [uri, setUri] = useState("cloudreve://my/demo.md");
  const [content, setContent] = useState("Infrared sensor thermal calibration notes connect to project delivery risks.");
  const [question, setQuestion] = useState("有哪些已经索引的文档？");
  const [answer, setAnswer] = useState(null);
  const [authStatus, setAuthStatus] = useState({ authorized: false });
  const [authConfig, setAuthConfig] = useState({ configured: false });
  const [scanStatus, setScanStatus] = useState({ status: "idle", files_found: 0, files_queued: 0, is_scanning: false });
  const [oauthClientId, setOauthClientId] = useState("");
  const [oauthClientSecret, setOauthClientSecret] = useState("");
  const [editingOAuthConfig, setEditingOAuthConfig] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [currentPage, setCurrentPage] = useState(0);
  const [pageSize, setPageSize] = useState(50);

  // Graph tab state
  const [graphMode, setGraphMode] = useState("full"); // "full" | "doc"
  const [graphDocUri, setGraphDocUri] = useState("");
  const [graphData, setGraphData] = useState({ nodes: [], edges: [] });
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphSelectedNode, setGraphSelectedNode] = useState(null);
  const [graphClusterMode, setGraphClusterMode] = useState(false);

  const selectedDocument = useMemo(
    () => documents.find((document) => document.uri === selectedUri),
    [documents, selectedUri],
  );
  const selectedFile = useMemo(
    () => files.find((file) => file.uri === selectedUri),
    [files, selectedUri],
  );
  const filteredFiles = useMemo(
    () => (statusFilter === "all" ? files : files.filter((file) => file.status === statusFilter)),
    [files, statusFilter],
  );
  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(filteredFiles.length / pageSize)),
    [filteredFiles.length, pageSize],
  );
  const pagedFiles = useMemo(
    () => filteredFiles.slice(currentPage * pageSize, (currentPage + 1) * pageSize),
    [filteredFiles, currentPage, pageSize],
  );
  const selectedAttempts = useMemo(
    () => jobs.filter((job) => job.uri === selectedUri),
    [jobs, selectedUri],
  );
  const metrics = useMemo(() => {
    const latestByUri = new Map();
    for (const job of jobs) {
      const existing = latestByUri.get(job.uri);
      if (!existing || new Date(job.created_at) > new Date(existing.created_at)) {
        latestByUri.set(job.uri, job);
      }
    }
    const documentUris = new Set(documents.map((document) => document.uri));
    let succeeded = 0;
    let processing = 0;
    let failed = 0;
    let pending = 0;
    let skipped = 0;
    for (const file of files) {
      const status = latestByUri.get(file.uri)?.status || file.status;
      if (status === "succeeded" || status === "processed" || documentUris.has(file.uri)) succeeded += 1;
      else if (status === "running" || status === "processing") processing += 1;
      else if (status === "failed") failed += 1;
      else if (status === "skipped") skipped += 1;
      else if (status === "pending") pending += 1;
    }
    for (const uri of documentUris) {
      if (!files.some((file) => file.uri === uri)) succeeded += 1;
    }
    return { succeeded, processing, failed, pending, skipped };
  }, [documents, files, jobs]);

  async function refresh() {
    const [nextFiles, nextDocuments, nextJobs, nextAuthStatus, nextAuthConfig, nextScanStatus] = await Promise.all([
      requestJson("/api/ingestion/files"),
      requestJson("/api/documents"),
      requestJson("/api/ingestion/jobs"),
      requestJson("/api/auth/cloudreve/status"),
      requestJson("/api/auth/cloudreve/config"),
      requestJson("/api/cloudreve/scan/status").catch(() => ({ status: "idle", files_found: 0, files_queued: 0, is_scanning: false })),
    ]);
    setFiles(nextFiles);
    setDocuments(nextDocuments);
    setJobs(nextJobs);
    setAuthStatus(nextAuthStatus);
    setAuthConfig(nextAuthConfig);
    setScanStatus(nextScanStatus);
    if (!selectedUri && nextFiles.length) {
      setSelectedUri(nextFiles[0].uri);
    }
  }

  async function authorizeCloudreve() {
    if (!authConfig.configured) {
      setMessage("请先在 Cloudreve 管理面板创建 OAuth App，并在这里保存 Client ID / Secret。");
      return;
    }
    if (authConfig.redirect_uri !== DEFAULT_OAUTH_REDIRECT_URI) {
      setBusy(true);
      setMessage("");
      try {
        const nextConfig = await requestJson("/api/auth/cloudreve/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            cloudreve_base_url: authConfig.cloudreve_base_url || "http://localhost:5212",
            redirect_uri: DEFAULT_OAUTH_REDIRECT_URI,
            scope: "openid profile offline_access Files.Read",
          }),
        });
        setAuthConfig(nextConfig);
      } catch (error) {
        setMessage(error.message);
        setBusy(false);
        return;
      }
      setBusy(false);
    }
    window.location.assign(`${API_BASE}/api/auth/cloudreve/start`);
  }

  async function saveCloudreveOAuthConfig() {
    setBusy(true);
    setMessage("");
    try {
      const nextConfig = await requestJson("/api/auth/cloudreve/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cloudreve_base_url: authConfig.cloudreve_base_url || "http://localhost:5212",
          client_id: oauthClientId,
          client_secret: oauthClientSecret,
          redirect_uri: DEFAULT_OAUTH_REDIRECT_URI,
          scope: "openid profile offline_access Files.Read",
        }),
      });
      setAuthConfig(nextConfig);
      setOauthClientId("");
      setOauthClientSecret("");
      setEditingOAuthConfig(false);
      setMessage(nextConfig.configured ? "Cloudreve OAuth 配置已保存，可以打开授权。" : "配置还不完整，请补齐 Client ID / Secret。");
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function loadKnowledge(nextUri) {
    if (!nextUri) {
      setKnowledge(null);
      return;
    }
    const result = await requestJson(`/api/files/knowledge?uri=${encodeURIComponent(nextUri)}`);
    setKnowledge(result);
  }

  async function loadGraph(mode, docUri) {
    setGraphLoading(true);
    setGraphSelectedNode(null);
    try {
      const url = mode === "doc" && docUri
        ? `/api/graph?uri=${encodeURIComponent(docUri)}`
        : "/api/graph";
      const result = await requestJson(url);
      setGraphData({
        nodes: result.nodes || [],
        edges: result.edges || [],
        truncated: Boolean(result.truncated),
        total_nodes: result.total_nodes,
      });
    } catch (err) {
      setMessage(err.message);
      setGraphData({ nodes: [], edges: [] });
    } finally {
      setGraphLoading(false);
    }
  }

  useEffect(() => {
    refresh().catch((error) => setMessage(error.message));
    const timer = setInterval(() => {
      refresh().catch(() => {});
    }, 10_000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    loadKnowledge(selectedUri).catch((error) => setMessage(error.message));
  }, [selectedUri]);

  useEffect(() => {
    if (tab === "graph") {
      loadGraph(graphMode, graphDocUri);
    }
  }, [tab, graphMode, graphDocUri]);

  useEffect(() => {
    setCurrentPage((page) => Math.min(page, totalPages - 1));
  }, [totalPages]);

  async function demoIndex() {
    setBusy(true);
    setMessage("");
    try {
      await requestJson("/api/ingestion/demo-index", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ uri, content, requested_by: "demo-user" }),
      });
      await refresh();
      setSelectedUri(uri);
      setMessage("演示文本已写入知识库。");
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function processCloudreveFile() {
    setBusy(true);
    setMessage("");
    try {
      const result = await requestJson("/api/ingestion/sync?process=true", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ uri, requested_by: "demo-user" }),
      });
      await refresh();
      setSelectedUri(uri);
      setMessage(result.processing?.success ? "Cloudreve 文档处理完成。" : `处理失败：${result.processing?.error || "未知错误"}`);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function retryFile(file) {
    setBusy(true);
    setMessage("");
    try {
      const result = await requestJson("/api/ingestion/files/retry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ uri: file.uri, requested_by: "demo-user" }),
      });
      await refresh();
      setSelectedUri(file.uri);
      setUri(file.uri);
      setMessage(result.processing?.success ? "已重新处理该文件。" : `重新处理失败：${result.processing?.error || "未知错误"}`);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  function selectFile(file) {
    setSelectedUri(file.uri);
    setUri(file.uri);
  }

  async function scanCloudreve() {
    setBusy(true);
    setMessage("");
    try {
      await requestJson("/api/cloudreve/scan", { method: "POST" });
      setMessage("全量扫描已在后台启动，发现的新文件将自动加入处理队列。");
      setTimeout(() => refresh().catch(() => {}), 3000);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  function scanStatusLabel(status) {
    const labels = { idle: "空闲", scanning: "扫描中…", done: "完成", error: "出错" };
    return labels[status] || status;
  }

  async function askGraph() {
    setBusy(true);
    setMessage("");
    try {
      const result = await requestJson("/api/graphrag/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, requested_by: "demo-user", layers: ["L1", "L2", "L3"] }),
      });
      setAnswer(result);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Knowledge Nexus Console</p>
          <h1>语义处理工作台</h1>
        </div>
        <div className="tabBar">
          <button className={`tabBtn ${tab === "workbench" ? "active" : ""}`} onClick={() => setTab("workbench")}>处理工作台</button>
          <button className={`tabBtn ${tab === "graph" ? "active" : ""}`} onClick={() => setTab("graph")}>知识图谱</button>
        </div>
        <button className="compact" onClick={refresh} disabled={busy}>刷新</button>
      </header>

      {message ? <div className="notice">{message}</div> : null}

      <section className="metrics">
        <article>
          <span>{metrics.succeeded}</span>
          <small>已处理文件</small>
        </article>
        <article>
          <span>{metrics.processing}</span>
          <small>处理中任务</small>
        </article>
        <article>
          <span>{metrics.failed}</span>
          <small>失败文件</small>
        </article>
        <article>
          <span>{metrics.pending}</span>
          <small>待索引文件</small>
        </article>
        <article>
          <span className={`scanDot ${scanStatus.is_scanning ? "scanning" : scanStatus.status}`}>
            {scanStatusLabel(scanStatus.status)}
          </span>
          <small>网盘扫描 · 发现 {scanStatus.files_found} 个文件</small>
        </article>
      </section>

      {tab === "graph" && (
        <section className="graphTab">
          <div className="graphControls">
            <div className="graphModeToggle">
              <button className={`tabBtn ${graphMode === "full" ? "active" : ""}`} onClick={() => setGraphMode("full")}>全部图谱</button>
              <button className={`tabBtn ${graphMode === "doc" ? "active" : ""}`} onClick={() => setGraphMode("doc")}>文档图谱</button>
            </div>
            {graphMode === "doc" && (
              <select value={graphDocUri} onChange={(e) => setGraphDocUri(e.target.value)} className="graphDocSelect">
                <option value="">— 请选择文档 —</option>
                {files.filter((f) => f.status === "processed" || f.status === "succeeded").map((f) => (
                  <option key={f.uri} value={f.uri}>{f.filename}</option>
                ))}
              </select>
            )}
            <button className="compact" onClick={() => loadGraph(graphMode, graphDocUri)} disabled={graphLoading}>
              {graphLoading ? "加载中…" : "刷新图谱"}
            </button>
            {graphMode === "full" && (
              <button className={`tabBtn ${graphClusterMode ? "active" : ""}`} onClick={() => setGraphClusterMode((value) => !value)}>
                {graphClusterMode ? "完整视图" : "集群视图"}
              </button>
            )}
            <span className="graphStats">
              {graphData.nodes.length} 节点 · {graphData.edges.length} 关系
              {graphData.truncated ? ` · 截断（共 ${graphData.total_nodes} 节点）` : ""}
            </span>
          </div>

          {graphData.truncated && (
            <div className="graphTruncatedBanner">
              显示 {graphData.nodes.length} / 共 {graphData.total_nodes} 个节点（已截断）
            </div>
          )}
          <div className="graphMain">
            <GraphView
              nodes={graphData.nodes}
              edges={graphData.edges}
              clusterMode={graphClusterMode}
              onNodeClick={(node) => setGraphSelectedNode(node)}
            />

            {graphSelectedNode && (
              <aside className="graphSidebar">
                <div className="graphSidebarHeader">
                  <h3>{graphSelectedNode.label || graphSelectedNode.id}</h3>
                  <button className="miniButton" onClick={() => setGraphSelectedNode(null)}>✕</button>
                </div>
                {graphSelectedNode.isCluster ? (
                  <>
                    <p className="graphNodeType">集群 · {graphSelectedNode.count} 个节点</p>
                    <h4>成员列表</h4>
                    <div className="graphRelList">
                      {graphSelectedNode.members?.map((member) => (
                        <div key={member.id} className="graphRelRow">
                          <span className="relType" style={{
                            background: `${paletteColor(member.properties?.type)}22`,
                            color: paletteColor(member.properties?.type),
                          }}>
                            {member.properties?.type || "节点"}
                          </span>
                          <span>{member.label || member.id}</span>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <>
                    {graphSelectedNode.properties?.type && (
                      <p className="graphNodeType">{graphSelectedNode.properties.type}</p>
                    )}
                    {graphSelectedNode.summary && (
                      <p className="summary">{graphSelectedNode.summary}</p>
                    )}
                    {graphSelectedNode.uri && (
                      <p className="uri">{graphSelectedNode.uri}</p>
                    )}
                    {graphSelectedNode.properties?.type === undefined && graphSelectedNode.uri?.startsWith("cloudreve://") && (
                      <button className="secondary" onClick={() => {
                        setTab("workbench");
                        setSelectedUri(graphSelectedNode.uri);
                        setUri(graphSelectedNode.uri);
                      }}>在工作台查看</button>
                    )}
                    <h4>相关关系</h4>
                    <div className="graphRelList">
                      {graphData.edges.filter((e) => e.source === graphSelectedNode.id || e.target === graphSelectedNode.id).map((e) => {
                        const otherId = e.source === graphSelectedNode.id ? e.target : e.source;
                        const other = graphData.nodes.find((n) => n.id === otherId);
                        const dir = e.source === graphSelectedNode.id ? "→" : "←";
                        return (
                          <div key={e.id} className="graphRelRow">
                            <span className="relType">{e.relation}</span>
                            <span>{dir} {other?.label || otherId}</span>
                          </div>
                        );
                      })}
                    </div>
                  </>
                )}
              </aside>
            )}
          </div>
        </section>
      )}

      {tab === "workbench" && <section className="workspace">
        <section className="panel fileCenter">
          <div className="panelHeader">
            <h2>文件处理中心</h2>
            <select value={statusFilter} onChange={(event) => { setCurrentPage(0); setStatusFilter(event.target.value); }}>
              <option value="all">全部</option>
              <option value="processed">已处理</option>
              <option value="succeeded">已完成</option>
              <option value="processing">处理中</option>
              <option value="pending">等待中</option>
              <option value="failed">失败</option>
              <option value="skipped">已跳过</option>
            </select>
          </div>
          <div className="fileList">
            {pagedFiles.length ? pagedFiles.map((file) => (

              <button
                className={`fileRow ${selectedUri === file.uri ? "active" : ""}`}
                key={file.uri}
                onClick={() => selectFile(file)}
              >
                <div>
                  <strong>{file.filename}</strong>
                  <small>{file.uri}</small>
                  {file.last_error ? <small className="errorText">{file.last_error}</small> : null}
                </div>
                <div className="fileMeta">
                  <span className={`status ${file.status}`}>{statusLabel(file.status)}</span>
                  <span className="semanticBadge">{stageLabel(file.stage)}</span>
                  <small>{file.attempt_count} 次尝试</small>
                  {file.semantic ? <small>{file.semantic.chunk_count} chunks</small> : <small>未见语义结果</small>}
                </div>
              </button>
            )) : (
              <p className="muted">
                暂无文件记录。点击右侧「扫描全部文件」可抓取 Cloudreve 上的全量文件并加入处理队列。
              </p>
            )}
          </div>
          <div className="pagination">
            <span className="pageInfo">
              第 {currentPage + 1}/{totalPages} 页 · 共 {filteredFiles.length} 条
            </span>
            <div className="pageActions">
              <label>
                每页
                <select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setCurrentPage(0); }}>
                  <option value="20">20</option>
                  <option value="50">50</option>
                  <option value="100">100</option>
                  <option value="200">200</option>
                </select>
                条
              </label>
              <button className="miniButton" disabled={currentPage <= 0} onClick={() => setCurrentPage((page) => Math.max(0, page - 1))}>上一页</button>
              <button className="miniButton" disabled={currentPage >= totalPages - 1} onClick={() => setCurrentPage((page) => Math.min(totalPages - 1, page + 1))}>下一页</button>
            </div>
          </div>
        </section>

        <section className="panel inspector">
          <div className="panelHeader">
            <h2>文件详情</h2>
            {selectedFile ? <span className={`status ${selectedFile.status}`}>{statusLabel(selectedFile.status)}</span> : null}
          </div>

          {selectedFile ? (
            <>
              <p className="uri">{selectedFile.uri}</p>
              <div className="detailGrid">
                <article>
                  <small>当前阶段</small>
                  <strong>{stageLabel(selectedFile.stage)}</strong>
                </article>
                <article>
                  <small>尝试次数</small>
                  <strong>{selectedFile.attempt_count}</strong>
                </article>
                <article>
                  <small>来源</small>
                  <strong>{selectedFile.source}</strong>
                </article>
              </div>
              {selectedFile.last_error ? <p className="jobError">{selectedFile.last_error}</p> : null}
              <button onClick={() => retryFile(selectedFile)} disabled={busy}>重新处理原文件</button>

              <h3>语义结果</h3>
              <p className="summary">{knowledge?.summary || selectedFile.semantic?.summary || "暂无摘要"}</p>

              <h3>标签</h3>
              <div className="chips">
                {knowledge?.tags?.length ? knowledge.tags.map((tag) => <span key={tag}>{tag}</span>) : <small className="muted">暂无标签</small>}
              </div>

              <h3>实体</h3>
              <div className="chips entity">
                {knowledge?.entities?.length ? knowledge.entities.map((entity) => <span key={entity}>{entity}</span>) : <small className="muted">暂无实体</small>}
              </div>

              <h3>最近尝试</h3>
              <div className="jobs">
                {selectedAttempts.length ? selectedAttempts.slice(0, 5).map((job) => (
                  <article className="job" key={job.id}>
                    <div className="jobMeta">
                      <span className={`status ${job.status}`}>{statusLabel(job.status)}</span>
                      <span className="semanticBadge">{stageLabel(job.stage)}</span>
                    </div>
                    <small>{new Date(job.created_at).toLocaleString()} · attempts {job.attempts}</small>
                    {job.error ? <p className="jobError">{job.error}</p> : null}
                  </article>
                )) : <p className="muted">暂无尝试记录。</p>}
              </div>
            </>
          ) : (
            <p className="muted">选择一个文件查看处理详情。</p>
          )}
        </section>

        <aside className="panel actions">
          <h2>Cloudreve 授权</h2>
          <div className={`authState ${authStatus.authorized ? "ready" : ""}`}>
            <strong>{authStatus.authorized ? "授权可用" : "需要授权"}</strong>
            <small>{cloudreveAuthHint(authStatus)}</small>
          </div>

          <div className="oauthSetup">
            <strong>{authConfig.configured ? "OAuth App 已配置" : "OAuth App 未配置"}</strong>
            {authConfig.client_id ? <small>Client ID: {authConfig.client_id}</small> : null}
            <small>Redirect URI: {authConfig.redirect_uri || DEFAULT_OAUTH_REDIRECT_URI}</small>
            {authConfig.configured && authConfig.redirect_uri !== DEFAULT_OAUTH_REDIRECT_URI ? (
              <small className="warningText">将于下次授权前更新为：{DEFAULT_OAUTH_REDIRECT_URI}</small>
            ) : null}
            <small>Scope: openid profile offline_access Files.Read</small>
            {authConfig.configured && !editingOAuthConfig ? (
              <button className="miniButton" onClick={() => setEditingOAuthConfig(true)} disabled={busy}>更新 OAuth 配置</button>
            ) : null}
            {!authConfig.configured || editingOAuthConfig ? (
              <>
                <label>
                  Client ID
                  <input value={oauthClientId} onChange={(event) => setOauthClientId(event.target.value)} />
                </label>
                <label>
                  Client Secret
                  <input type="password" value={oauthClientSecret} onChange={(event) => setOauthClientSecret(event.target.value)} />
                </label>
                <button className="secondary" onClick={saveCloudreveOAuthConfig} disabled={busy}>保存 OAuth 配置</button>
                {editingOAuthConfig ? (
                  <button className="miniButton" onClick={() => setEditingOAuthConfig(false)} disabled={busy}>取消</button>
                ) : null}
              </>
            ) : null}
          </div>
          <button className="secondary" onClick={authorizeCloudreve} disabled={busy}>打开 Cloudreve 授权</button>

          <h2>网盘全量扫描</h2>
          <div className={`scanPanel ${scanStatus.is_scanning ? "scanning" : scanStatus.status}`}>
            <strong>{scanStatusLabel(scanStatus.status)}</strong>
            {scanStatus.finished_at ? (
              <small>上次扫描：{new Date(scanStatus.finished_at).toLocaleString()}</small>
            ) : (
              <small>尚未执行过扫描</small>
            )}
            <small>发现文件：{scanStatus.files_found} 个 · 本次新增队列：{scanStatus.files_queued} 个</small>
            {scanStatus.error ? <small className="errorText">{scanStatus.error}</small> : null}
          </div>
          <button
            className="secondary"
            onClick={scanCloudreve}
            disabled={busy || scanStatus.is_scanning}
          >
            {scanStatus.is_scanning ? "扫描中…" : "扫描全部文件"}
          </button>

          <h2>手动补处理</h2>
          <label>
            Cloudreve URI
            <input value={uri} onChange={(event) => setUri(event.target.value)} />
          </label>
          <button onClick={processCloudreveFile} disabled={busy}>处理 Cloudreve 文档</button>

          <details className="devTools">
            <summary>开发工具</summary>
            <label>
              演示文本
              <textarea value={content} onChange={(event) => setContent(event.target.value)} />
            </label>
            <button className="secondary" onClick={demoIndex} disabled={busy}>写入演示文本</button>
          </details>

          <h2 className="sectionTitle">GraphRAG</h2>
          <label>
            问题
            <textarea className="question" value={question} onChange={(event) => setQuestion(event.target.value)} />
          </label>
          <button onClick={askGraph} disabled={busy}>询问</button>
          <p className="answer">{answer?.answer || "GraphRAG 会基于当前可见图谱回答。"}</p>
        </aside>
      </section>}
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
