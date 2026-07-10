"use client";

import { useEffect, useRef } from "react";
import anime from "animejs";

function useCountUp(target: number, format: (n: number) => string) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      node.textContent = format(target);
      return;
    }
    const obj = { n: 0 };
    const anim = anime({
      targets: obj,
      n: target,
      duration: 1400,
      easing: "easeOutExpo",
      update: () => { node.textContent = format(obj.n); },
    });
    return () => anim.pause();
  }, [target, format]);
  return ref;
}

const money = (n: number) => "$" + Math.round(n).toLocaleString("en-US");
const whole = (n: number) => Math.round(n).toLocaleString("en-US");

function Value({ value, format }: { value: number; format: (n: number) => string }) {
  const ref = useCountUp(value, format);
  return <div className="val"><span ref={ref}>{format(0)}</span></div>;
}

type Props = { spend: number; budgetUsed: number; jobs: number; armed: boolean };

export default function CostStats({ spend, budgetUsed, jobs, armed }: Props) {
  return (
    <section className="kpis">
      <div className="kpi hero">
        <div className="ic"><span className="material-symbols-rounded">payments</span></div>
        <div className="lab">Spend this month</div>
        <Value value={spend} format={money} />
        <div className="sub">
          <span className="delta up"><span className="material-symbols-rounded">trending_up</span>8.4%</span> vs. last month
        </div>
      </div>

      <div className="kpi">
        <div className="ic"><span className="material-symbols-rounded">donut_large</span></div>
        <div className="lab">Budget used</div>
        <div className="val">
          <span>{budgetUsed}</span><span className="u">%</span>
        </div>
        <div className="sub">of all client caps combined</div>
      </div>

      <div className="kpi">
        <div className="ic"><span className="material-symbols-rounded">conveyor_belt</span></div>
        <div className="lab">Jobs run</div>
        <Value value={jobs} format={whole} />
        <div className="sub">
          <span className="delta up"><span className="material-symbols-rounded">trending_up</span>31</span> this month
        </div>
      </div>

      <div className={`kpi cst-stopkpi ${armed ? "armed" : "tripped"}`}>
        <div className="ic"><span className="material-symbols-rounded">{armed ? "shield" : "gpp_bad"}</span></div>
        <div className="lab">Spend-stop</div>
        <div className="val cst-stopval">{armed ? "Armed" : "Tripped"}</div>
        <div className="sub">
          <span className={`cst-stopdot ${armed ? "ok" : "crit"}`} />
          {armed ? "paid providers protected" : "paid providers halted"}
        </div>
      </div>
    </section>
  );
}
