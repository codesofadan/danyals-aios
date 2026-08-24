"use client";

import { useEffect, useRef } from "react";
import anime from "animejs";
import { useContentStats } from "@/lib/hooks/content";

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

export default function ContentKpis() {
  // Server-computed over the WHOLE ledger. These used to be derived from the board's
  // job array, which the API page-caps - so every tile silently under-counted once a
  // client passed the page size, and "Published this month" counted `done` jobs of
  // ANY month because the array carried no date filter.
  const statsQ = useContentStats();
  const s = statsQ.data;

  if (statsQ.isError) {
    return (
      <section className="kpis">
        <div className="cs" role="alert" style={{ color: "var(--warn)" }}>
          Couldn&apos;t load content KPIs. {(statsQ.error as Error)?.message ?? "Try again"}.
        </div>
      </section>
    );
  }

  return (
    <section className="kpis">
      <div className="kpi hero">
        <div className="ic"><span className="material-symbols-rounded">conveyor_belt</span></div>
        <div className="lab">Jobs in pipeline</div>
        <Val value={s?.inPipeline ?? 0} />
        <div className="sub">queued, drafting or publishing</div>
      </div>
      <div className="kpi">
        <div className="ic"><span className="material-symbols-rounded">rate_review</span></div>
        <div className="lab">Awaiting review</div>
        <Val value={s?.awaitingReview ?? 0} />
        <div className="sub">the human 10% — approve or edit</div>
      </div>
      <div className="kpi">
        <div className="ic"><span className="material-symbols-rounded">task_alt</span></div>
        <div className="lab">Published this month</div>
        <Val value={s?.publishedThisMonth ?? 0} />
        {/* A degraded job is terminal but never reached the client's site (migration
            0081). Surfaced next to the published count so the two are never conflated
            - the sub-line is omitted entirely when there are none. */}
        <div className="sub">
          {s?.degradedThisMonth
            ? <span className="delta down">
                <span className="material-symbols-rounded">error</span>
                {s.degradedThisMonth} not live
              </span>
            : "live on the client's site"}
        </div>
      </div>
      <div className="kpi">
        <div className="ic"><span className="material-symbols-rounded">payments</span></div>
        <div className="lab">Avg cost / page</div>
        <Val value={s?.avgCost ?? 0} unit="$" decimals={2} />
        <div className="sub">mean over priced jobs</div>
      </div>
    </section>
  );
}
