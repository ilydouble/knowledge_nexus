import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { formatNodeType, getNodeType, isDocumentNode } from "./graphData.js";

const NODE_R = 16;          // document-node radius
const ENTITY_R = 10;        // entity-node radius
const CLUSTER_R = 28;
// Repulsion and center-pull are computed per-frame from canvas size (see useSim).
const ATTRACTION = 0.018;
const DAMPING = 0.78;
const CENTER_PULL = 0.006;

function nodeRadius(node) {
  if (node.isCluster) return Math.max(CLUSTER_R, 16 + Math.min(node.count || 1, 50) * 0.6);
  return isDocumentNode(node) ? NODE_R : ENTITY_R;
}

function nodeColor(node) {
  if (node.isCluster) return clusterColor(node.clusterType);
  if (isDocumentNode(node)) return "#2563eb";
  const type = getNodeType(node);
  return paletteColor(type) || "#94a3b8";
}

function paletteColor(type) {
  const palette = {
    researcher: "#f59e0b", person: "#f59e0b",
    institution: "#10b981", organization: "#10b981",
    method: "#3b82f6", concept: "#8b5cf6",
    database: "#0f766e",
    dataset: "#ec4899", metric: "#14b8a6",
    component: "#f97316", api: "#06b6d4",
    technology: "#6366f1", tool: "#f59e0b", framework: "#8b5cf6",
  };
  return palette[(type || "").toLowerCase()];
}

function clusterColor(type) {
  if (type === "document") return "#2563eb";
  return paletteColor(type) || "#94a3b8";
}

function clusterTypeLabel(node) {
  return getNodeType(node);
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
    const repulsion = width * height * 0.018;
    const idealEdgeLength = Math.max(96, Math.min(220, Math.sqrt(width * height) / 4));

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

      // Attraction along edges, with an ideal distance so connected clusters do
      // not collapse into a single hairball.
      rawEdges.forEach(({ source, target }) => {
        if (!p[source] || !p[target]) return;
        const dx = p[target].x - p[source].x, dy = p[target].y - p[source].y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = (dist - idealEdgeLength) * ATTRACTION * alpha;
        v[source].x += (dx / dist) * force;
        v[source].y += (dy / dist) * force;
        v[target].x -= (dx / dist) * force;
        v[target].y -= (dy / dist) * force;
      });

      // Collision spacing keeps labels and nodes legible after the force cools.
      for (let i = 0; i < nodeList.length; i++) {
        for (let j = i + 1; j < nodeList.length; j++) {
          const aNode = nodeList[i], bNode = nodeList[j];
          const a = aNode.id, b = bNode.id;
          const dx = p[b].x - p[a].x, dy = p[b].y - p[a].y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const minDist = nodeRadius(aNode) + nodeRadius(bNode) + 38;
          if (dist >= minDist) continue;
          const push = ((minDist - dist) / dist) * 0.18 * alpha;
          v[a].x -= dx * push;
          v[a].y -= dy * push;
          v[b].x += dx * push;
          v[b].y += dy * push;
        }
      }

      // Center gravity — must also scale by alpha so it decays together with
      // repulsion/attraction; otherwise it dominates as alpha→0 and collapses
      // all nodes toward the center.
      nodeList.forEach(({ id }) => {
        v[id].x += (width / 2 - p[id].x) * CENTER_PULL * alpha;
        v[id].y += (height / 2 - p[id].y) * CENTER_PULL * alpha;
      });

      // Integrate
      nodeList.forEach((node) => {
        const id = node.id;
        v[id].x *= DAMPING;
        v[id].y *= DAMPING;
        const margin = nodeRadius(node) + 28;
        p[id] = {
          x: Math.max(margin, Math.min(width - margin, p[id].x + v[id].x)),
          y: Math.max(margin, Math.min(height - margin, p[id].y + v[id].y)),
        };
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


export default function GraphView({
  nodes: rawNodes = [],
  edges: rawEdges = [],
  onNodeClick,
  clusterMode = false,
  selectedNodeId = "",
  focusNodeId = "",
}) {
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
  const activeSelected = selectedNodeId || selected;

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
  const connectedToFocus = new Set();
  if (focusNodeId) {
    connectedToFocus.add(focusNodeId);
    for (const edge of activeEdges) {
      if (edge.source === focusNodeId) connectedToFocus.add(edge.target);
      if (edge.target === focusNodeId) connectedToFocus.add(edge.source);
    }
  }
  const showAllLabels = activeNodes.length <= 36 || clusterMode;

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
          const isSelected = activeSelected === node.id;
          const isHov = hovered === node.id;
          const isDimmed = focusNodeId && !connectedToFocus.has(node.id);
          const showLabel = showAllLabels || isSelected || isHov || focusNodeId === node.id;
          const label = node.isCluster
            ? `${node.count} 个${formatNodeType(node.label)}`
            : (node.label || node.id).slice(0, 22);
          return (
            <g key={node.id} transform={`translate(${p.x},${p.y})`} style={{ cursor: "pointer", opacity: isDimmed ? 0.28 : 1 }}
              onMouseEnter={() => setHovered(node.id)} onMouseLeave={() => setHovered(null)}
              onMouseDown={(e) => handleMouseDown(e, node.id)}
              onClick={() => { setSelected(node.id); onNodeClick?.(node); }}>
              {node.isCluster ? (
                <>
                  <circle r={r} fill={nodeColor(node)} fillOpacity={0.15}
                    stroke={isSelected ? "#fff" : isHov ? "#e2e8f0" : nodeColor(node)}
                    strokeWidth={isSelected ? 3 : 2} strokeOpacity={0.7} />
                  <circle r={6} fill={nodeColor(node)} fillOpacity={0.85} />
                  {showLabel && (
                    <text textAnchor="middle" dy={r + 14} fontSize={11} fill="#e2e8f0" fontWeight={700}
                      style={{ pointerEvents: "none", userSelect: "none" }}>
                      {label}
                    </text>
                  )}
                </>
              ) : (
                <>
                  <circle r={r} fill={nodeColor(node)}
                    stroke={isSelected ? "#fff" : isHov ? "#e2e8f0" : "none"}
                    strokeWidth={isSelected ? 2.5 : 1.5} fillOpacity={0.9} />
                  {showLabel && (
                    <text textAnchor="middle" dy={r + 11} fontSize={10} fill="#e2e8f0"
                      style={{ pointerEvents: "none", userSelect: "none" }}>
                      {label}
                    </text>
                  )}
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
