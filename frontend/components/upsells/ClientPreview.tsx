"use client";

import type { Upsell } from "@/lib/upsells";

export default function ClientPreview({ list }: { list: Upsell[] }) {
  const active = list.filter((u) => u.active);

  return (
    <section className="card up-preview">
      <div className="card-h">
        <div>
          <div className="ct">Client-portal preview</div>
          <div className="cs">Exactly how the active upsells appear to clients.</div>
        </div>
        <div className="tools">
          <span className="pill-tag info sm">
            <span className="material-symbols-rounded">visibility</span>Live
          </span>
        </div>
      </div>

      <div className="up-portal">
        <div className="up-portal-bar">
          <span className="up-portal-dot" /><span className="up-portal-dot" /><span className="up-portal-dot" />
          <span className="up-portal-url">portal.xegents.ai/recommended</span>
        </div>

        <div className="up-portal-head">
          <div className="up-portal-title">Recommended for you</div>
          <div className="up-portal-sub">Hand-picked services from our Fiverr studio</div>
        </div>

        {active.length === 0 ? (
          <div className="up-empty">
            <span className="material-symbols-rounded">sell</span>
            No active upsells — toggle one on to preview it here.
          </div>
        ) : (
          <div className="up-grid">
            {active.map((u) => (
              <article className="up-c" key={u.id}>
                <div className="up-c-top">
                  <span className="up-c-badge" style={{ background: `${u.color}22`, color: u.color }}>
                    <span className="material-symbols-rounded">{u.icon}</span>
                  </span>
                  <span className="up-c-rating">
                    <span className="material-symbols-rounded">star</span>
                    {u.rating.toFixed(1)}
                    <span className="up-c-reviews">({u.reviews})</span>
                  </span>
                </div>
                <div className="up-c-title">{u.title}</div>
                <div className="up-c-desc">{u.description}</div>
                <div className="up-c-foot">
                  <div className="up-c-price">
                    <span className="up-c-from">From</span> ${u.price}
                  </div>
                  <a className="up-c-cta" href={u.fiverrUrl || "#"} target="_blank" rel="noreferrer">
                    <span className="up-fiverr-mark">fi</span>
                    View on Fiverr
                  </a>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
