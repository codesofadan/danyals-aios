"use client";

import { useMemo, useState } from "react";
import {
  clientReports, REPORT_GROUP_COLOR, TIER_COLOR,
  type ClientRecord, type SubStatus, type NewClient,
} from "@/lib/data";
import {
  useClients, useAllReportGrants, useCreateClient, useSaveGrants,
  useUpdateClient, useDeleteClient, type ClientUpdate,
} from "@/lib/hooks/clients";
import CopyButton from "@/components/CopyButton";
import AddClientWizard from "./AddClientWizard";
import ClientAccessEditor from "./ClientAccessEditor";
import EditClientModal from "./EditClientModal";

// Centred muted state message (loading / error / empty), self-styled so it never
// depends on a class that might not exist.
const stateStyle: React.CSSProperties = {
  padding: "2.5rem 1rem", textAlign: "center", color: "var(--muted)",
};

type Mode = "info" | "portal" | "access";

const STATUS_META: Record<SubStatus, { label: string; cls: string }> = {
  active: { label: "Active", cls: "ok" },
  trial: { label: "Trial", cls: "info" },
  past_due: { label: "Past due", cls: "warn" },
  paused: { label: "Paused", cls: "mut" },
};

const REPORT_BY_KEY = new Map(clientReports.map((r) => [r.key, r] as const));

function ContactCell({ c }: { c: ClientRecord["contact"] }) {
  return (
    <div className="cd-contact">
      <span className="av" style={{ background: c.c }}>{c.init}</span>
      <div className="cd-cmeta">
        <div className="cd-cname">{c.name}</div>
        <div className="cd-crole">{c.role}</div>
      </div>
    </div>
  );
}

function PassCell({ pass }: { pass: string }) {
  // Admin credentials are shown by default across the admin dashboard (the admin owns
  // these client portal logins and shares them manually); the eye toggle still hides.
  const [shown, setShown] = useState(true);
  return (
    <div className="pass-cell">
      <code className="pass-val">{shown ? pass : "•".repeat(pass.length)}</code>
      <button
        className="pass-eye"
        onClick={() => setShown((s) => !s)}
        aria-label={shown ? "Hide admin password" : "Reveal admin password"}
        title={shown ? "Hide" : "Reveal"}
      >
        <span className="material-symbols-rounded">{shown ? "visibility_off" : "visibility"}</span>
      </button>
      <CopyButton value={pass} label="admin password" />
    </div>
  );
}

// Granted-report chips (colour-coded by area), truncated with a "+N".
function ReportChips({ keys }: { keys: string[] }) {
  if (keys.length === 0) {
    return <span className="cd-noaccess">No reports shared</span>;
  }
  const shown = keys.slice(0, 4);
  const extra = keys.length - shown.length;
  return (
    <div className="cd-chips">
      {shown.map((k) => {
        const r = REPORT_BY_KEY.get(k);
        if (!r) return null;
        const c = REPORT_GROUP_COLOR[r.group];
        return (
          <span key={k} className="cd-chip" style={{ color: c, borderColor: c }}>
            <span className="material-symbols-rounded">{r.icon}</span>{r.short}
          </span>
        );
      })}
      {extra > 0 && <span className="cd-chip more">+{extra}</span>}
    </div>
  );
}

export default function ClientDirectory() {
  const [mode, setMode] = useState<Mode>("info");
  const clientsQ = useClients();
  const clients = useMemo(() => clientsQ.data ?? [], [clientsQ.data]);
  const { grants } = useAllReportGrants(clients.map((c) => c.id));
  const createClient = useCreateClient();
  const saveGrants = useSaveGrants();
  const updateClient = useUpdateClient();
  const deleteClient = useDeleteClient();
  const [addOpen, setAddOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [infoEditId, setInfoEditId] = useState<string | null>(null);
  const [portalWarning, setPortalWarning] = useState<string | null>(null);

  const editClient = useMemo(() => clients.find((c) => c.id === editId) ?? null, [clients, editId]);
  const infoEditClient = useMemo(() => clients.find((c) => c.id === infoEditId) ?? null, [clients, infoEditId]);

  function handleUpdateClient(changes: ClientUpdate) {
    if (!infoEditId) return;
    updateClient.mutate({ id: infoEditId, changes }, { onSuccess: () => setInfoEditId(null) });
  }

  function handleDeleteClient(id: string, name: string) {
    if (deleteClient.isPending) return;
    if (!window.confirm(`Delete ${name}? This permanently removes the client account and can't be undone.`)) return;
    deleteClient.mutate(id);
  }

  function handleAddClient(input: NewClient) {
    createClient.mutate(input, {
      onSuccess: (created) => {
        setAddOpen(false);
        setMode("access");
        if (created.portalWarning) {
          setPortalWarning(created.portalWarning);
          window.setTimeout(() => setPortalWarning(null), 6000);
        }
      },
    });
  }

  function handleSaveGrants(reports: string[]) {
    if (!editId) return;
    saveGrants.mutate({ clientId: editId, reports }, { onSuccess: () => setEditId(null) });
  }

  const subtitle =
    mode === "info" ? "Account details, primary contact & subscription"
    : mode === "portal" ? "Portal logins & admin credentials · handle with care"
    : "What each client is allowed to see — charts, graphs & reports";

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Client Directory</div>
          <div className="cs">{subtitle}</div>
        </div>
        <div className="tools">
          <div className="seg" role="tablist" aria-label="Directory view">
            <button role="tab" aria-selected={mode === "info"} className={mode === "info" ? "on" : undefined} onClick={() => setMode("info")}>
              Client Info
            </button>
            <button role="tab" aria-selected={mode === "portal"} className={mode === "portal" ? "on" : undefined} onClick={() => setMode("portal")}>
              Portal Access
            </button>
            <button role="tab" aria-selected={mode === "access"} className={mode === "access" ? "on" : undefined} onClick={() => setMode("access")}>
              Report Access
            </button>
          </div>
          <button className="primary-btn" onClick={() => setAddOpen(true)}>
            <span className="material-symbols-rounded">person_add</span>Add client
          </button>
        </div>
      </div>

      {portalWarning && (
        <div className="login-error" role="alert">
          <span className="material-symbols-rounded">warning</span>{portalWarning}
        </div>
      )}
      {createClient.error instanceof Error && (
        <div className="login-error" role="alert">
          <span className="material-symbols-rounded">error</span>
          Couldn&apos;t create the client — {createClient.error.message}
        </div>
      )}
      {deleteClient.error instanceof Error && (
        <div className="login-error" role="alert">
          <span className="material-symbols-rounded">error</span>
          Couldn&apos;t delete the client — {deleteClient.error.message}
        </div>
      )}
      {mode === "portal" && (
        <div className="sec-note">
          <span className="material-symbols-rounded">lock</span>
          Admin credentials are shown by default; use the eye to hide one. Copy actions are recorded in the activity log.
        </div>
      )}
      {mode === "access" && (
        <div className="sec-note">
          <span className="material-symbols-rounded">visibility</span>
          A client sees only the reports granted here — anything else is hidden and its data is never sent. Update it any time with Manage.
        </div>
      )}

      <div className="cd-wrap">
        {clientsQ.isLoading ? (
          <div style={stateStyle}>Loading clients…</div>
        ) : clientsQ.isError ? (
          <div style={stateStyle}>Couldn&apos;t load clients — {(clientsQ.error as Error)?.message ?? "try again"}.</div>
        ) : clients.length === 0 ? (
          <div style={stateStyle}>No clients yet — add your first client to get started.</div>
        ) : (
        <>
        {mode === "info" && (
          <table className="cd-table">
            <thead>
              <tr>
                <th>Client</th>
                <th>Primary contact</th>
                <th>Subscription</th>
                <th className="num">Sites</th>
                <th className="num">MRR</th>
                <th className="num">Actions</th>
              </tr>
            </thead>
            <tbody>
              {clients.map((c) => {
                const sm = STATUS_META[c.status] ?? { label: c.status, cls: "mut" };
                return (
                  <tr key={c.id}>
                    <td>
                      <div className="cd-client">
                        <div className="cd-name">{c.cn}</div>
                        <div className="cd-meta">{c.industry} · since {c.since}</div>
                      </div>
                    </td>
                    <td><ContactCell c={c.contact} /></td>
                    <td>
                      <div className="cd-sub">
                        <span className="tier-chip sm" style={{ color: TIER_COLOR[c.tier], borderColor: TIER_COLOR[c.tier] }}>{c.tier}</span>
                        <span className={`status-pill ${sm.cls}`}>{sm.label}</span>
                        <span className="cd-renew">Renews {c.renews}</span>
                      </div>
                    </td>
                    <td className="num">{c.sites}</td>
                    <td className="num mrr">{c.mrr ? `$${c.mrr.toLocaleString()}` : "—"}</td>
                    <td className="num">
                      <div className="cd-rowactions">
                        <button className="cd-manage" onClick={() => setInfoEditId(c.id)} title={`Edit ${c.cn}`}>
                          <span className="material-symbols-rounded">edit</span>Edit
                        </button>
                        <button
                          className="cd-manage danger"
                          onClick={() => handleDeleteClient(c.id, c.cn)}
                          disabled={deleteClient.isPending}
                          title={`Delete ${c.cn}`}
                        >
                          <span className="material-symbols-rounded">delete</span>Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        {mode === "portal" && (
          <table className="cd-table">
            <thead>
              <tr>
                <th>Client</th>
                <th>Admin login</th>
                <th>Admin pass</th>
                <th className="num">Seats</th>
                <th>2FA</th>
                <th>Last login</th>
              </tr>
            </thead>
            <tbody>
              {clients.map((c) => (
                <tr key={c.id}>
                  <td>
                    <div className="cd-client">
                      <div className="cd-name">{c.cn}</div>
                      <div className="cd-meta">{c.contact.name}</div>
                    </div>
                  </td>
                  <td>
                    <div className="pass-cell">
                      <code className="login-val">{c.portal.admin}</code>
                      <CopyButton value={c.portal.admin} label="admin login" />
                    </div>
                  </td>
                  <td><PassCell pass={c.portal.pass} /></td>
                  <td className="num">{c.portal.seats}</td>
                  <td>
                    {c.portal.twoFA ? (
                      <span className="fa-badge on"><span className="material-symbols-rounded">verified_user</span>On</span>
                    ) : (
                      <span className="fa-badge off"><span className="material-symbols-rounded">gpp_maybe</span>Off</span>
                    )}
                  </td>
                  <td className="last">{c.portal.lastLogin}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {mode === "access" && (
          <table className="cd-table">
            <thead>
              <tr>
                <th>Client</th>
                <th>Reports the client can see</th>
                <th className="num">Visible</th>
                <th className="num">Manage</th>
              </tr>
            </thead>
            <tbody>
              {clients.map((c) => {
                const keys = grants[c.id] ?? [];
                return (
                  <tr key={c.id}>
                    <td>
                      <div className="cd-client">
                        <div className="cd-name">{c.cn}</div>
                        <div className="cd-meta">{c.contact.name}</div>
                      </div>
                    </td>
                    <td><ReportChips keys={keys} /></td>
                    <td className="num">{keys.length} / {clientReports.length}</td>
                    <td className="num">
                      <button className="cd-manage" onClick={() => setEditId(c.id)}>
                        <span className="material-symbols-rounded">tune</span>Manage
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        </>
        )}
      </div>

      <div className="cd-foot">
        <span>{clients.length} accounts</span>
        <span className="cd-foot-hint">
          {mode === "access"
            ? "Grant or revoke report visibility per client — updates apply instantly."
            : `Toggle to ${mode === "info" ? "Portal Access or Report Access" : "Client Info"} for ${mode === "info" ? "credentials & visibility" : "account details"}`}
        </span>
      </div>

      {addOpen && <AddClientWizard onClose={() => setAddOpen(false)} onAdd={handleAddClient} />}
      {editClient && (
        <ClientAccessEditor
          client={editClient}
          current={grants[editClient.id] ?? []}
          onClose={() => setEditId(null)}
          onSave={handleSaveGrants}
        />
      )}
      {infoEditClient && (
        <EditClientModal
          client={infoEditClient}
          busy={updateClient.isPending}
          error={updateClient.error instanceof Error ? updateClient.error.message : null}
          onClose={() => setInfoEditId(null)}
          onSave={handleUpdateClient}
        />
      )}
    </section>
  );
}
