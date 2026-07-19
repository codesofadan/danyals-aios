"use client";

import { useEffect, useRef, useState } from "react";
import anime from "animejs";
import type { CCTrafficPoint } from "@/lib/hooks/commandCenter";

// Monthly organic sessions — animated SVG area line (anime.js) with hover crosshair.
export default function TrafficChart({ traffic }: { traffic: CCTrafficPoint[] }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const [showTable, setShowTable] = useState(false);
  const [range, setRange] = useState<"12M" | "6M" | "30D">("12M");

  useEffect(() => {
    const svg = svgRef.current;
    const tip = tipRef.current;
    if (!svg || !tip) return;
    const NS = "http://www.w3.org/2000/svg";
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

    const W = 760, H = 300, padL = 44, padR = 16, padT = 18, padB = 34;
    const innerW = W - padL - padR, innerH = H - padT - padB;
    const vals = traffic.map((d) => d.v);
    const min = Math.floor(Math.min(...vals) / 20) * 20 - 10;
    const max = Math.ceil(Math.max(...vals) / 20) * 20 + 10;
    const X = (i: number) => padL + (i / (traffic.length - 1)) * innerW;
    const Y = (v: number) => padT + (1 - (v - min) / (max - min)) * innerH;
    const mk = (t: string, a: Record<string, string | number>) => {
      const e = document.createElementNS(NS, t);
      for (const k in a) e.setAttribute(k, String(a[k]));
      return e;
    };

    svg.innerHTML = "";

    const defs = mk("defs", {});
    defs.innerHTML =
      `<linearGradient id="tgrad" x1="0" y1="0" x2="0" y2="1">
         <stop offset="0" stop-color="#432B52" stop-opacity="0.34"/>
         <stop offset="1" stop-color="#432B52" stop-opacity="0"/>
       </linearGradient>
       <linearGradient id="tline" x1="0" y1="0" x2="1" y2="0">
         <stop offset="0" stop-color="#5B3A6E"/><stop offset="1" stop-color="#211B29"/>
       </linearGradient>`;
    svg.appendChild(defs);

    const gaxis = mk("g", { class: "tx-axis" });
    const steps = 4;
    for (let i = 0; i <= steps; i++) {
      const v = min + (max - min) * i / steps, y = Y(v);
      gaxis.appendChild(mk("line", { class: "tx-grid", x1: padL, y1: y, x2: W - padR, y2: y }));
      const t = mk("text", { x: padL - 10, y: y + 3.5, "text-anchor": "end" });
      t.textContent = `${Math.round(v)}K`;
      gaxis.appendChild(t);
    }
    traffic.forEach((d, i) => {
      const t = mk("text", { x: X(i), y: H - 12, "text-anchor": "middle" });
      t.textContent = d.m;
      gaxis.appendChild(t);
    });
    svg.appendChild(gaxis);

    const linePts = traffic.map((d, i) => `${X(i)},${Y(d.v)}`).join(" ");
    const areaD = `M ${X(0)},${Y(traffic[0].v)} ` +
      traffic.map((d, i) => `L ${X(i)},${Y(d.v)}`).join(" ") +
      ` L ${X(traffic.length - 1)},${padT + innerH} L ${X(0)},${padT + innerH} Z`;
    const area = mk("path", { d: areaD, fill: "url(#tgrad)", opacity: 0 });
    const line = mk("polyline", {
      points: linePts, fill: "none", stroke: "url(#tline)",
      "stroke-width": 2.6, "stroke-linejoin": "round", "stroke-linecap": "round",
    }) as unknown as SVGPolylineElement;
    svg.appendChild(area);
    svg.appendChild(line);

    const len = line.getTotalLength();
    line.style.strokeDasharray = String(len);
    line.style.strokeDashoffset = reduce ? "0" : String(len);
    if (!reduce) {
      anime({ targets: line, strokeDashoffset: [len, 0], duration: 1600, easing: "easeInOutSine" });
      anime({ targets: area, opacity: [0, 1], duration: 900, delay: 700, easing: "easeOutQuad" });
    } else {
      area.setAttribute("opacity", "1");
    }

    const li = traffic.length - 1;
    svg.appendChild(mk("circle", { cx: X(li), cy: Y(traffic[li].v), r: 6.5, fill: "#FAF6EE", stroke: "#432B52", "stroke-width": 2.4 }));

    const cross = mk("line", { x1: 0, y1: padT, x2: 0, y2: padT + innerH, stroke: "rgba(67,43,82,.26)", "stroke-width": 1, opacity: 0 });
    const dot = mk("circle", { r: 5.5, fill: "#5B3A6E", stroke: "#FAF6EE", "stroke-width": 2, opacity: 0 });
    svg.appendChild(cross);
    svg.appendChild(dot);

    const onMove = (e: PointerEvent) => {
      const r = svg.getBoundingClientRect();
      const sx = (e.clientX - r.left) / r.width * W;
      let i = Math.round((sx - padL) / innerW * (traffic.length - 1));
      i = Math.max(0, Math.min(traffic.length - 1, i));
      const d = traffic[i], px = X(i), py = Y(d.v);
      cross.setAttribute("x1", String(px)); cross.setAttribute("x2", String(px)); cross.setAttribute("opacity", "1");
      dot.setAttribute("cx", String(px)); dot.setAttribute("cy", String(py)); dot.setAttribute("opacity", "1");
      tip.innerHTML = `<span class="k">${d.m}</span><br><span class="v">${d.v}K</span> <span class="k">sessions</span>`;
      tip.style.left = `${px / W * r.width}px`;
      tip.style.top = `${py / H * r.height}px`;
      tip.classList.add("show");
    };
    const onLeave = () => {
      cross.setAttribute("opacity", "0");
      dot.setAttribute("opacity", "0");
      tip.classList.remove("show");
    };
    svg.addEventListener("pointermove", onMove);
    svg.addEventListener("pointerleave", onLeave);

    return () => {
      svg.removeEventListener("pointermove", onMove);
      svg.removeEventListener("pointerleave", onLeave);
    };
  }, [traffic]);

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Monthly Traffic Overview</div>
          <div className="cs">Aggregate organic sessions across all client sites</div>
        </div>
        <div className="tools">
          <div className="seg">
            {(["12M", "6M", "30D"] as const).map((r) => (
              <button key={r} className={range === r ? "on" : undefined} onClick={() => setRange(r)}>{r}</button>
            ))}
          </div>
          <button className="ghostbtn" onClick={() => setShowTable((s) => !s)}>
            <span className="material-symbols-rounded">table_rows</span>Data
          </button>
        </div>
      </div>

      <div className="svg-wrap">
        <svg ref={svgRef} viewBox="0 0 760 300" preserveAspectRatio="none" aria-label="Monthly organic sessions" />
        <div className="chart-tip" ref={tipRef} />
      </div>

      <div className={showTable ? "dtable show" : "dtable"}>
        <table>
          <thead><tr><th>Month</th><th>Sessions (K)</th></tr></thead>
          <tbody>
            {traffic.map((d) => (
              <tr key={d.m}><td>{d.m}</td><td>{d.v}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
