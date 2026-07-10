"use client";

import { useEffect, useRef } from "react";
import anime from "animejs";
import { CONVERSION_RATE, type Upsell } from "@/lib/upsells";

function useCountUp(target: number) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      node.textContent = Math.round(target).toLocaleString();
      return;
    }
    const obj = { n: 0 };
    const anim = anime({
      targets: obj,
      n: target,
      duration: 1200,
      easing: "easeOutExpo",
      update: () => { node.textContent = Math.round(obj.n).toLocaleString(); },
    });
    return () => anim.pause();
  }, [target]);
  return ref;
}

function Value({ value, unit }: { value: number; unit?: string }) {
  const ref = useCountUp(value);
  return (
    <div className="val">
      {unit === "$" && <span className="u">$</span>}
      <span ref={ref}>0</span>
      {unit && unit !== "$" && <span className="u">{unit}</span>}
    </div>
  );
}

export default function UpsellStats({ list }: { list: Upsell[] }) {
  const active = list.filter((u) => u.active);
  const clicks = list.reduce((s, u) => s + u.clicks30d, 0);
  const top = [...list].sort((a, b) => b.clicks30d - a.clicks30d)[0];
  const conversions = Math.round(clicks * CONVERSION_RATE);

  return (
    <section className="kpis">
      <div className="kpi hero">
        <div className="ic"><span className="material-symbols-rounded">sell</span></div>
        <div className="lab">Active upsells</div>
        <Value value={active.length} />
        <div className="sub">
          <span className="delta up"><span className="material-symbols-rounded">trending_up</span>2</span>{" "}
          live in client portal
        </div>
      </div>

      <div className="kpi">
        <div className="ic"><span className="material-symbols-rounded">ads_click</span></div>
        <div className="lab">Gig clicks (30d)</div>
        <Value value={clicks} />
        <div className="sub">
          <span className="delta up"><span className="material-symbols-rounded">trending_up</span>18%</span>{" "}
          vs. prior 30 days
        </div>
      </div>

      <div className="kpi">
        <div className="ic"><span className="material-symbols-rounded">workspace_premium</span></div>
        <div className="lab">Top gig</div>
        <div className="val up-top-val" title={top?.title}>{top?.title ?? "—"}</div>
        <div className="sub">
          <span className="up-fiverr-dot" /> {top ? `${top.clicks30d.toLocaleString()} clicks` : "no data"}
        </div>
      </div>

      <div className="kpi">
        <div className="ic"><span className="material-symbols-rounded">shopping_cart_checkout</span></div>
        <div className="lab">Est. conversions</div>
        <Value value={conversions} />
        <div className="sub">
          <span className="delta up"><span className="material-symbols-rounded">trending_up</span>6.2%</span>{" "}
          click-to-order rate
        </div>
      </div>
    </section>
  );
}
