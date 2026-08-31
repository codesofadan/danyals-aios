"use client";

// One client, every concern - the account page the directory never had.
//
// The directory held everything about a client inside modals: profile edits in
// EditClientModal, report access in ClientAccessEditor, the NAP business
// profile buried in a sub-form, and the per-client report grants fetched N+1
// (one request per client, to show ALL clients). This page gives one client
// one URL, and fetches only that client's grants - looking at one account no
// longer costs a request per account on the roster.
//
// The directory's modals stay for quick edits; this is the place a teammate
// can be LINKED to ("look at NorthPeak's setup").

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { TIER_COLOR, type ClientRecord } from "@/lib/data";
import { usd } from "@/lib/format";
import { useClients } from "@/lib/hooks/clients";
import { useClientBusinessProfile } from "@/lib/hooks/clients";
import ClientCredentialCell from "./ClientCredentialCell";
import DetailShell from "@/components/ui/DetailShell";
import QueryGuard from "@/components/ui/QueryGuard";
import EmptyState from "@/components/ui/EmptyState";
import PortalPublishing from "./PortalPublishing";
import { clientReports } from "@/lib/data";

/** THIS client's grants only — the directory's useAllReportGrants issues one
 *  request per client on the whole roster; a detail page needs exactly one. */
function useClientGrants(clientId: string | null) {
  return useQuery({
    queryKey: ["clients", clientId, "report-grants"] as const,
    queryFn: () => api.get<string[]>(`/clients/${clientId}/report-grants`),
    enabled: Boolean(clientId),
  });
}

export default function ClientDetail({ clientId }: { clientId: string }) {
  const clientsQ = useClients();
  const client: ClientRecord | undefined = clientsQ.data?.find((c) => c.id === clientId);
  const grantsQ = useClientGrants(client ? clientId : null);
  const napQ = useClientBusinessProfile(client ? clientId : null);

  if (clientsQ.isError) {
    return (
      <section className="card" style={{ maxWidth: 520, margin: "48px auto", textAlign: "center", padding: 28 }}>
        <div className="ct">Couldn&apos;t load the client</div>
        <div className="cs" style={{ marginTop: 8 }}><Link href="/admin/clients">Back to Clients</Link></div>
      </section>
    );
  }
  if (clientsQ.isLoading) {
    return <div role="status" style={{ padding: 48, textAlign: "center", color: "var(--muted)" }}>Loading client…</div>;
  }
  if (!client) {
    return (
      <section className="card" style={{ maxWidth: 520, margin: "48px auto", textAlign: "center", padding: 28 }}>
        <div className="ct">No client with this id</div>
        {(clientsQ.data?.length ?? 0) === 200 ? (
          <div className="cs" style={{ marginTop: 6 }}>The directory window holds the first 200 clients — this one may sit beyond it.</div>
        ) : null}
        <div className="cs" style={{ marginTop: 8 }}><Link href="/admin/clients">Back to Clients</Link></div>
      </section>
    );
  }

  const granted = new Set(grantsQ.data ?? []);
  const nap = napQ.data ?? null;

  return (
    <DetailShell
      eyebrow="Client"
      title={client.cn}
      statusPill={
        <span
          className="status-pill mut"
          style={{ color: TIER_COLOR[client.tier], borderColor: "currentColor" }}
        >
          {client.tier} · {client.status}
        </span>
      }
      facts={[
        { label: "Industry", value: client.industry || "—" },
        { label: "Since", value: client.since },
        { label: "Sites", value: client.sites },
        { label: "MRR", value: usd(client.mrr) },
        { label: "Renews", value: client.renews || "—" },
        { label: "Contact", value: client.contact?.name || "—" },
      ]}
      actions={
        <>
          <Link className="ghostbtn" href="/admin/audit">
            <span className="material-symbols-rounded">fact_check</span>Audits
          </Link>
          <Link className="ghostbtn" href="/admin/content">
            <span className="material-symbols-rounded">article</span>Content
          </Link>
          <Link className="ghostbtn" href="/admin/wordpress">
            <span className="material-symbols-rounded">language</span>WordPress
          </Link>
        </>
      }
      tabs={[
        { key: "reports", label: "Report access", icon: "lock_open" },
        { key: "nap", label: "Business profile", icon: "storefront" },
        { key: "portal", label: "Portal login", icon: "badge" },
      ]}
    >
      {(tab) => {
        if (tab === "reports") {
          return (
            <QueryGuard queries={[grantsQ]} label="report access" minHeight={120}>
              <section className="card" style={{ padding: "var(--s-7)", maxWidth: 640 }}>
                <div className="cs" style={{ marginBottom: "var(--s-6)" }}>
                  What {client.cn} can see in their portal. Editing stays in the
                  directory&apos;s access editor — this is the honest readout of the live grants.
                </div>
                <div style={{ display: "grid", gap: "var(--s-3)" }}>
                  {clientReports.map((r) => (
                    <div
                      key={r.key}
                      style={{ display: "flex", alignItems: "center", gap: "var(--s-4)", fontSize: "var(--fs-sm)" }}
                    >
                      <span
                        className="material-symbols-rounded"
                        style={{ color: granted.has(r.key) ? "var(--ok)" : "var(--muted-2)", fontSize: 18 }}
                        aria-hidden="true"
                      >
                        {granted.has(r.key) ? "check_circle" : "radio_button_unchecked"}
                      </span>
                      <span style={{ fontWeight: granted.has(r.key) ? 700 : 400 }}>{r.label}</span>
                      <span className="sr-only">{granted.has(r.key) ? "granted" : "not granted"}</span>
                    </div>
                  ))}
                </div>
              </section>
              <PortalPublishing clientId={clientId} clientName={client.cn} />
            </QueryGuard>
          );
        }
        if (tab === "nap") {
          if (napQ.isLoading) {
            return <div role="status" style={{ padding: 32, color: "var(--muted)" }}>Loading business profile…</div>;
          }
          if (!nap) {
            return (
              <EmptyState
                icon="storefront"
                title="No business profile yet"
                hint="The NAP record (name, address, phone) powers citations and local SEO. Add it from the directory's edit form."
              />
            );
          }
          return (
            <section className="card" style={{ padding: "var(--s-7)", maxWidth: 640 }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "var(--s-6)" }}>
                {[
                  ["Business name", nap.businessName],
                  ["Phone", nap.phone],
                  ["Website", nap.websiteUrl],
                  ["Address", [nap.addressLine1, nap.addressLine2, nap.city, nap.region, nap.postalCode].filter(Boolean).join(", ")],
                  ["Primary category", nap.primaryCategory],
                  ["Market", nap.market],
                ].map(([label, value]) => (
                  <div key={String(label)}>
                    <div style={{ fontSize: "var(--fs-xs)", color: "var(--muted)" }}>{label}</div>
                    <div style={{ fontSize: "var(--fs-sm)", fontWeight: 600 }}>{value || "—"}</div>
                  </div>
                ))}
              </div>
              {nap.description ? (
                <p className="cs" style={{ marginTop: "var(--s-6)", maxWidth: 560 }}>{nap.description}</p>
              ) : null}
            </section>
          );
        }
        return (
          <section className="card" style={{ padding: "var(--s-7)", maxWidth: 560 }}>
            <div className="cs" style={{ marginBottom: "var(--s-5)" }}>
              The portal identity this client signs in with. The password IS
              recoverable — provisioning seals an encrypted copy beside the one-way
              hash — so reveal it below rather than issuing a new one.
            </div>
            <div style={{ marginBottom: "var(--s-5)" }}>
              <ClientCredentialCell client={client} />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "var(--s-6)" }}>
              <div>
                <div style={{ fontSize: "var(--fs-xs)", color: "var(--muted)" }}>Login</div>
                <div style={{ fontSize: "var(--fs-sm)", fontWeight: 700 }}>
                  {client.portal?.admin || "— not provisioned —"}
                </div>
              </div>
              <div>
                <div style={{ fontSize: "var(--fs-xs)", color: "var(--muted)" }}>Seats</div>
                <div style={{ fontSize: "var(--fs-sm)", fontWeight: 700 }}>{client.portal?.seats ?? 0}</div>
              </div>
              <div>
                <div style={{ fontSize: "var(--fs-xs)", color: "var(--muted)" }}>Last login</div>
                <div style={{ fontSize: "var(--fs-sm)", fontWeight: 700 }}>{client.portal?.lastLogin || "—"}</div>
              </div>
            </div>
          </section>
        );
      }}
    </DetailShell>
  );
}
