"use client";

// TEAM REQUESTS - a member asking the leads for something.
//
// The client portal has had this since 0024; the team portal had nothing. A member who
// needed an access grant, a tool switched on, a deadline moved or a decision made had
// no route inside the product, so the ask went to chat - where it had no record, no
// owner and no status, and "did anyone action that?" had no answer.
//
// The list is the member's OWN requests only, and that is enforced in SQL by the
// `team_requests` view (filtered to auth.uid()), not by this component asking nicely.

import { useState } from "react";
import QueryGuard from "@/components/ui/QueryGuard";
import { useToast, describeError } from "@/components/ui/Toast";
import {
  useCreateTeamRequest,
  useTeamRequests,
  type TeamRequestKind,
} from "@/lib/hooks/portal";

const KINDS: { key: TeamRequestKind; label: string; hint: string }[] = [
  { key: "Access", label: "Access", hint: "A client, a tool or a permission you need" },
  { key: "Support", label: "Support", hint: "Something is broken or you are stuck" },
  { key: "Feature", label: "Feature", hint: "Something the platform should be able to do" },
  { key: "Report", label: "Report", hint: "A report or export you need produced" },
  { key: "Billing", label: "Billing", hint: "Anything about spend, budget or invoicing" },
];

const STATUS_CLS: Record<string, string> = {
  open: "info",
  pending: "warn",
  resolved: "ok",
};

export default function TeamRequests() {
  const listQ = useTeamRequests();
  const create = useCreateTeamRequest();
  const toast = useToast();

  const [kind, setKind] = useState<TeamRequestKind>("Access");
  const [subject, setSubject] = useState("");
  const [detail, setDetail] = useState("");

  const rows = listQ.data ?? [];
  const canSend = subject.trim().length >= 3 && !create.isPending;

  const submit = () => {
    if (!canSend) return;
    create.mutate(
      { kind, subject: subject.trim(), detail: detail.trim() },
      {
        onSuccess: (r) => {
          setSubject("");
          setDetail("");
          toast.success(
            `Request ${r.code} sent`,
            "The leads have been emailed. You'll see the reply here.",
          );
        },
        onError: (e: unknown) => toast.error("Couldn't send the request", describeError(e)),
      },
    );
  };

  return (
    <div className="tw portal" style={{ display: "grid", gap: 16 }}>
      <section className="card" style={{ padding: "var(--s-7)" }}>
        <div className="ct">Ask the team leads</div>
        <div className="cs" style={{ margin: "4px 0 14px", lineHeight: 1.6 }}>
          Anything you need from the agency side — an access grant, a tool switched on, a
          deadline moved, a decision. It reaches the leads by email and in-app, and stays
          here with a status until it is answered.
        </div>

        <div className="fld">
          <label htmlFor="tr-kind">What kind of request?</label>
          <select
            id="tr-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as TeamRequestKind)}
            style={{ maxWidth: 320 }}
          >
            {KINDS.map((k) => (
              <option key={k.key} value={k.key}>
                {k.label} — {k.hint}
              </option>
            ))}
          </select>
        </div>

        <div className="fld" style={{ marginTop: 12 }}>
          <label htmlFor="tr-subject">
            Subject <span style={{ color: "var(--crit)" }}>*</span>
          </label>
          <input
            id="tr-subject"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="Access to the Spotino account"
            maxLength={200}
          />
          <div className="fld-hint">
            {subject.trim().length >= 3
              ? "One line the lead can act on."
              : "At least a few words — a lead triages on this line alone."}
          </div>
        </div>

        <div className="fld" style={{ marginTop: 12 }}>
          <label htmlFor="tr-detail">Detail (optional)</label>
          <textarea
            id="tr-detail"
            rows={4}
            value={detail}
            onChange={(e) => setDetail(e.target.value)}
            placeholder="What you need, why, and by when if it matters."
            maxLength={4000}
          />
        </div>

        <button
          type="button"
          className="primary-btn"
          onClick={submit}
          disabled={!canSend}
          style={{ marginTop: 14 }}
        >
          <span className="material-symbols-rounded">send</span>
          {create.isPending ? "Sending…" : "Send request"}
        </button>
      </section>

      <section className="card" style={{ padding: "var(--s-7)" }}>
        <div className="ct">Your requests</div>
        <QueryGuard queries={[listQ]} label="your requests" minHeight={140}>
          {
            rows.length === 0 ? (
              <div className="pt-empty">
                <span className="material-symbols-rounded">forum</span>
                <div className="pt-empty-t">Nothing asked yet</div>
                <div className="pt-empty-s">
                  Requests you raise appear here with their status and the lead&apos;s reply.
                </div>
              </div>
            ) : (
              <div className="tbl-wrap" style={{ marginTop: 10 }}>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Request</th>
                      <th>Type</th>
                      <th>Status</th>
                      <th>Reply</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.code}>
                        <td>
                          <strong>{r.subject}</strong>
                          <div className="cs">
                            {r.code}
                            {r.opened_at ? ` · ${new Date(r.opened_at).toLocaleDateString()}` : ""}
                          </div>
                        </td>
                        <td>{r.kind}</td>
                        <td>
                          <span className={`status-pill ${STATUS_CLS[r.status] ?? "mut"}`}>
                            {r.status}
                          </span>
                        </td>
                        <td className="cs">
                          {/* An unanswered request says so. Rendering a blank cell
                              reads as "answered with nothing", which is the one
                              thing it does not mean. */}
                          {r.reply || "— awaiting a reply"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          }
        </QueryGuard>
      </section>
    </div>
  );
}
