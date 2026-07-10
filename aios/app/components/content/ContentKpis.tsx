"use client";

import { useEffect, useRef } from "react";
import anime from "animejs";
import type { ContentJob } from "@/lib/content";

function useCountUp(target: number, decimals = 0) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const fmt = (n: number) =>
      decimals ? n.toFixed(decimals) : Math.round(n).toLocaleString();
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      node.textContent = fmt(target);
      return;
    }
    const obj = { n: 0 };
    const anim = anime({
      targets: obj, n: target, duration: 1200, easing: "easeOutExpo",
      update: () => { node.textContent = fmt(obj.n); },
    });
    return () => anim.pause();
  }, [target, decimals]);
  return ref;
}

function Val({ value, unit, decimals }: { value: number; unit?: string; decimals?: number }) {
  const ref = useCountUp(value, decimals);
  return (
    <div className="val">
      {unit === "$" && <span className="u" style={{ marginRight: 1 }}>$</span>}
      <span ref={ref}>0</span>
      {unit && unit !== "$" && <span className="u">{unit}</span>}
    </div>
  );
}

export default function ContentKpis({ jobs }: { jobs: ContentJob[] }) {
  const inPipeline = jobs.filter((j) =>
    ["queued", "drafting", "needs_review", "publishing"].includes(j.status)).length;
  const awaiting = jobs.filter((j) => j.status === "needs_review").length;
  const published = jobs.filter((j) => j.status === "done").length;
  const priced = jobs.filter((j) => j.cost > 0);
  const avgCost = priced.length
    ? priced.reduce((s, j) => s + j.cost, 0) / priced.length : 0;

  return (
    <section className="kpis">
      <div className="kpi hero">
        <div className="ic"><span className="material-symbols-rounded">conveyor_belt</span></div>
        <div className="lab">Jobs in pipeline</div>
        <Val value={inPipeline} />
        <div className="sub">
          <span className="delta up"><span className="material-symbols-rounded">trending_up</span>3</span>{" "}
          queued today
        </div>
      </div>
      <div className="kpi">
        <div className="ic"><span className="material-symbols-rounded">rate_review</span></div>
        <div className="lab">Awaiting review</div>
        <Val value={awaiting} />
        <div className="sub">the human 10% — approve or edit</div>
      </div>
      <div className="kpi">
        <div className="ic"><span className="material-symbols-rounded">task_alt</span></div>
        <div className="lab">Published this month</div>
        <Val value={published} />
        <div className="sub">
          <span className="delta up"><span className="material-symbols-rounded">trending_up</span>18%</span>{" "}
          vs. last month
        </div>
      </div>
      <div className="kpi">
        <div className="ic"><span className="material-symbols-rounded">payments</span></div>
        <div className="lab">Avg cost / page</div>
        <Val value={avgCost} unit="$" decimals={2} />
        <div className="sub">
          <span className="delta down"><span className="material-symbols-rounded">trending_down</span>6%</span>{" "}
          within $10–50 band
        </div>
      </div>
    </section>
  );
}
