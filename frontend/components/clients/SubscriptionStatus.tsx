"use client";

import { useMemo } from "react";
import EmptyState from "@/components/ui/EmptyState";
import { TIER_COLOR, type ClientRecord, type SubStatus, type SubTier } from "@/lib/data";
import { useClients } from "@/lib/hooks/clients";

const TIERS: SubTier[] = ["Starter", "Growth", "Scale"];
const STATUS_META: Record<SubStatus, { label: string; c: string }> = {
  active: { label: "Active", c: "#2FA36B" },
  trial: { label: "Trial", c: "#5B8DEF" },
  past_due: { label: "Past due", c: "#C8871A" },
  paused: { label: "Paused", c: "#8A8F98" },
};

// Subscription health — REAL aggregation over the live client directory
// (GET /clients): plan mix, status distribution and total MRR. No billing
// gateway exists (invoices are manual), so the directory rows ARE the source
// of truth for plan + MRR.
export default function SubscriptionStatus() {
  const clientsQ = useClients();
  const clients: ClientRecord[] = useMemo(() => clientsQ.data ?? [], [clientsQ.data]);

  const { mrr, byTier, byStatus } = useMemo(() => {
    const byTier = new Map<SubTier, number>();
    const byStatus = new Map<SubStatus, number>();
    let mrr = 0;
    for (const c of clients) {
      mrr += c.mrr || 0;
      byTier.set(c.tier, (byTier.get(c.tier) ?? 0) + 1);
      byStatus.set(c.status, (byStatus.get(c.status) ?? 0) + 1);
    }
    return { mrr, byTier, byStatus };
  }, [clients]);

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Subscription Status</div>
          <div className="cs">Plan mix &amp; monthly recurring revenue</div>
        </div>
      </div>

      {clients.length === 0 ? (
        <EmptyState
          icon="donut_small"
          title="No clients yet"
          hint="Plan mix and MRR appear here as soon as the first client is added."
        />
      ) : (
        <div style={{ display: "grid", gap: "0.9rem" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem" }}>
            <span style={{ fontSize: "1.8rem", fontWeight: 800 }}>${mrr.toLocaleString()}</span>
            <span style={{ color: "var(--muted)", fontSize: "0.85rem" }}>MRR · {clients.length} account{clients.length === 1 ? "" : "s"}</span>
          </div>

          {/* plan mix bar */}
          <div style={{ display: "flex", height: 10, borderRadius: 6, overflow: "hidden" }} aria-label="Plan mix">
            {TIERS.map((t) => {
              const n = byTier.get(t) ?? 0;
              if (!n) return null;
              return <span key={t} style={{ flex: n, background: TIER_COLOR[t] }} title={`${t}: ${n}`} />;
            })}
          </div>
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", fontSize: "0.82rem" }}>
            {TIERS.map((t) => (
              <span key={t} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 8, height: 8, borderRadius: 2, background: TIER_COLOR[t], display: "inline-block" }} />
                {t} · <b>{byTier.get(t) ?? 0}</b>
              </span>
            ))}
          </div>

          {/* status distribution */}
          <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
            {(Object.keys(STATUS_META) as SubStatus[]).map((s) => {
              const n = byStatus.get(s) ?? 0;
              if (!n) return null;
              const m = STATUS_META[s];
              return (
                <span key={s} style={{
                  display: "inline-flex", alignItems: "center", gap: 6, padding: "0.25rem 0.6rem",
                  borderRadius: 999, border: `1px solid ${m.c}55`, color: m.c, fontSize: "0.8rem", fontWeight: 600,
                }}>
                  <span style={{ width: 7, height: 7, borderRadius: 999, background: m.c, display: "inline-block" }} />
                  {m.label} · {n}
                </span>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}
