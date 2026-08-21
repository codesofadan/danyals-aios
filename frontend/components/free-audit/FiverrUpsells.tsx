"use client";

import { useEffect, useRef } from "react";
import anime from "animejs";
import { freeAuditGigs } from "@/lib/freeAuditGigs";

// Post-report conversion surface: the agency's real Fiverr gigs, shown as
// "recommended next steps" once a prospect has seen their free score. Cards
// stagger in for a polished reveal (reduced-motion honored). Links open the
// live gig on Fiverr in a new tab. `fiverrUrl` (the backend-owned profile link
// from the report) powers the section-level "view all" CTA.
export default function FiverrUpsells({ fiverrUrl }: { fiverrUrl?: string }) {
  const gridRef = useRef<HTMLDivElement>(null);
  const active = freeAuditGigs;

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
          <h2 className="fa-upsell-t">Want more hands-on help?</h2>
          <p className="fa-upsell-s">Optional — if you&apos;d like a hand fixing what this audit surfaced, explore our SEO services on Fiverr.</p>
        </div>
        {fiverrUrl && (
          <a className="fa-upsell-all" href={fiverrUrl} target="_blank" rel="noopener noreferrer">
            Explore all services
            <span className="material-symbols-rounded">arrow_outward</span>
          </a>
        )}
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
            {u.image ? (
              <div className="fa-gig-img" style={{ backgroundImage: `url(${u.image})` }} />
            ) : (
              <div className="fa-gig-top">
                <span className="fa-gig-ic" style={{ background: `${u.color}22`, color: u.color }}>
                  <span className="material-symbols-rounded">{u.icon}</span>
                </span>
              </div>
            )}
            <div className="fa-gig-title">{u.title}</div>
            <p className="fa-gig-desc">{u.description}</p>
            <div className="fa-gig-foot">
              <span className="fa-gig-price fa-gig-price-muted">On Fiverr</span>
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
