"use client";

import { CATEGORIES, providers, STATUS_META, type VaultKey } from "@/lib/vault";

export default function ProvidersOverview({ keys }: { keys: VaultKey[] }) {
  return (
    <section className="card kv-overview">
      <div className="card-h">
        <div>
          <div className="ct">Providers overview</div>
          <div className="cs">Keys grouped by integration category.</div>
        </div>
      </div>

      <div className="kv-cats">
        {CATEGORIES.map((cat) => {
          const catProviders = providers.filter((p) => p.category === cat.key);
          const catKeys = keys.filter((k) => catProviders.some((p) => p.id === k.provider));
          const attention = catKeys.filter((k) => k.status !== "active").length;
          const connected = catProviders.filter((p) => catKeys.some((k) => k.provider === p.id)).length;

          return (
            <div className="kv-cat" key={cat.key}>
              <span className="kv-cat-ic" style={{ background: `${cat.c}22`, color: cat.c }}>
                <span className="material-symbols-rounded">{cat.icon}</span>
              </span>
              <div className="kv-cat-body">
                <div className="kv-cat-top">
                  <span className="kv-cat-n">{cat.key}</span>
                  <span className="kv-cat-count">{catKeys.length}</span>
                </div>
                <div className="kv-cat-meta">
                  {connected}/{catProviders.length} provider{catProviders.length === 1 ? "" : "s"} connected
                  {attention > 0 && (
                    <span className="kv-cat-warn">
                      <span className="material-symbols-rounded">warning</span>
                      {attention} need{attention === 1 ? "s" : ""} attention
                    </span>
                  )}
                </div>
                {cat.note && (
                  <div className="kv-cat-note">
                    <span className="material-symbols-rounded">help</span>
                    {cat.note}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="kv-legend">
        {(["active", "expiring", "rotate"] as const).map((s) => (
          <span className="kv-leg" key={s}>
            <span className={`kv-dot ${STATUS_META[s].cls}`} />
            {STATUS_META[s].label}
          </span>
        ))}
      </div>
    </section>
  );
}
