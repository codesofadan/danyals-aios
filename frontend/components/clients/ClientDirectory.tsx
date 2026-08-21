"use client";

import { useMemo, useState } from "react";
import {
  TIER_COLOR,
  type ClientRecord, type SubStatus,
} from "@/lib/data";
import {
  useClients, useCreateClient,
  useUpdateClient, useDeleteClient, type ClientUpdate, type NewClientInput,
} from "@/lib/hooks/clients";
import AddClientWizard from "./AddClientWizard";
import EditClientModal from "./EditClientModal";

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

  function handleAddClient(input: NewClientInput) {
    createClient.mutate(input, {
      onSuccess: () => {
        setAddOpen(false);
      },
    });
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
                        <div className="cd-name">{c.cn}</div>
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
        <span>{clients.length} accounts</span>
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
    </section>
  );
}
