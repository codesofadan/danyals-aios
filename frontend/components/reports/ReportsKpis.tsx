"use client";

import { useEffect, useRef } from "react";
import anime from "animejs";

type Props = {
  workbooks: number;
  lastSync: string;
  rowsToday: number;
  health: number;
};

// Tween from the previously shown value to the new target so live
// updates (a fresh sync) nudge upward instead of restarting from 0.
function useCountUp(target: number) {
  const ref = useRef<HTMLSpanElement>(null);
  const last = useRef(0);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      node.textContent = target.toLocaleString();
      last.current = target;
      return;
    }
    const obj = { n: last.current };
    const anim = anime({
      targets: obj,
      n: target,
      duration: 1100,
      easing: "easeOutExpo",
      update: () => { node.textContent = Math.round(obj.n).toLocaleString(); },
    });
    last.current = target;
    return () => anim.pause();
  }, [target]);
  return ref;
}

function Num({ value, unit }: { value: number; unit?: string }) {
  const ref = useCountUp(value);
  return (
    <div className="val"><span ref={ref}>0</span>{unit && <span className="u">{unit}</span>}</div>
  );
}

export default function ReportsKpis({ workbooks, lastSync, rowsToday, health }: Props) {
  return (
    <section className="kpis">
      <div className="kpi hero">
        <div className="ic"><span className="material-symbols-rounded">table_view</span></div>
        <div className="lab">Client workbooks</div>
        <Num value={workbooks} />
        <div className="sub"><span className="delta up"><span className="material-symbols-rounded">trending_up</span>1</span> + master rollup</div>
      </div>

      <div className="kpi">
        <div className="ic"><span className="material-symbols-rounded">sync</span></div>
        <div className="lab">Last sync</div>
        <div className="val rp-lastsync">{lastSync}</div>
        <div className="sub"><span className="delta up"><span className="material-symbols-rounded">check_circle</span>live</span> master rollup current</div>
      </div>

      <div className="kpi">
        <div className="ic"><span className="material-symbols-rounded">table_rows</span></div>
        <div className="lab">Rows synced</div>
        <Num value={rowsToday} />
        <div className="sub"><span className="delta up"><span className="material-symbols-rounded">trending_up</span>today</span> across all tabs</div>
      </div>

      <div className="kpi">
        <div className="ic"><span className="material-symbols-rounded">monitoring</span></div>
        <div className="lab">Sync health</div>
        <Num value={health} unit="%" />
        <div className="sub"><span className="delta up"><span className="material-symbols-rounded">bolt</span>row writes</span> succeeding today</div>
      </div>
    </section>
  );
}
