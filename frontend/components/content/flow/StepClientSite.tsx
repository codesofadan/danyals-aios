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
//
// THE SITE IS NO LONGER A HARD GATE. A client with no `sites` row could not leave
// this screen: the Next button stayed disabled behind "This client has no site
// registered — add one on the client's page". There was no such control anywhere
// in the product (POST /clients/{id}/sites had zero frontend callers), so the
// instruction named a place that did not exist and the flow was unexitable for
// that client. The backend never required it either: `site_domain` is optional on
// both creation schemas, `_chosen_site` tolerates None, and generation completes
// without one. So the screen now offers all three true options - a registered
// site, the website already stored on the client's business profile (registering
// it in one click), or continuing without one - and says plainly what each costs.

import { useState } from "react";
import {
  normalizeDomain,
  useClientBusinessProfile,
  useClients,
  useClientSites,
  useCreateClientSite,
} from "@/lib/hooks/clients";
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
  const profileQ = useClientBusinessProfile(state.clientId || null);
  const createSite = useCreateClientSite();
  const clients = clientsQ.data ?? [];
  const sites = sitesQ.data ?? [];

  const [registerError, setRegisterError] = useState("");

  // The website the client's own business profile already carries (captured when
  // the client was added). Offered only when it is not already a registered site.
  const profileDomain = normalizeDomain(profileQ.data?.websiteUrl ?? "");
  const alreadyRegistered = sites.some((s) => normalizeDomain(s.domain) === profileDomain);
  const derivedDomain = profileDomain && !alreadyRegistered ? profileDomain : "";

  const useDerived = () => {
    if (!derivedDomain || createSite.isPending) return;
    setRegisterError("");
    createSite.mutate(
      { clientId: state.clientId, domain: derivedDomain },
      {
        onSuccess: () => patch({ siteDomain: derivedDomain, siteRegistered: true, picks: [] }),
        onError: (err: unknown) => {
          // A non-lead cannot register a site (ManageClients). That must not strand
          // them: the domain is still usable for research, it just cannot be the
          // publish target, and the caption below says so rather than failing.
          const status = (err as { status?: number } | null)?.status;
          patch({ siteDomain: derivedDomain, siteRegistered: false, picks: [] });
          setRegisterError(
            status === 403
              ? "Using this site for research only — ask a lead to register it as the publishing site."
              : "Couldn't register the site, so it will be used for research only.",
          );
        },
      },
    );
  };

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
                  setRegisterError("");
                  patch({
                    clientId: e.target.value,
                    clientName: c?.cn ?? "",
                    siteDomain: "",
                    siteRegistered: false,
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
            Pages are researched against this site and published to it. Optional — you
            can write pages without one and publish them later.
          </div>
          <QueryGuard queries={[sitesQ]} label="this client's sites" minHeight={80}>
            <div style={{ display: "grid", gap: 12 }}>
              {sites.length > 0 && (
                <div className="fld">
                  <label htmlFor="flow-site">Site</label>
                  <select
                    id="flow-site"
                    value={state.siteRegistered ? state.siteDomain : ""}
                    onChange={(e) => {
                      setRegisterError("");
                      patch({
                        siteDomain: e.target.value,
                        siteRegistered: Boolean(e.target.value),
                        picks: [],
                      });
                    }}
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

              {derivedDomain && (
                <div
                  style={{
                    border: "1px solid var(--line)", borderRadius: 10, padding: "12px 13px",
                    display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap",
                  }}
                >
                  <span className="material-symbols-rounded" style={{ fontSize: 20, opacity: 0.75 }}>
                    language
                  </span>
                  <span style={{ flex: 1, minWidth: 220 }}>
                    <span style={{ display: "block", fontWeight: 700, fontSize: 13.5, color: "var(--ink)" }}>
                      {derivedDomain}
                    </span>
                    <span className="cs">
                      {sites.length === 0
                        ? "From this client's business profile. No site is registered yet."
                        : "From this client's business profile, not yet registered."}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="ghostbtn"
                    onClick={useDerived}
                    disabled={createSite.isPending}
                  >
                    {createSite.isPending ? "Registering…" : "Use this site"}
                  </button>
                </div>
              )}

              {sites.length === 0 && !derivedDomain && (
                <div className="cs">
                  This client has no site registered and no website on their business
                  profile. You can still write the pages now — they will be saved as
                  drafts you can review and publish once a site is connected.
                </div>
              )}

              {registerError && <div className="cs">{registerError}</div>}

              {state.siteDomain && (
                <div className="cs">
                  Using <b>{state.siteDomain}</b>
                  {state.siteRegistered
                    ? " — pages will be researched against it and published to it."
                    : " for research only. It is not registered to this client, so publishing will fall back to their registered site if they have one."}{" "}
                  <button
                    type="button"
                    className="ghostbtn"
                    onClick={() => {
                      setRegisterError("");
                      patch({ siteDomain: "", siteRegistered: false, picks: [] });
                    }}
                  >
                    Clear
                  </button>
                </div>
              )}

              {!state.siteDomain && (sites.length > 0 || derivedDomain) && (
                <div className="cs">
                  Or continue without one — the pages are written and held for review,
                  and publishing needs a connected site whenever you come to it.
                </div>
              )}
            </div>
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
