"use client";

import { useIntegrations, type IntegrationStatus } from "@/lib/hooks/integrations";

// The API-Management integrations overview: EVERY supported integration with a REAL
// connected/missing status, from GET /integrations (live config + vault presence) —
// never a hard-coded checkmark list. Grouped by category, connected count in the header.
export default function ProvidersOverview() {
  const q = useIntegrations();
  const items = q.data ?? [];

  // Group by category, preserving the backend's ordering.
  const cats: string[] = [];
  const byCat = new Map<string, IntegrationStatus[]>();
  for (const it of items) {
    const bucket = byCat.get(it.category);
    if (bucket) {
      bucket.push(it);
    } else {
      byCat.set(it.category, [it]);
      cats.push(it.category);
    }
  }
  const connected = items.filter((i) => i.connected).length;

  return (
    <section className="card kv-overview">
      <div className="card-h">
        <div>
          <div className="ct">Integrations</div>
          <div className="cs">Every supported integration — connected or missing, from live config &amp; the vault.</div>
        </div>
        <div className="tools">
          <span className="pill-tag">
            <span className="material-symbols-rounded">hub</span>
            {connected}/{items.length} connected
          </span>
        </div>
      </div>

      {q.isLoading ? (
        <div className="panel-hint" style={{ padding: "16px 18px" }}>Loading integrations…</div>
      ) : q.isError ? (
        <div className="panel-hint" role="alert" style={{ padding: "16px 18px", color: "var(--warn, #A96913)" }}>
          Couldn&apos;t load integrations — {(q.error as Error)?.message ?? "try again"}.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: "4px 2px" }}>
          {cats.map((cat) => (
            <div key={cat}>
              <div
                style={{
                  fontSize: 12,
                  textTransform: "uppercase",
                  letterSpacing: 0.4,
                  color: "var(--muted)",
                  margin: "2px 2px 8px",
                }}
              >
                {cat}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {(byCat.get(cat) ?? []).map((it) => (
                  <div
                    key={it.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: "9px 12px",
                      border: "1px solid var(--line, rgba(0,0,0,0.08))",
                      borderRadius: 10,
                    }}
                  >
                    <span
                      className="material-symbols-rounded"
                      style={{ color: it.connected ? "var(--ok, #1FA890)" : "var(--muted)" }}
                    >
                      {it.connected ? "check_circle" : "radio_button_unchecked"}
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 650 }}>{it.name}</div>
                      <div style={{ color: "var(--muted)", fontSize: 12 }}>{it.detail}</div>
                    </div>
                    <span
                      className={`status-pill ${it.connected ? "ok" : "mut"}`}
                      title={it.source === "vault" ? "From the key vault" : "From platform config"}
                      style={{ whiteSpace: "nowrap" }}
                    >
                      {it.connected ? "Connected" : "Missing"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
