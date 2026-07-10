"use client";

import { useMemo, useState } from "react";
import {
  tierClients, TIER_BY_KEY, BASE_COST,
  type TierClient, type TierKey,
} from "@/lib/tiers";
import TierCards from "./TierCards";
import ClientAssignment from "./ClientAssignment";
import FeatureMatrix from "./FeatureMatrix";

const KPI: { key: TierKey; label: string; icon: string; c: string }[] = [
  { key: "free", label: "Clients on Free", icon: "toll", c: "#22C08A" },
  { key: "semi", label: "Clients on Semi-Auto", icon: "tune", c: "#4D8DF0" },
  { key: "fully", label: "Clients on Fully-Auto", icon: "bolt", c: "#7B69EE" },
];

export default function TiersWorkspace() {
  const [clients, setClients] = useState<TierClient[]>(tierClients);

  const stats = useMemo(() => {
    const counts: Record<TierKey, number> = { free: 0, semi: 0, fully: 0 };
    let spend = 0;
    for (const c of clients) {
      counts[c.tier]++;
      spend += TIER_BY_KEY[c.tier].price;
    }
    return { counts, spend };
  }, [clients]);

  function handleSwitch(id: string, tier: TierKey) {
    setClients((prev) => prev.map((c) => (c.id === id ? { ...c, tier } : c)));
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
              {Math.round((stats.counts[k.key] / clients.length) * 100)}% of book
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
        <ClientAssignment clients={clients} onSwitch={handleSwitch} />
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
