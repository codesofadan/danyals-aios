"use client";

import { useState } from "react";
import type { ReportViz } from "@/lib/client";

// A compact, theme-aware visualization used inside each dashboard report
// card. Chart marks ride the report's own accent colour (consistent with
// the admin bubbles); axes, grid and text come from the shared tokens so
// every theme re-skins for free. Draw-in is CSS-animated (see client.css)
// and triggers when the card is revealed after unlock.
//
// One component, five kinds: area · bars · gauge · progress · stat.
export default function MiniChart({ id, accent, viz }: { id: string; accent: string; viz: ReportViz }) {
  switch (viz.kind) {
    case "area": return <AreaChart id={id} accent={accent} viz={viz} />;
    case "bars": return <BarChart accent={accent} viz={viz} />;
    case "gauge": return <GaugeRow accent={accent} viz={viz} />;
    case "progress": return <ProgressRing accent={accent} viz={viz} />;
    default: return <StatRow accent={accent} viz={viz} />;
  }
}

const W = 320, H = 132, PADL = 8, PADR = 8, PADT = 12, PADB = 20;
const IW = W - PADL - PADR, IH = H - PADT - PADB;

function AreaChart({ id, accent, viz }: { id: string; accent: string; viz: ReportViz }) {
  const pts = viz.points ?? [];
  const labels = viz.labels ?? [];
  const [hover, setHover] = useState<number | null>(null);
  if (pts.length < 2) return null;

  const min = Math.min(...pts), max = Math.max(...pts);
  const span = max - min || 1;
  const pad = span * 0.18;
  const lo = min - pad, hi = max + pad;
  const X = (i: number) => PADL + (i / (pts.length - 1)) * IW;
  const Y = (v: number) => PADT + (1 - (v - lo) / (hi - lo)) * IH;

  const line = pts.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  const area = `M ${X(0)},${Y(pts[0])} ` + pts.map((v, i) => `L ${X(i)},${Y(v)}`).join(" ") +
    ` L ${X(pts.length - 1)},${PADT + IH} L ${X(0)},${PADT + IH} Z`;
  const li = pts.length - 1;

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    const sx = ((e.clientX - r.left) / r.width) * W;
    let i = Math.round(((sx - PADL) / IW) * (pts.length - 1));
    i = Math.max(0, Math.min(pts.length - 1, i));
    setHover(i);
  }

  const gid = `g-${id}`;
  return (
    <div className="mc-wrap" style={{ ["--accent" as string]: accent }}>
      <svg viewBox={`0 0 ${W} ${H}`} className="mc-svg" onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={accent} stopOpacity="0.30" />
            <stop offset="1" stopColor={accent} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 0.5, 1].map((t) => {
          const y = PADT + t * IH;
          return <line key={t} className="mc-grid" x1={PADL} y1={y} x2={W - PADR} y2={y} />;
        })}
        <path d={area} fill={`url(#${gid})`} className="mc-area" />
        <polyline points={line} pathLength={1} fill="none" stroke={accent} strokeWidth={2.4} strokeLinejoin="round" strokeLinecap="round" className="mc-line" />
        <circle cx={X(li)} cy={Y(pts[li])} r={4} fill="var(--card)" stroke={accent} strokeWidth={2.4} className="mc-end" />
        {hover !== null && (
          <>
            <line className="mc-cross" x1={X(hover)} y1={PADT} x2={X(hover)} y2={PADT + IH} />
            <circle cx={X(hover)} cy={Y(pts[hover])} r={4.5} fill={accent} stroke="var(--card)" strokeWidth={2} />
          </>
        )}
        {labels.length > 0 && labels.map((l, i) => {
          if (labels.length > 7 && i % 2 !== 0 && i !== labels.length - 1) return null;
          return <text key={i} className="mc-xlab" x={X(i)} y={H - 5} textAnchor="middle">{l}</text>;
        })}
      </svg>
      {hover !== null && (
        <div className="mc-tip" style={{ left: `${(X(hover) / W) * 100}%`, top: `${(Y(pts[hover]) / H) * 100}%` }}>
          <span className="mc-tip-k">{labels[hover] ?? `#${hover + 1}`}</span>
          <span className="mc-tip-v">{pts[hover].toLocaleString()}</span>
        </div>
      )}
    </div>
  );
}

function BarChart({ accent, viz }: { accent: string; viz: ReportViz }) {
  const pts = viz.points ?? [];
  const labels = viz.labels ?? [];
  const [hover, setHover] = useState<number | null>(null);
  if (pts.length === 0) return null;
  const max = Math.max(...pts) || 1;
  const gap = 6;
  const bw = (IW - gap * (pts.length - 1)) / pts.length;

  return (
    <div className="mc-wrap" style={{ ["--accent" as string]: accent }}>
      <svg viewBox={`0 0 ${W} ${H}`} className="mc-svg">
        {[0, 0.5, 1].map((t) => {
          const y = PADT + t * IH;
          return <line key={t} className="mc-grid" x1={PADL} y1={y} x2={W - PADR} y2={y} />;
        })}
        {pts.map((v, i) => {
          const h = (v / max) * IH;
          const x = PADL + i * (bw + gap);
          const y = PADT + IH - h;
          return (
            <g key={i} onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)}>
              <rect x={x} y={PADT} width={bw} height={IH} fill="transparent" />
              <rect
                x={x} y={y} width={bw} height={h} rx={Math.min(4, bw / 2)}
                fill={accent} className="mc-bar" style={{ ["--bi" as string]: i, opacity: hover === null || hover === i ? 1 : 0.5 }}
              />
              {labels[i] && <text className="mc-xlab" x={x + bw / 2} y={H - 5} textAnchor="middle">{labels[i]}</text>}
            </g>
          );
        })}
      </svg>
      {hover !== null && (
        <div className="mc-tip mc-tip-bar" style={{ left: `${((PADL + hover * (bw + gap) + bw / 2) / W) * 100}%` }}>
          <span className="mc-tip-k">{labels[hover] ?? `#${hover + 1}`}</span>
          <span className="mc-tip-v">{pts[hover].toLocaleString()}</span>
        </div>
      )}
    </div>
  );
}

function GaugeRow({ accent, viz }: { accent: string; viz: ReportViz }) {
  const gauges = viz.gauges ?? [];
  return (
    <div className="mc-gauges" style={{ ["--accent" as string]: accent }}>
      {gauges.map((g) => {
        const pct = Math.max(0, Math.min(1, 1 - g.value / g.max));
        const pass = g.value <= g.good;
        const R = 26, C = 2 * Math.PI * R;
        return (
          <div className="mc-gauge" key={g.label}>
            <svg viewBox="0 0 72 72" className="mc-gauge-svg">
              <circle cx="36" cy="36" r={R} className="mc-gauge-track" />
              <circle
                cx="36" cy="36" r={R} className="mc-gauge-arc"
                stroke={pass ? "var(--ok)" : "var(--warn)"}
                strokeDasharray={C}
                style={{ ["--circ" as string]: C, ["--to" as string]: C * (1 - pct) }}
                transform="rotate(-90 36 36)"
              />
            </svg>
            <div className="mc-gauge-c">
              <div className="mc-gauge-v">{g.value}{g.unit}</div>
              <div className="mc-gauge-l">{g.label}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ProgressRing({ accent, viz }: { accent: string; viz: ReportViz }) {
  const pct = Math.max(0, Math.min(100, viz.progress ?? 0));
  const R = 46, C = 2 * Math.PI * R;
  return (
    <div className="mc-progress" style={{ ["--accent" as string]: accent }}>
      <svg viewBox="0 0 120 120" className="mc-progress-svg">
        <circle cx="60" cy="60" r={R} className="mc-gauge-track" />
        <circle
          cx="60" cy="60" r={R} className="mc-gauge-arc" stroke={accent}
          strokeDasharray={C}
          style={{ ["--circ" as string]: C, ["--to" as string]: C * (1 - pct / 100) }}
          transform="rotate(-90 60 60)"
        />
      </svg>
      <div className="mc-progress-c">
        <div className="mc-progress-v">{pct}%</div>
        <div className="mc-progress-l">complete</div>
      </div>
    </div>
  );
}

function StatRow({ accent, viz }: { accent: string; viz: ReportViz }) {
  const stats = viz.stats ?? [];
  return (
    <div className="mc-stats" style={{ ["--accent" as string]: accent }}>
      {stats.map((s) => (
        <div className="mc-stat" key={s.label}>
          <div className={`mc-stat-v${s.up ? " up" : ""}`}>{s.value}</div>
          <div className="mc-stat-l">{s.label}</div>
        </div>
      ))}
    </div>
  );
}
