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
    running: "处理中",
    succeeded: "已完成",
    failed: "失败",
  };
  return labels[status] || status;
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
  const [documents, setDocuments] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [selectedUri, setSelectedUri] = useState("");
  const [knowledge, setKnowledge] = useState(null);
  const [uri, setUri] = useState("cloudreve://my/demo.md");
  const [content, setContent] = useState("Infrared sensor thermal calibration notes connect to project delivery risks.");
  const [question, setQuestion] = useState("有哪些已经索引的文档？");
  const [answer, setAnswer] = useState(null);
  const [authStatus, setAuthStatus] = useState({ authorized: false });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const selectedDocument = useMemo(
    () => documents.find((document) => document.uri === selectedUri),
    [documents, selectedUri],
  );
  const processedUris = useMemo(() => new Set(documents.map((document) => document.uri)), [documents]);

  async function refresh() {
    const [nextDocuments, nextJobs, nextAuthStatus] = await Promise.all([
      requestJson("/api/documents"),
      requestJson("/api/ingestion/jobs"),
      requestJson("/api/auth/cloudreve/status"),
    ]);
    setDocuments(nextDocuments);
    setJobs(nextJobs);
    setAuthStatus(nextAuthStatus);
    if (!selectedUri && nextDocuments.length) {
      setSelectedUri(nextDocuments[0].uri);
    }
  }

  function authorizeCloudreve() {
    window.location.assign(`${API_BASE}/api/auth/cloudreve/start`);
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

  async function retryJob(job) {
    setBusy(true);
    setMessage("");
    try {
      const result = await requestJson(`/api/ingestion/jobs/${job.id}/retry`, { method: "POST" });
      await refresh();
      setSelectedUri(job.uri);
      setUri(job.uri);
      setMessage(result.processing?.success ? "已重新处理该文件。" : `重新处理失败：${result.processing?.error || "未知错误"}`);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  function selectJobFile(job) {
    setSelectedUri(job.uri);
    setUri(job.uri);
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
          <span>{documents.length}</span>
          <small>已索引文档</small>
        </article>
        <article>
          <span>{jobs.filter((job) => job.status === "running").length}</span>
          <small>处理中任务</small>
        </article>
        <article>
          <span>{jobs.filter((job) => job.status === "failed").length}</span>
          <small>失败任务</small>
        </article>
        <article>
          <span>{authStatus.authorized ? "已授权" : "未授权"}</span>
          <small>Cloudreve OAuth</small>
        </article>
      </section>

      <section className="workspace">
        <aside className="panel sidebar">
          <div className="panelHeader">
            <h2>文档</h2>
          </div>
          <div className="list">
            {documents.length ? documents.map((document) => (
              <button
                className={`listItem ${selectedUri === document.uri ? "active" : ""}`}
                key={document.uri}
                onClick={() => setSelectedUri(document.uri)}
              >
                <strong>{document.uri.split("/").pop()}</strong>
                <small>{document.uri}</small>
              </button>
            )) : <p className="muted">还没有可查看的语义文档。</p>}
          </div>

          <h2 className="sectionTitle">任务</h2>
          <div className="jobs">
            {jobs.length ? jobs.slice(0, 8).map((job) => (
              <article className="job" key={job.id}>
                <div className="jobMeta">
                  <span className={`status ${job.status}`}>{statusLabel(job.status)}</span>
                  <span className={`semanticBadge ${processedUris.has(job.uri) ? "ready" : ""}`}>
                    {processedUris.has(job.uri) ? "已语义处理" : "未见语义结果"}
                  </span>
                </div>
                <strong>{job.uri.split("/").pop()}</strong>
                <small>{job.uri}</small>
                <small>尝试 {job.attempts} 次 · {new Date(job.created_at).toLocaleString()}</small>
                {job.error ? <p className="jobError">{job.error}</p> : null}
                <div className="jobActions">
                  <button className="miniButton" onClick={() => selectJobFile(job)} disabled={busy}>选中文件</button>
                  <button className="miniButton primary" onClick={() => retryJob(job)} disabled={busy}>重新处理</button>
                </div>
              </article>
            )) : <p className="muted">暂无 ingestion job。</p>}
          </div>
        </aside>

        <section className="panel inspector">
          <div className="panelHeader">
            <h2>知识检查器</h2>
            {selectedDocument ? <span className="pill">{selectedDocument.chunk_count} chunks</span> : null}
          </div>

          {knowledge ? (
            <>
              <p className="uri">{knowledge.uri}</p>
              <p className="summary">{knowledge.summary || "暂无摘要"}</p>

              <h3>标签</h3>
              <div className="chips">
                {knowledge.tags.length ? knowledge.tags.map((tag) => <span key={tag}>{tag}</span>) : <small className="muted">暂无标签</small>}
              </div>

              <h3>实体</h3>
              <div className="chips entity">
                {knowledge.entities.length ? knowledge.entities.map((entity) => <span key={entity}>{entity}</span>) : <small className="muted">暂无实体</small>}
              </div>

              <h3>自动链接建议</h3>
              {knowledge.suggestions.length ? (
                knowledge.suggestions.map((suggestion) => (
                  <article className="suggestion" key={`${suggestion.source_uri}-${suggestion.target_uri}`}>
                    <strong>{suggestion.target_uri}</strong>
                    <small>{suggestion.reason}</small>
                  </article>
                ))
              ) : (
                <p className="muted">没有候选链接。索引更多相似文档后会出现建议。</p>
              )}
            </>
          ) : (
            <p className="muted">选择一个文档查看语义分析结果。</p>
          )}
        </section>

        <aside className="panel actions">
          <h2>Cloudreve 授权</h2>
          <div className={`authState ${authStatus.authorized ? "ready" : ""}`}>
            <strong>{authStatus.authorized ? "授权可用" : "需要授权"}</strong>
            <small>{cloudreveAuthHint(authStatus)}</small>
          </div>
          <button className="secondary" onClick={authorizeCloudreve} disabled={busy}>打开 Cloudreve 授权</button>

          <h2>手动处理</h2>
          <label>
            Cloudreve URI
            <input value={uri} onChange={(event) => setUri(event.target.value)} />
          </label>
          <button onClick={processCloudreveFile} disabled={busy}>处理 Cloudreve 文档</button>

          <label>
            演示文本
            <textarea value={content} onChange={(event) => setContent(event.target.value)} />
          </label>
          <button className="secondary" onClick={demoIndex} disabled={busy}>写入演示文本</button>

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
