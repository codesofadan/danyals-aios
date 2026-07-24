"use client";

import { useState } from "react";
import { useCreateInvoice, useFinalizeInvoice, type InvoiceKind } from "@/lib/hooks/tools";
import { ActionCard, ClientSelect, PermNote, ToolActionResult } from "./shared";
import type { ToolActionProps } from "./registry";

/** Billing — open a DRAFT invoice with one line (POST /billing/invoices), then
 *  issue it (POST .../{number}/finalize). Records only: no gateway charges a card.
 *  Finance-sensitive, so both steps need owner / admin. */
export default function BillingActions({ accent }: ToolActionProps) {
  const [clientId, setClientId] = useState("");
  const [kind, setKind] = useState<InvoiceKind>("retainer");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const create = useCreateInvoice();
  const finalize = useFinalizeInvoice();

  const amountNum = Number(amount);
  const created = create.data ?? null;
  const canCreate =
    !!clientId && description.trim().length > 1 && amount !== "" && amountNum > 0 && !create.isPending;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canCreate) return;
    create.mutate(
      {
        client_id: clientId,
        kind,
        currency: "USD",
        lines: [{ description: description.trim(), quantity: 1, unit_amount: amountNum }],
      },
      { onSuccess: () => { setDescription(""); setAmount(""); } },
    );
  };

  return (
    <ActionCard
      title="Draft an invoice"
      subtitle="Open a draft with one line, then issue it to the client."
      icon="payments"
      accent={accent}
    >
      <form onSubmit={submit}>
        <div className="fld-row">
          <ClientSelect value={clientId} onChange={setClientId} />
          <div className="fld">
            <label>Kind</label>
            <select value={kind} onChange={(e) => setKind(e.target.value as InvoiceKind)}>
              <option value="retainer">Retainer</option>
              <option value="one_off">One-off</option>
            </select>
          </div>
        </div>
        <div className="fld">
          <label>Line description</label>
          <input
            placeholder="Monthly SEO retainer — July"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div className="fld">
          <label>Amount (USD)</label>
          <input
            type="number"
            min="0"
            step="0.01"
            placeholder="1490"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </div>
        <button type="submit" className="primary-btn wide" disabled={!canCreate}>
          <span className="material-symbols-rounded">receipt_long</span>
          {create.isPending ? "Drafting…" : "Draft invoice"}
        </button>
      </form>

      {created && created.status === "draft" && (
        <div className="fld" style={{ marginTop: 14 }}>
          <label>Issue {created.number} (freezes it — corrections are void + reissue)</label>
          <button
            type="button"
            className="primary-btn"
            onClick={() => finalize.mutate(created.number)}
            disabled={finalize.isPending}
          >
            <span className="material-symbols-rounded">send</span>
            {finalize.isPending ? "Issuing…" : "Issue invoice"}
          </button>
        </div>
      )}

      <ToolActionResult
        error={create.error ?? finalize.error}
        success={
          finalize.isSuccess
            ? `Invoice ${finalize.data.number} issued.`
            : create.isSuccess && created
              ? `Draft ${created.number} created. Issue it to send it to the client.`
              : null
        }
      />
      <PermNote>Billing is finance-scoped — drafting and issuing need owner / admin access.</PermNote>
    </ActionCard>
  );
}
