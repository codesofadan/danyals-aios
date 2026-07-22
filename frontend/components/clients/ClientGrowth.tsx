"use client";

import { useMemo } from "react";
import EmptyState from "@/components/ui/EmptyState";
import { SERIES } from "@/lib/data";
import { useClients } from "@/lib/hooks/clients";

// Client base growth — REAL cumulative account count by the year each client
// joined (ClientRecord.since from GET /clients). Coarser than a monthly trend,
// but honest: the directory is the source of truth until billing history exists.
export default function ClientGrowth() {
  const clientsQ = useClients();
  const clients = useMemo(() => clientsQ.data ?? [], [clientsQ.data]);

  const points = useMemo(() => {
    const byYear = new Map<string, number>();
    for (const c of clients) {
      const y = String(c.since || "").trim() || "—";
      byYear.set(y, (byYear.get(y) ?? 0) + 1);
    }
    const years = [...byYear.keys()].sort();
    let running = 0;
    return years.map((y) => {
      running += byYear.get(y) ?? 0;
      return { year: y, total: running };
    });
  }, [clients]);

  const max = points.length ? points[points.length - 1].total : 0;

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Client Base Growth</div>
          <div className="cs">Total active accounts · by year joined</div>
        </div>
      </div>

      {points.length === 0 ? (
        <EmptyState
          icon="show_chart"
          title="No clients yet"
          hint="Account growth appears here as soon as the first client is added."
        />
      ) : (
        <div style={{ display: "flex", alignItems: "flex-end", gap: "0.7rem", height: 130, padding: "0.4rem 0" }}>
          {points.map((p) => (
            <div key={p.year} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 6, minWidth: 0 }}>
              <span style={{ fontSize: "0.8rem", fontWeight: 700 }}>{p.total}</span>
              <div
                style={{
                  width: "100%", maxWidth: 46, borderRadius: "6px 6px 2px 2px",
                  height: `${Math.max(8, (p.total / (max || 1)) * 84)}px`,
                  background: `linear-gradient(180deg, ${SERIES.c1}, ${SERIES.c1}88)`,
                }}
                title={`${p.total} account${p.total === 1 ? "" : "s"} by ${p.year}`}
              />
              <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>{p.year}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
