"use client";

import { useEffect, useRef, useState } from "react";
import anime from "animejs";
import { BACKLINK_META, type BacklinkStatus } from "@/lib/offpage";
import { useBacklinks } from "@/lib/hooks/offpage";

// Backlink quality scatter — domain authority (x) vs spam score (y),
// one dot per referring domain, coloured by status. Toxic links land
// top-left (low authority · high spam); quality links bottom-right.
// Animated SVG (anime.js) matching the AuditVolumeChart / TrafficChart idiom.

const STATUS_COLOR: Record<BacklinkStatus, string> = {
  new: "var(--ok)",
  lost: "var(--warn)",
  toxic: "var(--crit)",
};
// Resolved hex for SVG fills (CSS vars don't animate cleanly on attrs here).
const STATUS_HEX: Record<BacklinkStatus, string> = {
  new: "#3DE68A",
  lost: "#FFB43D",
  toxic: "#FF4D6D",
};

const ORDER: BacklinkStatus[] = ["new", "lost", "toxic"];

export default function BacklinkScatter() {
  const svgRef = useRef<SVGSVGElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const [showTable, setShowTable] = useState(false);
  const backlinksQ = useBacklinks();
  const backlinks = backlinksQ.data ?? [];

  useEffect(() => {
    const svg = svgRef.current;
    const tip = tipRef.current;
    if (!svg || !tip) return;
    const NS = "http://www.w3.org/2000/svg";
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

    const W = 760, H = 340, padL = 44, padR = 18, padT = 20, padB = 40;
    const innerW = W - padL - padR, innerH = H - padT - padB;
    // Both axes are 0–100 scores.
    const X = (v: number) => padL + (v / 100) * innerW;
    const Y = (v: number) => padT + (1 - v / 100) * innerH;
    const mk = (t: string, a: Record<string, string | number>) => {
      const e = document.createElementNS(NS, t);
      for (const k in a) e.setAttribute(k, String(a[k]));
      return e;
    };

    svg.innerHTML = "";

    // Toxic quadrant wash — high spam (top) + low authority (left).
    svg.appendChild(mk("rect", {
      x: padL, y: padT, width: innerW * 0.4, height: innerH * 0.5,
      fill: "rgba(255,77,109,.07)", rx: 4,
    }));

    // grid + axis labels
    const gaxis = mk("g", { class: "tx-axis" });
    const steps = 5;
    for (let i = 0; i <= steps; i++) {
      const gx = padL + (innerW / steps) * i;
      const gy = padT + (innerH / steps) * i;
      gaxis.appendChild(mk("line", { class: "tx-grid", x1: gx, y1: padT, x2: gx, y2: padT + innerH }));
      gaxis.appendChild(mk("line", { class: "tx-grid", x1: padL, y1: gy, x2: W - padR, y2: gy }));
      const xt = mk("text", { x: gx, y: H - 20, "text-anchor": "middle" });
      xt.textContent = String((100 / steps) * i);
      gaxis.appendChild(xt);
      const yv = 100 - (100 / steps) * i;
      const yt = mk("text", { x: padL - 9, y: gy + 3.5, "text-anchor": "end" });
      yt.textContent = String(yv);
      gaxis.appendChild(yt);
    }
    svg.appendChild(gaxis);

    // axis titles
    const xTitle = mk("text", { x: padL + innerW / 2, y: H - 4, "text-anchor": "middle", class: "sc-axis-title" });
    xTitle.textContent = "Domain authority →";
    svg.appendChild(xTitle);
    const yTitle = mk("text", { x: 12, y: padT + innerH / 2, "text-anchor": "middle", class: "sc-axis-title", transform: `rotate(-90 12 ${padT + innerH / 2})` });
    yTitle.textContent = "Spam score →";
    svg.appendChild(yTitle);

    // dots
    type DotRef = { el: SVGCircleElement; d: typeof backlinks[number] };
    const dots: DotRef[] = [];
    backlinks.forEach((b, i) => {
      const cx = X(b.authority), cy = Y(b.spam);
      const dot = mk("circle", {
        cx, cy, r: reduce ? 7 : 0,
        fill: STATUS_HEX[b.status], "fill-opacity": 0.85,
        stroke: "var(--card)", "stroke-width": 2, class: "sc-dot",
      }) as SVGCircleElement;
      svg.appendChild(dot);
      dots.push({ el: dot, d: b });
      if (!reduce) {
        anime({ targets: dot, r: [0, 7], duration: 620, delay: 200 + i * 45, easing: "easeOutBack" });
      }
    });

    // hover: nearest dot within a small radius
    let hovered: DotRef | null = null;
    const setHover = (h: DotRef | null) => {
      if (hovered === h) return;
      if (hovered) { hovered.el.setAttribute("r", "7"); hovered.el.setAttribute("fill-opacity", "0.85"); }
      hovered = h;
      if (h) { h.el.setAttribute("r", "9.5"); h.el.setAttribute("fill-opacity", "1"); }
    };
    const onMove = (e: PointerEvent) => {
      const r = svg.getBoundingClientRect();
      const sx = (e.clientX - r.left) / r.width * W;
      const sy = (e.clientY - r.top) / r.height * H;
      let best: DotRef | null = null, bestD = Infinity;
      for (const dot of dots) {
        const dx = Number(dot.el.getAttribute("cx")) - sx;
        const dy = Number(dot.el.getAttribute("cy")) - sy;
        const dist = dx * dx + dy * dy;
        if (dist < bestD) { bestD = dist; best = dot; }
      }
      if (best && bestD < 26 * 26) {
        setHover(best);
        const b = best.d;
        tip.innerHTML = `<span class="k">${b.refDomain}</span><br><span class="v">DA ${b.authority}</span> <span class="k">· spam ${b.spam} · ${BACKLINK_META[b.status].label}</span>`;
        tip.style.left = `${X(b.authority) / W * r.width}px`;
        tip.style.top = `${Y(b.spam) / H * r.height}px`;
        tip.classList.add("show");
      } else {
        setHover(null);
        tip.classList.remove("show");
      }
    };
    const onLeave = () => { setHover(null); tip.classList.remove("show"); };
    svg.addEventListener("pointermove", onMove);
    svg.addEventListener("pointerleave", onLeave);

    return () => {
      svg.removeEventListener("pointermove", onMove);
      svg.removeEventListener("pointerleave", onLeave);
    };
  }, [backlinksQ.data]);

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Backlink Quality Map</div>
          <div className="cs">Domain authority vs spam score · every referring domain, by status</div>
        </div>
        <div className="tools">
          <div className="sc-legend">
            {ORDER.map((s) => (
              <span key={s} className="sc-leg">
                <span className="sc-leg-dot" style={{ background: STATUS_COLOR[s] }} />
                {BACKLINK_META[s].label}
              </span>
            ))}
          </div>
          <button className="ghostbtn" onClick={() => setShowTable((s) => !s)}>
            <span className="material-symbols-rounded">table_rows</span>Data
          </button>
        </div>
      </div>

      <div className="svg-wrap">
        <svg ref={svgRef} viewBox="0 0 760 340" preserveAspectRatio="none" aria-label="Backlink domain authority versus spam score, coloured by link status" />
        <div className="chart-tip" ref={tipRef} />
        <div className="hint">
          <span className="material-symbols-rounded">touch_app</span>Hover a domain
        </div>
      </div>

      <div className={showTable ? "dtable show" : "dtable"}>
        <table>
          <thead><tr><th>Referring domain</th><th>Authority</th><th>Spam</th><th>Status</th></tr></thead>
          <tbody>
            {backlinks.map((b) => (
              <tr key={b.id}>
                <td>{b.refDomain}</td><td>{b.authority}</td><td>{b.spam}</td><td>{BACKLINK_META[b.status].label}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
