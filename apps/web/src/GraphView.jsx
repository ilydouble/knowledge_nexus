import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

const NODE_R = 18;          // file-node radius
const ENTITY_R = 12;        // entity-node radius
const CLUSTER_R = 28;
// Repulsion and center-pull are computed per-frame from canvas size (see useSim).
const ATTRACTION = 0.04;
const DAMPING = 0.78;
const CENTER_PULL = 0.012;

function isFileNode(node) {
  return node.uri && (
    node.uri.startsWith("cloudreve://") ||
    node.uri.startsWith("file:") ||
    node.uri.startsWith("newdrive://")
  );
}

function nodeRadius(node) {
  if (node.isCluster) return Math.max(CLUSTER_R, 16 + Math.min(node.count || 1, 50) * 0.6);
  return isFileNode(node) ? NODE_R : ENTITY_R;
}

function nodeColor(node) {
  if (node.isCluster) return clusterColor(node.clusterType);
  if (isFileNode(node)) return "#6366f1";
  const type = (node.properties?.type || "").toLowerCase();
  return paletteColor(type) || "#94a3b8";
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
  return palette[(type || "").toLowerCase()];
}

function clusterColor(type) {
  if (type === "文档") return "#6366f1";
  return paletteColor(type) || "#94a3b8";
}

function clusterTypeLabel(node) {
  if (isFileNode(node)) return "文档";
  const type = node.properties?.type || "其他";
  const known = [
    "person", "researcher", "institution", "organization", "method", "concept",
    "dataset", "metric", "component", "api", "technology", "tool", "framework",
  ];
  return known.includes(type.toLowerCase()) ? type : "其他";
}

function buildClusters(nodes, edges) {
  const groups = {};
  for (const node of nodes) {
    const type = clusterTypeLabel(node);
    if (!groups[type]) groups[type] = [];
    groups[type].push(node);
  }

  const entries = Object.entries(groups);
  if (entries.length <= 1) return null;

  const clusterNodes = entries.map(([type, members]) => ({
    id: `cluster:${type}`,
    label: type,
    count: members.length,
    members,
    clusterType: type,
    isCluster: true,
    summary: `${members.length} 个节点`,
  }));

  const nodeCluster = {};
  for (const cluster of clusterNodes) {
    for (const member of cluster.members) {
      nodeCluster[member.id] = cluster.id;
    }
  }

  const edgeMap = {};
  for (const edge of edges) {
    const source = nodeCluster[edge.source];
    const target = nodeCluster[edge.target];
    if (!source || !target || source === target) continue;
    const key = source < target ? `${source}|${target}` : `${target}|${source}`;
    if (!edgeMap[key]) {
      edgeMap[key] = { id: key, source, target, relation: edge.relation, count: 0 };
    }
    edgeMap[key].count += 1;
  }

  return {
    nodes: clusterNodes,
    edges: Object.values(edgeMap).map((edge) => ({
      ...edge,
      relation: edge.count > 1 ? `${edge.count} 条关系` : edge.relation,
    })),
  };
}

function useSim(rawNodes, rawEdges, width, height) {
  const [positions, setPositions] = useState({});
  const velRef = useRef({});
  const posRef = useRef({});
  const rafRef = useRef(null);

  useEffect(() => {
    if (!rawNodes.length) { setPositions({}); return; }

    const ids = rawNodes.map((n) => n.id);
    const pos = {};
    const vel = {};
    // Seed a simple deterministic PRNG so positions are stable across re-renders
    // but still spread across the full canvas from the start.
    let seed = 42;
    const rand = () => { seed = (seed * 16807 + 0) % 2147483647; return (seed - 1) / 2147483646; };
    ids.forEach((id) => {
      pos[id] = posRef.current[id] || {
        x: width  * (0.1 + 0.8 * rand()),
        y: height * (0.1 + 0.8 * rand()),
      };
      vel[id] = { x: 0, y: 0 };
    });
    posRef.current = pos;
    velRef.current = vel;

    let alpha = 1.0;
    // Scale repulsion with canvas area so the graph fills the space regardless
    // of window size.  At 800×520 this ≈ 4160 (same ballpark as before);
    // at 1400×700 it grows to ~9800 — nodes spread proportionally further.
    const repulsion = width * height * 0.01;

    function tick() {
      const p = posRef.current;
      const v = velRef.current;
      const nodeList = rawNodes;

      // Repulsion
      for (let i = 0; i < nodeList.length; i++) {
        for (let j = i + 1; j < nodeList.length; j++) {
          const a = nodeList[i].id, b = nodeList[j].id;
          const dx = p[b].x - p[a].x, dy = p[b].y - p[a].y;
          const dist2 = dx * dx + dy * dy + 1;
          const force = (repulsion * alpha) / dist2;
          const dist = Math.sqrt(dist2);
          v[a].x -= (force * dx) / dist;
          v[a].y -= (force * dy) / dist;
          v[b].x += (force * dx) / dist;
          v[b].y += (force * dy) / dist;
        }
      }

      // Attraction along edges
      rawEdges.forEach(({ source, target }) => {
        if (!p[source] || !p[target]) return;
        const dx = p[target].x - p[source].x, dy = p[target].y - p[source].y;
        v[source].x += dx * ATTRACTION * alpha;
        v[source].y += dy * ATTRACTION * alpha;
        v[target].x -= dx * ATTRACTION * alpha;
        v[target].y -= dy * ATTRACTION * alpha;
      });

      // Center gravity — must also scale by alpha so it decays together with
      // repulsion/attraction; otherwise it dominates as alpha→0 and collapses
      // all nodes toward the center.
      nodeList.forEach(({ id }) => {
        v[id].x += (width / 2 - p[id].x) * CENTER_PULL * alpha;
        v[id].y += (height / 2 - p[id].y) * CENTER_PULL * alpha;
      });

      // Integrate
      nodeList.forEach(({ id }) => {
        v[id].x *= DAMPING;
        v[id].y *= DAMPING;
        p[id] = { x: p[id].x + v[id].x, y: p[id].y + v[id].y };
      });

      alpha *= 0.99;
      setPositions({ ...p });
      if (alpha > 0.005) {
        rafRef.current = requestAnimationFrame(tick);
      }
    }

    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [rawNodes, rawEdges, width, height]);

  return positions;
}


export default function GraphView({ nodes: rawNodes = [], edges: rawEdges = [], onNodeClick, clusterMode = false }) {
  const containerRef = useRef(null);
  const [dims, setDims] = useState({ width: 800, height: 520 });
  const [hovered, setHovered] = useState(null);
  const [selected, setSelected] = useState(null);
  const dragRef = useRef(null);
  const posOverrideRef = useRef({});

  useEffect(() => {
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setDims({ width, height });
    });
    if (containerRef.current) ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  const clusterInfo = useMemo(() => {
    if (!clusterMode || !rawNodes.length) return null;
    return buildClusters(rawNodes, rawEdges);
  }, [clusterMode, rawEdges, rawNodes]);
  const activeNodes = clusterInfo ? clusterInfo.nodes : rawNodes;
  const activeEdges = clusterInfo ? clusterInfo.edges : rawEdges;

  const positions = useSim(activeNodes, activeEdges, dims.width, dims.height);
  // Merge sim positions with drag overrides
  const mergedPos = { ...positions, ...posOverrideRef.current };

  const handleMouseDown = useCallback((e, id) => {
    e.preventDefault();
    dragRef.current = id;
  }, []);

  useEffect(() => {
    function onMove(e) {
      const id = dragRef.current;
      if (!id) return;
      const svg = containerRef.current?.querySelector("svg");
      if (!svg) return;
      const rect = svg.getBoundingClientRect();
      posOverrideRef.current[id] = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      setDims((d) => ({ ...d }));
    }
    function onUp() {
      if (dragRef.current) {
        // absorb override back so sim doesn't jump
        dragRef.current = null;
      }
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, []);

  if (!rawNodes.length) {
    return <div className="graphEmpty">暂无图谱数据</div>;
  }

  const nodeMap = Object.fromEntries(activeNodes.map((n) => [n.id, n]));

  return (
    <div className="graphCanvas" ref={containerRef}>
      <svg width={dims.width} height={dims.height} onMouseLeave={() => setHovered(null)}>
        <defs>
          <marker id="arrow" markerWidth="8" markerHeight="8" refX="8" refY="3" orient="auto">
            <path d="M0,0 L0,6 L8,3 z" fill="#94a3b8" />
          </marker>
        </defs>

        {activeEdges.map((edge) => {
          const sp = mergedPos[edge.source], tp = mergedPos[edge.target];
          if (!sp || !tp) return null;
          const mx = (sp.x + tp.x) / 2, my = (sp.y + tp.y) / 2;
          const strokeWidth = edge.count ? Math.min(2 + edge.count, 6) : 1.5;
          return (
            <g key={edge.id}>
              <line x1={sp.x} y1={sp.y} x2={tp.x} y2={tp.y}
                stroke="#94a3b8" strokeWidth={strokeWidth} strokeOpacity={0.6} markerEnd="url(#arrow)" />
              <text x={mx} y={my - 4} textAnchor="middle" fontSize={9} fill="#94a3b8">{edge.relation}</text>
            </g>
          );
        })}

        {activeNodes.map((node) => {
          const p = mergedPos[node.id];
          if (!p) return null;
          const r = nodeRadius(node);
          const isSelected = selected === node.id;
          const isHov = hovered === node.id;
          return (
            <g key={node.id} transform={`translate(${p.x},${p.y})`} style={{ cursor: "pointer" }}
              onMouseEnter={() => setHovered(node.id)} onMouseLeave={() => setHovered(null)}
              onMouseDown={(e) => handleMouseDown(e, node.id)}
              onClick={() => { setSelected(node.id); onNodeClick?.(node); }}>
              {node.isCluster ? (
                <>
                  <circle r={r} fill={nodeColor(node)} fillOpacity={0.15}
                    stroke={isSelected ? "#fff" : isHov ? "#e2e8f0" : nodeColor(node)}
                    strokeWidth={isSelected ? 3 : 2} strokeOpacity={0.7} />
                  <circle r={6} fill={nodeColor(node)} fillOpacity={0.85} />
                  <text textAnchor="middle" dy={r + 14} fontSize={11} fill="#e2e8f0" fontWeight={700}
                    style={{ pointerEvents: "none", userSelect: "none" }}>
                    {node.count} 个{node.label}
                  </text>
                </>
              ) : (
                <>
                  <circle r={r} fill={nodeColor(node)}
                    stroke={isSelected ? "#fff" : isHov ? "#e2e8f0" : "none"}
                    strokeWidth={isSelected ? 2.5 : 1.5} fillOpacity={0.9} />
                  <text textAnchor="middle" dy={r + 11} fontSize={10} fill="#e2e8f0"
                    style={{ pointerEvents: "none", userSelect: "none" }}>
                    {(node.label || node.id).slice(0, 20)}
                  </text>
                </>
              )}
            </g>
          );
        })}
      </svg>

      {hovered && nodeMap[hovered] && (() => {
        const n = nodeMap[hovered];
        const p = mergedPos[hovered];
        if (!p) return null;
        if (n.isCluster) {
          return (
            <div className="graphTooltip" style={{ left: p.x + 24, top: p.y - 8 }}>
              <strong>{n.label}</strong>
              <p>{n.count} 个节点</p>
              {n.members?.length > 10 ? <p>点击查看成员列表</p> : null}
            </div>
          );
        }
        return (
          <div className="graphTooltip" style={{ left: p.x + 24, top: p.y - 8 }}>
            <strong>{n.label || n.id}</strong>
            {n.properties?.type && <span> · {n.properties.type}</span>}
            {n.summary && <p>{n.summary.slice(0, 120)}{n.summary.length > 120 ? "…" : ""}</p>}
          </div>
        );
      })()}
    </div>
  );
}
