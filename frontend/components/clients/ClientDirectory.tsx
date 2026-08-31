"use client";

import Link from "next/link";

import { useMemo, useState } from "react";
import {
  TIER_COLOR,
  type ClientRecord, type SubStatus,
} from "@/lib/data";
import {
  useClients, useCreateClient,
  useUpdateClient, useDeleteClient, useAllReportGrants, useSaveGrants,
  type ClientUpdate, type NewClientInput,
} from "@/lib/hooks/clients";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useToast, describeError } from "@/components/ui/Toast";
import AddClientWizard from "./AddClientWizard";
import EditClientModal from "./EditClientModal";
import ClientAccessEditor from "./ClientAccessEditor";
import ClientCredentialCell from "./ClientCredentialCell";
import CopyButton from "@/components/CopyButton";

// Centred muted state message (loading / error / empty), self-styled so it never
// depends on a class that might not exist.
const stateStyle: React.CSSProperties = {
  padding: "2.5rem 1rem", textAlign: "center", color: "var(--muted)",
};

const STATUS_META: Record<SubStatus, { label: string; cls: string }> = {
  active: { label: "Active", cls: "ok" },
  trial: { label: "Trial", cls: "info" },
  past_due: { label: "Past due", cls: "warn" },
  paused: { label: "Paused", cls: "mut" },
};

function ContactCell({ c }: { c: ClientRecord["contact"] }) {
  return (
    <div className="cd-contact">
      <span className="av" style={{ background: c.c }}>{c.init}</span>
      <div className="cd-cmeta">
        <div className="cd-cname">{c.name}</div>
        {c.role && <div className="cd-crole">{c.role}</div>}
      </div>
    </div>
  );
}

export default function ClientDirectory() {
  const clientsQ = useClients();
  const clients = useMemo(() => clientsQ.data ?? [], [clientsQ.data]);
  const createClient = useCreateClient();
  const updateClient = useUpdateClient();
  const deleteClient = useDeleteClient();
  const [addOpen, setAddOpen] = useState(false);
  const [infoEditId, setInfoEditId] = useState<string | null>(null);
  const [accessId, setAccessId] = useState<string | null>(null);
  const [portalWarning, setPortalWarning] = useState<string | null>(null);
  // The credentials the SERVER accepted, shown once creation has actually happened.
  // The wizard used to print a locally generated pair before the login was
  // provisioned, so an operator could copy and send a password that was never stored.
  const [newLogin, setNewLogin] = useState<{ cn: string; username: string; password: string } | null>(null);

  // Which reports each client may see. Read for the whole table so the count is
  // visible per row: before this screen existed, EVERY client sat at 0 and nothing
  // in the product said so - the client dashboard just rendered as locked forever.
  const clientIds = useMemo(() => clients.map((c) => c.id), [clients]);
  const grantsQ = useAllReportGrants(clientIds);
  const saveGrants = useSaveGrants();

  const infoEditClient = useMemo(() => clients.find((c) => c.id === infoEditId) ?? null, [clients, infoEditId]);
  const accessClient = useMemo(() => clients.find((c) => c.id === accessId) ?? null, [clients, accessId]);

  function handleUpdateClient(changes: ClientUpdate) {
    if (!infoEditId) return;
    updateClient.mutate({ id: infoEditId, changes }, { onSuccess: () => setInfoEditId(null) });
  }

  // Deleting a client is the directory's one irreversible action: the account,
  // its portal logins and its grant rows go with it. window.confirm could not
  // say that, could not demand typing, and never answered whether it worked.
  const [deleting, setDeleting] = useState<{ id: string; name: string } | null>(null);
  const toast = useToast();

  function handleDeleteClient(id: string, name: string) {
    if (deleteClient.isPending) return;
    setDeleting({ id, name });
  }

  function confirmDelete() {
    if (!deleting) return;
    deleteClient.mutate(deleting.id, {
      onSuccess: () => { toast.success("Client deleted", `${deleting.name} and its portal access are gone.`); setDeleting(null); },
      onError: (e: unknown) => { toast.error("Couldn't delete the client", describeError(e)); setDeleting(null); },
    });
  }

  function handleAddClient(input: NewClientInput) {
    createClient.mutate(input, {
      onSuccess: (created) => {
        setAddOpen(false);
        // The client row is created even when provisioning its portal LOGIN fails
        // (a duplicate email, most often). That used to be swallowed: the mutation
        // returned a portalWarning and this callback ignored it, so the operator saw
        // an unqualified success for an account nobody could sign in to.
        setPortalWarning(created.portalWarning ?? null);
        setNewLogin(
          created.portalLogin
            ? { cn: created.cn, username: created.portalLogin.username, password: created.portalLogin.password }
            : null,
        );
      },
    });
  }

  function handleSaveGrants(reports: string[]) {
    if (!accessClient) return;
    saveGrants.mutate(
      { clientId: accessClient.id, reports },
      { onSuccess: () => setAccessId(null) },
    );
  }

  const subtitle = "Account details, primary contact & subscription";

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Client Directory</div>
          <div className="cs">{subtitle}</div>
        </div>
        <div className="tools">
          <button className="primary-btn" onClick={() => setAddOpen(true)}>
            <span className="material-symbols-rounded">person_add</span>Add client
          </button>
        </div>
      </div>

      {createClient.error instanceof Error && (
        <div className="login-error" role="alert">
          <span className="material-symbols-rounded">error</span>
          Couldn&apos;t create the client — {createClient.error.message}
        </div>
      )}
      {newLogin && (
        <div className="wiz-creds" role="status" style={{ margin: "0 0 var(--s-5)" }}>
          <div className="wiz-creds-h">
            <span className="material-symbols-rounded">key</span>
            <div>
              <div className="wiz-creds-t">{newLogin.cn} &mdash; portal login created</div>
              <div className="wiz-creds-s">
                Send these to the client. They are stored, not just shown: you can read
                them back any time from <b>Show login</b> on the client&apos;s row.
              </div>
            </div>
          </div>
          <div className="wiz-cred-row">
            <span className="wiz-cred-k">Username</span>
            <code className="wiz-cred-v">{newLogin.username}</code>
            <CopyButton value={newLogin.username} label="portal username" />
          </div>
          <div className="wiz-cred-row">
            <span className="wiz-cred-k">Password</span>
            <code className="wiz-cred-v">{newLogin.password}</code>
            <CopyButton value={newLogin.password} label="portal password" />
          </div>
          <div className="modal-f" style={{ marginTop: "var(--s-4)" }}>
            <button type="button" className="ghostbtn" onClick={() => setNewLogin(null)}>Done</button>
          </div>
        </div>
      )}
      {portalWarning && (
        <div className="login-error" role="alert">
          <span className="material-symbols-rounded">warning</span>
          {portalWarning}
          <button type="button" className="ghostbtn" onClick={() => setPortalWarning(null)}>Dismiss</button>
        </div>
      )}
      {saveGrants.error instanceof Error && (
        <div className="login-error" role="alert">
          <span className="material-symbols-rounded">error</span>
          Couldn&apos;t save report access — {saveGrants.error.message}
        </div>
      )}
      {grantsQ.isError && (
        <div className="login-error" role="alert">
          <span className="material-symbols-rounded">error</span>
          Couldn&apos;t load report access — the per-client counts below may be wrong.
        </div>
      )}
      {deleteClient.error instanceof Error && (
        <div className="login-error" role="alert">
          <span className="material-symbols-rounded">error</span>
          Couldn&apos;t delete the client — {deleteClient.error.message}
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
          <table className="cd-table">
            <thead>
              <tr>
                <th>Client</th>
                <th>Primary contact</th>
                <th>Subscription</th>
                <th>Contact email</th>
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
                        <div className="cd-name"><Link href={`/admin/clients/${c.id}`} title={`Open ${c.cn} in full`}>{c.cn}</Link></div>
                        <div className="cd-meta">{c.industry}{c.since ? ` · since ${c.since}` : ""}</div>
                      </div>
                    </td>
                    <td><ContactCell c={c.contact} /></td>
                    <td>
                      <div className="cd-sub">
                        <span className="tier-chip sm" style={{ color: TIER_COLOR[c.tier], borderColor: TIER_COLOR[c.tier] }}>{c.tier}</span>
                        <span className={`status-pill ${sm.cls}`}>{sm.label}</span>
                        {c.renews && <span className="cd-renew">Renews {c.renews}</span>}
                      </div>
                    </td>
                    <td>{c.contact.email}</td>
                    <td className="num">
                      <div className="cd-rowactions">
                        <button className="cd-manage" onClick={() => setInfoEditId(c.id)} title={`Edit ${c.cn}`}>
                          <span className="material-symbols-rounded">edit</span>Edit
                        </button>
                        <button
                          className="cd-manage"
                          onClick={() => setAccessId(c.id)}
                          // Opening before the grants land would show an empty set as
                          // the client's CURRENT access, and saving would wipe it.
                          disabled={grantsQ.isLoading}
                          title={`Choose which reports ${c.cn} can see`}
                        >
                          <span className="material-symbols-rounded">visibility</span>
                          Reports
                          <span className="cd-grantcount">{(grantsQ.grants[c.id] ?? []).length}</span>
                        </button>
                        <ClientCredentialCell client={c} />
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
      </div>

      <div className="cd-foot">
        <span>{clients.length} accounts{clients.length === 200 ? " (first 200 — the server window is full)" : ""}</span>
        <span className="cd-foot-hint">Account details, primary contact &amp; subscription for every client.</span>
      </div>

      {addOpen && <AddClientWizard onClose={() => setAddOpen(false)} onAdd={handleAddClient} />}
      {infoEditClient && (
        <EditClientModal
          client={infoEditClient}
          busy={updateClient.isPending}
          error={updateClient.error instanceof Error ? updateClient.error.message : null}
          onClose={() => setInfoEditId(null)}
          onSave={handleUpdateClient}
        />
      )}
      {accessClient && (
        <ClientAccessEditor
          client={accessClient}
          current={grantsQ.grants[accessClient.id] ?? []}
          onClose={() => setAccessId(null)}
          onSave={handleSaveGrants}
        />
      )}
      <ConfirmDialog
        open={deleting !== null}
        title={`Delete ${deleting?.name ?? "this client"}?`}
        body="The client account is permanently removed - its portal logins stop working and its report grants are deleted with it."
        reassurance="Completed audits and published content remain in their own ledgers."
        confirmLabel="Delete client"
        tone="danger"
        typeToConfirm="DELETE"
        pending={deleteClient.isPending}
        onCancel={() => setDeleting(null)}
        onConfirm={confirmDelete}
      />
    </section>
  );
}
