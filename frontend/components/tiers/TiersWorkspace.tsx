"use client";

import { useMemo } from "react";
import {
  TIER_BY_KEY, BASE_COST,
  type TierKey,
} from "@/lib/tiers";
import { useTierClients, useSetDeliveryTier } from "@/lib/hooks/tiers";
import TierCards from "./TierCards";
import ClientAssignment from "./ClientAssignment";
import FeatureMatrix from "./FeatureMatrix";

const KPI: { key: TierKey; label: string; icon: string; c: string }[] = [
  { key: "free", label: "Clients on Free", icon: "toll", c: "#2F8A73" },
  { key: "semi", label: "Clients on Semi-Auto", icon: "tune", c: "#7C5F91" },
  { key: "fully", label: "Clients on Fully-Auto", icon: "bolt", c: "#432B52" },
];

export default function TiersWorkspace() {
  const clientsQ = useTierClients();
  const setDeliveryTier = useSetDeliveryTier();
  const clients = clientsQ.data ?? [];

  const stats = useMemo(() => {
    const counts: Record<TierKey, number> = { free: 0, semi: 0, fully: 0 };
    let spend = 0;
    for (const c of clients) {
      counts[c.tier]++;
      spend += TIER_BY_KEY[c.tier].price;
    }
    return { counts, spend };
  }, [clients]);

  // Re-dial a client's preset on the backend; the assignment list refetches on
  // success and the KPI counts / spend recompute from the fresh data.
  function handleSwitch(id: string, tier: TierKey) {
    setDeliveryTier.mutate({ clientId: id, tier });
  }

  return (
    <>
      {/* KPI row */}
      <section className="kpis">
        {KPI.map((k, i) => (
          <div key={k.key} className={i === 0 ? "kpi hero" : "kpi"}>
            <div className="ic"><span className="material-symbols-rounded">{k.icon}</span></div>
            <div className="lab">{k.label}</div>
            <div className="val">{stats.counts[k.key]}</div>
            <div className="sub">
              <span className="tr-swatch" style={{ background: k.c }} />
              {clients.length ? Math.round((stats.counts[k.key] / clients.length) * 100) : 0}% of book
            </div>
          </div>
        ))}
        <div className="kpi">
          <div className="ic"><span className="material-symbols-rounded">payments</span></div>
          <div className="lab">Monthly platform spend</div>
          <div className="val"><span className="tr-cur-lg">$</span>{stats.spend}</div>
          <div className="sub">
            <span className="material-symbols-rounded tr-sub-ic">dns</span>
            + ${BASE_COST}/mo shared base
          </div>
        </div>
      </section>

      {/* Tier comparison cards */}
      <section className="card tr-card">
        <div className="card-h">
          <div>
            <div className="ct">Tier presets</div>
            <div className="cs">Each tier is a preset over the per-client cost dial — a human approves everything, on every tier.</div>
          </div>
          <div className="tools">
            <span className="pill-tag info"><span className="material-symbols-rounded">verified_user</span>Human-in-the-loop</span>
          </div>
        </div>
        <TierCards counts={stats.counts} />
      </section>

      {/* Per-client assignment */}
      <section className="card tr-card">
        <div className="card-h">
          <div>
            <div className="ct">Client tier assignment</div>
            <div className="cs">Switch a client&apos;s preset to re-dial their features and recompute spend.</div>
          </div>
          <div className="tools">
            <span className="pill-tag"><span className="material-symbols-rounded">group</span>{clients.length} clients</span>
          </div>
        </div>
        {clientsQ.isLoading ? (
          <div className="panel-hint" style={{ padding: "18px 20px" }}>Loading clients…</div>
        ) : clientsQ.isError ? (
          <div className="panel-hint" role="alert" style={{ padding: "18px 20px", color: "var(--warn, #A96913)" }}>
            Couldn&apos;t load clients — {(clientsQ.error as Error)?.message ?? "try again"}.
          </div>
        ) : clients.length === 0 ? (
          <div className="panel-hint" style={{ padding: "18px 20px" }}>No clients yet.</div>
        ) : (
          <ClientAssignment clients={clients} onSwitch={handleSwitch} />
        )}
        {setDeliveryTier.isError && (
          <div className="panel-hint" role="alert" style={{ padding: "0 20px 16px", color: "var(--warn, #A96913)" }}>
            Couldn&apos;t switch tier — {(setDeliveryTier.error as Error)?.message ?? "try again"}.
          </div>
        )}
      </section>

      {/* Feature-area × tier matrix */}
      <section className="card tr-card">
        <div className="card-h">
          <div>
            <div className="ct">Feature dial · tier matrix</div>
            <div className="cs">The 7 gated areas by preset — Off, By-hand (manual / free tools), or API (paid data, still approved).</div>
          </div>
          <div className="tools tr-legend">
            <span className="tr-mode off">Off</span>
            <span className="tr-mode byhand">By-hand</span>
            <span className="tr-mode api">API</span>
          </div>
        </div>
        <FeatureMatrix />
      </section>
    </>
  );
}
