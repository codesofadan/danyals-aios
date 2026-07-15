"use client";

import { useEffect, useRef } from "react";
import anime from "animejs";
import { upsells } from "@/lib/upsells";

// Post-report conversion surface: the agency's real Fiverr gigs, shown as
// "recommended next steps" once a prospect has seen their free score. Cards
// stagger in for a polished reveal (reduced-motion honored). Links open the
// live gig on Fiverr in a new tab — consistent with the admin Upsells module.
export default function FiverrUpsells() {
  const gridRef = useRef<HTMLDivElement>(null);
  const active = upsells.filter((u) => u.active);

  useEffect(() => {
    const node = gridRef.current;
    if (!node) return;
    const cards = node.querySelectorAll<HTMLElement>(".fa-gig");
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      cards.forEach((c) => {
        c.style.opacity = "1";
        c.style.transform = "none";
      });
      return;
    }
    const anim = anime({
      targets: cards,
      opacity: [0, 1],
      translateY: [22, 0],
      delay: anime.stagger(90, { start: 120 }),
      duration: 620,
      easing: "easeOutExpo",
    });
    return () => anim.pause();
  }, []);

  return (
    <section className="fa-upsell">
      <div className="fa-upsell-h">
        <span className="fa-fiverr-badge"><span className="material-symbols-rounded">verified</span></span>
        <div>
          <h2 className="fa-upsell-t">Recommended next steps</h2>
          <p className="fa-upsell-s">Done for you by our team on Fiverr — fix what your audit surfaced.</p>
        </div>
      </div>

      <div className="fa-gig-grid" ref={gridRef}>
        {active.map((u) => (
          <a
            key={u.id}
            className="fa-gig"
            href={u.fiverrUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            <div className="fa-gig-top">
              <span className="fa-gig-ic" style={{ background: `${u.color}22`, color: u.color }}>
                <span className="material-symbols-rounded">{u.icon}</span>
              </span>
              <span className="fa-gig-rating">
                <span className="material-symbols-rounded">star</span>
                {u.rating.toFixed(1)}
                <span className="fa-gig-reviews">({u.reviews})</span>
              </span>
            </div>
            <div className="fa-gig-title">{u.title}</div>
            <p className="fa-gig-desc">{u.description}</p>
            <div className="fa-gig-foot">
              <span className="fa-gig-price">
                from <strong>${u.price}</strong>
              </span>
              <span className="fa-fiverr-cta">
                View on Fiverr
                <span className="material-symbols-rounded">arrow_outward</span>
              </span>
            </div>
          </a>
        ))}
      </div>
    </section>
  );
}
