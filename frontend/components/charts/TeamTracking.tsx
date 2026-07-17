"use client";

import { useEffect, useRef } from "react";
import anime from "animejs";
import type { CCTeamPoint } from "@/lib/hooks/commandCenter";

// Team member tracking — animated bars + count-ups (anime.js). Identity via name label.
export default function TeamTracking({ team }: { team: CCTeamPoint[] }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const totalRef = useRef<HTMLElement>(null);
  const maxJobs = Math.max(...team.map((t) => t.jobs));
  const total = team.reduce((s, t) => s + t.jobs, 0);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

    const anims: anime.AnimeInstance[] = [];
    root.querySelectorAll<HTMLElement>(".trow").forEach((row, idx) => {
      const t = team[idx];
      const fill = row.querySelector<HTMLElement>(".fill")!;
      const num = row.querySelector<HTMLElement>(".n")!;
      const pct = (t.jobs / maxJobs) * 100;
      if (reduce) {
        fill.style.width = `${pct}%`;
        num.textContent = String(t.jobs);
        return;
      }
      anims.push(anime({ targets: fill, width: [0, `${pct}%`], duration: 1200, delay: 200, easing: "easeOutExpo" }));
      const o = { n: 0 };
      anims.push(anime({ targets: o, n: t.jobs, duration: 1200, delay: 200, easing: "easeOutExpo", round: 1, update: () => { num.textContent = String(o.n); } }));
    });

    if (totalRef.current) {
      if (reduce) {
        totalRef.current.textContent = String(total);
      } else {
        const o = { n: 0 };
        anims.push(anime({ targets: o, n: total, duration: 1400, easing: "easeOutExpo", round: 1, update: () => { if (totalRef.current) totalRef.current.textContent = String(o.n); } }));
      }
    }

    return () => anims.forEach((a) => a.pause());
  }, [maxJobs, total]);

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Team Member Tracking</div>
          <div className="cs">Audit &amp; content jobs delivered · this month</div>
        </div>
      </div>

      <div className="team" ref={rootRef}>
        {team.map((t) => (
          <div className="trow" key={t.nm}>
            <div className="nm">
              <span className="av" style={{ background: t.c }}>{t.init}</span>{t.nm}
            </div>
            <div className="track">
              <div className="fill" style={{ background: `linear-gradient(90deg, ${t.c}, ${t.c}cc)` }} />
            </div>
            <div className="n">0</div>
          </div>
        ))}
      </div>

      <div className="team-foot">
        <span>{team.length} specialists active</span>
        <span><b ref={totalRef}>0</b> jobs delivered</span>
      </div>
    </section>
  );
}
