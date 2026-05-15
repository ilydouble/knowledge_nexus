import React, { useCallback, useEffect, useRef, useState } from "react";

const NODE_R = 18;          // file-node radius
const ENTITY_R = 12;        // entity-node radius
const REPULSION = 4000;
const ATTRACTION = 0.06;
const DAMPING = 0.82;
const CENTER_PULL = 0.015;

function isFileNode(node) {
  return node.uri && (node.uri.startsWith("cloudreve://") || node.uri.startsWith("file:"));
}

function nodeRadius(node) {
  return isFileNode(node) ? NODE_R : ENTITY_R;
}

function nodeColor(node) {
  if (isFileNode(node)) return "#6366f1";
  const type = (node.properties?.type || "").toLowerCase();
  const palette = {
    researcher: "#f59e0b", person: "#f59e0b",
    institution: "#10b981", organization: "#10b981",
    method: "#3b82f6", concept: "#8b5cf6",
    dataset: "#ec4899", metric: "#14b8a6",
    component: "#f97316", api: "#06b6d4",
  };
  return palette[type] || "#94a3b8";
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
    ids.forEach((id, i) => {
      const angle = (2 * Math.PI * i) / ids.length;
      const r = Math.min(width, height) * 0.3;
      pos[id] = posRef.current[id] || {
        x: width / 2 + r * Math.cos(angle),
        y: height / 2 + r * Math.sin(angle),
      };
      vel[id] = { x: 0, y: 0 };
    });
    posRef.current = pos;
    velRef.current = vel;

    let alpha = 1.0;

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
          const force = (REPULSION * alpha) / dist2;
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


export default function GraphView({ nodes: rawNodes = [], edges: rawEdges = [], onNodeClick }) {
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

  const positions = useSim(rawNodes, rawEdges, dims.width, dims.height);
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

  const nodeMap = Object.fromEntries(rawNodes.map((n) => [n.id, n]));

  return (
    <div className="graphCanvas" ref={containerRef}>
      <svg width={dims.width} height={dims.height} onMouseLeave={() => setHovered(null)}>
        <defs>
          <marker id="arrow" markerWidth="8" markerHeight="8" refX="8" refY="3" orient="auto">
            <path d="M0,0 L0,6 L8,3 z" fill="#94a3b8" />
          </marker>
        </defs>

        {rawEdges.map((edge) => {
          const sp = mergedPos[edge.source], tp = mergedPos[edge.target];
          if (!sp || !tp) return null;
          const mx = (sp.x + tp.x) / 2, my = (sp.y + tp.y) / 2;
          return (
            <g key={edge.id}>
              <line x1={sp.x} y1={sp.y} x2={tp.x} y2={tp.y}
                stroke="#94a3b8" strokeWidth={1.5} strokeOpacity={0.6} markerEnd="url(#arrow)" />
              <text x={mx} y={my - 4} textAnchor="middle" fontSize={9} fill="#94a3b8">{edge.relation}</text>
            </g>
          );
        })}

        {rawNodes.map((node) => {
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
              <circle r={r} fill={nodeColor(node)}
                stroke={isSelected ? "#fff" : isHov ? "#e2e8f0" : "none"}
                strokeWidth={isSelected ? 2.5 : 1.5} fillOpacity={0.9} />
              <text textAnchor="middle" dy={r + 11} fontSize={10} fill="#e2e8f0"
                style={{ pointerEvents: "none", userSelect: "none" }}>
                {(node.label || node.id).slice(0, 20)}
              </text>
            </g>
          );
        })}
      </svg>

      {hovered && nodeMap[hovered] && (() => {
        const n = nodeMap[hovered];
        const p = mergedPos[hovered];
        if (!p) return null;
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
