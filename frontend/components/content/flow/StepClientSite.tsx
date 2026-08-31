"use client";

// Screen 1 — who it is for, and which of THEIR sites it goes on.
//
// The old first screen asked for a site URL, typed by hand, before it had asked
// who the client was. That URL was then discarded: `site` never reached the
// generate call, so the backend quietly used the client's first registered site
// regardless. The sites were in the database the whole time.
//
// So: client first, then their real sites. And it says up front whether
// publishing will actually work, because finding that out at the end - after
// writing and paying for pages - is the expensive way to learn it.

import { useClients, useClientSites } from "@/lib/hooks/clients";
import { PAGE_KINDS } from "@/lib/pageKinds";
import QueryGuard from "@/components/ui/QueryGuard";
import EmptyState from "@/components/ui/EmptyState";
import type { FlowState } from "./types";

export default function StepClientSite({
  state, patch,
}: {
  state: FlowState;
  patch: (p: Partial<FlowState>) => void;
}) {
  const clientsQ = useClients();
  const sitesQ = useClientSites(state.clientId || null);
  const clients = clientsQ.data ?? [];
  const sites = sitesQ.data ?? [];

  return (
    <div style={{ display: "grid", gap: 18, maxWidth: 720 }}>
      <section className="card" style={{ padding: "var(--s-7)" }}>
        <div className="ct">Who is this for?</div>
        <div className="cs" style={{ margin: "4px 0 14px" }}>
          The client&apos;s stored facts — their name, phone, licence and areas — become the
          only things the page is allowed to state.
        </div>
        <QueryGuard queries={[clientsQ]} label="your clients" minHeight={90}>
          {clients.length === 0 ? (
            <EmptyState
              icon="person_add"
              title="No clients yet"
              hint="Add a client first — content is always written for one, and its facts ground the page."
            />
          ) : (
            <div className="fld">
              <label htmlFor="flow-client">Client</label>
              <select
                id="flow-client"
                value={state.clientId}
                onChange={(e) => {
                  const c = clients.find((x) => x.id === e.target.value);
                  // Changing client invalidates the site AND the picks: keywords
                  // researched for one business are not pages for another.
                  patch({
                    clientId: e.target.value,
                    clientName: c?.cn ?? "",
                    siteDomain: "",
                    picks: [],
                  });
                }}
              >
                <option value="">Choose a client…</option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>{c.cn}</option>
                ))}
              </select>
            </div>
          )}
        </QueryGuard>
      </section>

      {state.clientId && (
        <section className="card" style={{ padding: "var(--s-7)" }}>
          <div className="ct">Which of their sites?</div>
          <div className="cs" style={{ margin: "4px 0 14px" }}>
            Pages are researched against this site and published to it.
          </div>
          <QueryGuard queries={[sitesQ]} label="this client's sites" minHeight={80}>
            {sites.length === 0 ? (
              <EmptyState
                icon="language"
                title="This client has no site registered"
                hint="Add one on the client's page. Without it there is nothing to research against and nowhere to publish."
              />
            ) : (
              <div className="fld">
                <label htmlFor="flow-site">Site</label>
                <select
                  id="flow-site"
                  value={state.siteDomain}
                  onChange={(e) => patch({ siteDomain: e.target.value, picks: [] })}
                >
                  <option value="">Choose a site…</option>
                  {sites.map((s) => (
                    <option key={s.id} value={s.domain}>
                      {s.domain} {s.cms ? `· ${s.cms}` : ""}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </QueryGuard>
        </section>
      )}

      <section className="card" style={{ padding: "var(--s-7)" }}>
        <div className="ct">What kind of pages?</div>
        <div className="cs" style={{ margin: "4px 0 14px" }}>
          Asked once. This decides what gets researched, which layout is built, and how
          the job is filed — they used to be three separate questions with different answers.
        </div>
        <div style={{ display: "grid", gap: 8 }}>
          {PAGE_KINDS.map((k) => (
            <label
              key={k.key}
              style={{
                display: "flex", gap: 11, alignItems: "flex-start", cursor: "pointer",
                border: "1px solid var(--line)", borderRadius: 10, padding: "11px 13px",
                background: state.kind === k.key ? "var(--hover)" : "transparent",
                borderColor: state.kind === k.key ? "var(--accent)" : "var(--line)",
              }}
            >
              <input
                type="radio"
                name="page-kind"
                checked={state.kind === k.key}
                onChange={() => patch({ kind: k.key, picks: [] })}
                style={{ marginTop: 3 }}
              />
              <span className="material-symbols-rounded" style={{ fontSize: 20, opacity: 0.75 }}>
                {k.icon}
              </span>
              <span>
                <span style={{ display: "block", fontWeight: 700, fontSize: 13.5, color: "var(--ink)" }}>
                  {k.label}
                </span>
                <span className="cs">{k.bestFor}</span>
              </span>
            </label>
          ))}
        </div>
      </section>
    </div>
  );
}
