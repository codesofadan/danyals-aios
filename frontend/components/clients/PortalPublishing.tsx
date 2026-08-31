"use client";

// ============================================================
// AIOS · portal publishing — the decision to put a document in front of a client.
//
// Every producer used to write documents straight to `ready`, and the portal shows
// any ready row whose grant key the client holds. So an audit PDF was in front of the
// client the moment its job finished: no review, and no way to hold one back short of
// revoking the whole report grant, which removes every other document of that kind at
// the same time.
//
// Documents are produced as `pending_review` now. This is where a lead releases one.
// The gate itself is in the portal VIEW (0116), not in a response model — a row
// awaiting review is never selected for a client by any route, present or future.
// ============================================================

import { useState } from "react";
import {
  useClientDeliverables,
  useSetDeliverablePublished,
  type StaffDeliverable,
} from "@/lib/hooks/clients";

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function Row({
  doc,
  clientId,
  onError,
}: {
  doc: StaffDeliverable;
  clientId: string;
  onError: (message: string) => void;
}) {
  const setPublished = useSetDeliverablePublished(clientId);
  const live = doc.status === "ready";
  const generating = doc.status === "generating";

  return (
    <div
      style={{
        display: "flex", alignItems: "center", gap: "var(--s-4)",
        padding: "10px 0", borderTop: "1px solid var(--line)",
      }}
    >
      <span className="material-symbols-rounded" style={{ fontSize: 20, opacity: 0.7 }} aria-hidden>
        {doc.icon || "description"}
      </span>
      <span style={{ flex: 1, minWidth: 0 }}>
        <span style={{ display: "block", fontWeight: 700, fontSize: "var(--fs-sm)" }}>
          {doc.title}
        </span>
        <span className="cs">
          {doc.kind}
          {doc.period ? ` · ${doc.period}` : ""}
          {live && doc.issuedAt ? ` · shared ${when(doc.issuedAt)}` : ""}
          {/* A document with no stored file cannot be released: the portal would
              render a download that 404s. Say so where the button would be. */}
          {!doc.hasFile && !generating ? " · no file stored" : ""}
        </span>
      </span>

      <span className={`status-pill ${live ? "ok" : generating ? "info" : "warn"}`}>
        {live ? "Shared" : generating ? "Producing" : "Awaiting review"}
      </span>

      {!generating && (
        <button
          type="button"
          className={live ? "ghostbtn" : "primary-btn"}
          disabled={setPublished.isPending || (!live && !doc.hasFile)}
          title={
            !live && !doc.hasFile
              ? "This document has no stored file, so the client would get a broken download."
              : undefined
          }
          onClick={() =>
            setPublished.mutate(
              { id: doc.id, publish: !live },
              {
                onError: (err: unknown) =>
                  onError(
                    err instanceof Error ? err.message : "That could not be changed.",
                  ),
              },
            )
          }
        >
          {live ? "Withdraw" : "Share with client"}
        </button>
      )}
    </div>
  );
}

export default function PortalPublishing({
  clientId,
  clientName,
}: {
  clientId: string;
  clientName: string;
}) {
  const docsQ = useClientDeliverables(clientId);
  const [error, setError] = useState("");
  const docs = docsQ.data ?? [];
  const waiting = docs.filter((d) => d.status === "pending_review").length;

  return (
    <section className="card" style={{ padding: "var(--s-7)", maxWidth: 640, marginTop: "var(--s-6)" }}>
      <div className="ct">Documents</div>
      <div className="cs" style={{ margin: "4px 0 var(--s-5)" }}>
        {waiting > 0
          ? `${waiting} document${waiting === 1 ? "" : "s"} waiting for your review. Nothing here reaches ${clientName} until you share it.`
          : `Everything produced for ${clientName}. Nothing reaches their portal until you share it.`}
      </div>

      {error && (
        <div style={{ fontSize: 13, color: "var(--crit)", fontWeight: 600, marginBottom: 8 }}>
          {error}
        </div>
      )}

      {docsQ.isLoading ? (
        <div className="cs">Loading documents…</div>
      ) : docsQ.isError ? (
        // A failed fetch is not an empty library. Saying "no documents" here would
        // tell an operator nothing has been produced for a client who may have a
        // dozen waiting.
        <div style={{ fontSize: 13, color: "var(--crit)", fontWeight: 600 }}>
          Couldn&rsquo;t load this client&rsquo;s documents.{" "}
          <button type="button" className="ghostbtn" onClick={() => void docsQ.refetch()}>
            Retry
          </button>
        </div>
      ) : docs.length === 0 ? (
        <div className="cs">
          No documents yet. Audits, reports and published content appear here as they are
          produced, for you to review before the client sees them.
        </div>
      ) : (
        <div>
          {docs.map((d) => (
            <Row key={d.id} doc={d} clientId={clientId} onError={setError} />
          ))}
        </div>
      )}
    </section>
  );
}
