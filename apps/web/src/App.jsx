import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API_BASE = import.meta.env.VITE_NEXUS_API_BASE || "http://localhost:8000";

async function requestJson(path, options) {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json();
}

function statusLabel(status) {
  const labels = {
    pending: "等待中",
    processing: "处理中",
    processed: "已处理",
    running: "处理中",
    succeeded: "已完成",
    failed: "失败",
  };
  return labels[status] || status;
}

function stageLabel(stage) {
  const labels = {
    queued: "排队",
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
  const [oauthClientId, setOauthClientId] = useState("");
  const [oauthClientSecret, setOauthClientSecret] = useState("");
  const [editingOAuthConfig, setEditingOAuthConfig] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

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
  const selectedAttempts = useMemo(
    () => jobs.filter((job) => job.uri === selectedUri),
    [jobs, selectedUri],
  );

  async function refresh() {
    const [nextFiles, nextDocuments, nextJobs, nextAuthStatus, nextAuthConfig] = await Promise.all([
      requestJson("/api/ingestion/files"),
      requestJson("/api/documents"),
      requestJson("/api/ingestion/jobs"),
      requestJson("/api/auth/cloudreve/status"),
      requestJson("/api/auth/cloudreve/config"),
    ]);
    setFiles(nextFiles);
    setDocuments(nextDocuments);
    setJobs(nextJobs);
    setAuthStatus(nextAuthStatus);
    setAuthConfig(nextAuthConfig);
    if (!selectedUri && nextFiles.length) {
      setSelectedUri(nextFiles[0].uri);
    }
  }

  function authorizeCloudreve() {
    if (!authConfig.configured) {
      setMessage("请先在 Cloudreve 管理面板创建 OAuth App，并在这里保存 Client ID / Secret。");
      return;
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
          redirect_uri: authConfig.redirect_uri || "http://localhost:8000/api/auth/cloudreve/callback",
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

  useEffect(() => {
    refresh().catch((error) => setMessage(error.message));
  }, []);

  useEffect(() => {
    loadKnowledge(selectedUri).catch((error) => setMessage(error.message));
  }, [selectedUri]);

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
        <button className="compact" onClick={refresh} disabled={busy}>刷新</button>
      </header>

      {message ? <div className="notice">{message}</div> : null}

      <section className="metrics">
        <article>
          <span>{files.filter((file) => file.status === "processed").length}</span>
          <small>已处理文件</small>
        </article>
        <article>
          <span>{files.filter((file) => file.status === "processing").length}</span>
          <small>处理中任务</small>
        </article>
        <article>
          <span>{files.filter((file) => file.status === "failed").length}</span>
          <small>失败文件</small>
        </article>
        <article>
          <span>{authStatus.authorized ? "已授权" : "未授权"}</span>
          <small>Cloudreve OAuth</small>
        </article>
      </section>

      <section className="workspace">
        <section className="panel fileCenter">
          <div className="panelHeader">
            <h2>文件处理中心</h2>
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="all">全部</option>
              <option value="processed">已处理</option>
              <option value="processing">处理中</option>
              <option value="pending">等待中</option>
              <option value="failed">失败</option>
            </select>
          </div>
          <div className="fileList">
            {filteredFiles.length ? filteredFiles.map((file) => (
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
            )) : <p className="muted">还没有监听或处理过的文件。</p>}
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
            <small>Redirect URI: {authConfig.redirect_uri || "http://localhost:8000/api/auth/cloudreve/callback"}</small>
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
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
