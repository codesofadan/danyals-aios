"use client";

import { useEffect, useRef } from "react";
import anime from "animejs";
import { clientGrowth } from "@/lib/data";

// Total client count + a growth-trend area chart (animated SVG · anime.js).
// The big number counts up; the line draws itself in and supports a hover readout.
export default function ClientGrowth() {
  const svgRef = useRef<SVGSVGElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const totalRef = useRef<HTMLSpanElement>(null);

  const total = clientGrowth[clientGrowth.length - 1].v;
  const start = clientGrowth[0].v;
  const gain = total - start;
  const growthPct = Math.round((gain / start) * 100);

  useEffect(() => {
    const svg = svgRef.current;
    const tip = tipRef.current;
    if (!svg || !tip) return;
    const NS = "http://www.w3.org/2000/svg";
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

    // count-up on the headline total
    const node = totalRef.current;
    if (node) {
      if (reduce) {
        node.textContent = String(total);
      } else {
        const o = { n: 0 };
        anime({ targets: o, n: total, duration: 1400, easing: "easeOutExpo", round: 1, update: () => { node.textContent = String(o.n); } });
      }
    }

    const W = 520, H = 220, padL = 30, padR = 14, padT = 16, padB = 26;
    const innerW = W - padL - padR, innerH = H - padT - padB;
    const vals = clientGrowth.map((d) => d.v);
    const min = Math.floor(Math.min(...vals) / 5) * 5 - 2;
    const max = Math.ceil(Math.max(...vals) / 5) * 5 + 2;
    const X = (i: number) => padL + (i / (clientGrowth.length - 1)) * innerW;
    const Y = (v: number) => padT + (1 - (v - min) / (max - min)) * innerH;
    const mk = (t: string, a: Record<string, string | number>) => {
      const e = document.createElementNS(NS, t);
      for (const k in a) e.setAttribute(k, String(a[k]));
      return e;
    };

    svg.innerHTML = "";
    const defs = mk("defs", {});
    defs.innerHTML =
      `<linearGradient id="cgrad" x1="0" y1="0" x2="0" y2="1">
         <stop offset="0" stop-color="#1FA890" stop-opacity="0.32"/>
         <stop offset="1" stop-color="#1FA890" stop-opacity="0"/>
       </linearGradient>
       <linearGradient id="cline" x1="0" y1="0" x2="1" y2="0">
         <stop offset="0" stop-color="#7B69EE"/><stop offset="1" stop-color="#1FA890"/>
       </linearGradient>`;
    svg.appendChild(defs);

    // baseline grid
    const gaxis = mk("g", { class: "tx-axis" });
    const steps = 3;
    for (let i = 0; i <= steps; i++) {
      const v = min + (max - min) * i / steps, y = Y(v);
      gaxis.appendChild(mk("line", { class: "tx-grid", x1: padL, y1: y, x2: W - padR, y2: y }));
      const t = mk("text", { x: padL - 8, y: y + 3.5, "text-anchor": "end" });
      t.textContent = String(Math.round(v));
      gaxis.appendChild(t);
    }
    clientGrowth.forEach((d, i) => {
      if (i % 2 !== 0 && i !== clientGrowth.length - 1) return;
      const t = mk("text", { x: X(i), y: H - 8, "text-anchor": "middle" });
      t.textContent = d.m;
      gaxis.appendChild(t);
    });
    svg.appendChild(gaxis);

    const linePts = clientGrowth.map((d, i) => `${X(i)},${Y(d.v)}`).join(" ");
    const areaD = `M ${X(0)},${Y(clientGrowth[0].v)} ` +
      clientGrowth.map((d, i) => `L ${X(i)},${Y(d.v)}`).join(" ") +
      ` L ${X(clientGrowth.length - 1)},${padT + innerH} L ${X(0)},${padT + innerH} Z`;
    const area = mk("path", { d: areaD, fill: "url(#cgrad)", opacity: 0 });
    const line = mk("polyline", {
      points: linePts, fill: "none", stroke: "url(#cline)",
      "stroke-width": 2.6, "stroke-linejoin": "round", "stroke-linecap": "round",
    }) as unknown as SVGPolylineElement;
    svg.appendChild(area);
    svg.appendChild(line);

    const len = line.getTotalLength();
    line.style.strokeDasharray = String(len);
    line.style.strokeDashoffset = reduce ? "0" : String(len);
    if (!reduce) {
      anime({ targets: line, strokeDashoffset: [len, 0], duration: 1500, easing: "easeInOutSine" });
      anime({ targets: area, opacity: [0, 1], duration: 900, delay: 650, easing: "easeOutQuad" });
    } else {
      area.setAttribute("opacity", "1");
    }

    const li = clientGrowth.length - 1;
    svg.appendChild(mk("circle", { cx: X(li), cy: Y(clientGrowth[li].v), r: 5.5, fill: "#141033", stroke: "#1FA890", "stroke-width": 2.4 }));

    const cross = mk("line", { x1: 0, y1: padT, x2: 0, y2: padT + innerH, stroke: "rgba(159,147,230,.26)", "stroke-width": 1, opacity: 0 });
    const dot = mk("circle", { r: 5, fill: "#8F7FEA", stroke: "#141033", "stroke-width": 2, opacity: 0 });
    svg.appendChild(cross);
    svg.appendChild(dot);

    const onMove = (e: PointerEvent) => {
      const r = svg.getBoundingClientRect();
      const sx = (e.clientX - r.left) / r.width * W;
      let i = Math.round((sx - padL) / innerW * (clientGrowth.length - 1));
      i = Math.max(0, Math.min(clientGrowth.length - 1, i));
      const d = clientGrowth[i], px = X(i), py = Y(d.v);
      cross.setAttribute("x1", String(px)); cross.setAttribute("x2", String(px)); cross.setAttribute("opacity", "1");
      dot.setAttribute("cx", String(px)); dot.setAttribute("cy", String(py)); dot.setAttribute("opacity", "1");
      tip.innerHTML = `<span class="k">${d.m}</span><br><span class="v">${d.v}</span> <span class="k">clients</span>`;
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
  }, [total]);

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Client Base Growth</div>
          <div className="cs">Total active accounts · trailing 12 months</div>
        </div>
        <div className="tools">
          <span className="pill-tag ok">
            <span className="material-symbols-rounded">trending_up</span>+{growthPct}%
          </span>
        </div>
      </div>

      <div className="cg-body">
        <div className="cg-count">
          <div className="cg-total"><span ref={totalRef}>0</span></div>
          <div className="cg-lab">Active clients</div>
          <div className="cg-sub">
            <span className="delta up">
              <span className="material-symbols-rounded">north_east</span>+{gain}
            </span>
            new since {clientGrowth[0].m}
          </div>
        </div>
        <div className="cg-chart">
          <svg ref={svgRef} viewBox="0 0 520 220" preserveAspectRatio="none" aria-label="Client base growth over 12 months" />
          <div className="chart-tip" ref={tipRef} />
        </div>
      </div>
    </section>
  );
}
