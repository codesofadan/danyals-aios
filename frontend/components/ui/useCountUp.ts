"use client";

// The one animated-number hook. Eleven components carried a near-identical local
// copy of this (StatTiles, AuditStats, TeamStats, CostStats, ContentKpis,
// MilestoneStats, ReportsKpis, UpsellStats, OffpageWorkspace, BackupsWorkspace,
// FreeAuditReport), varying only in decimals/formatting — which meant eleven
// places for the reduced-motion check to be forgotten. The locals are deleted as
// each file is touched; new KPI work imports this.
//
// It respects prefers-reduced-motion by SNAPPING to the value: the number is the
// content, the count-up is decoration.

import { useEffect, useRef } from "react";
import anime from "animejs";

export function useCountUp(
  target: number,
  format: (n: number) => string = (n) => Math.round(n).toLocaleString(),
) {
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
    // `format` is deliberately not a dependency: callers pass inline lambdas, and
    // re-running the animation because a lambda got a new identity would restart
    // the count-up on every parent render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);
  return ref;
}

export default useCountUp;
