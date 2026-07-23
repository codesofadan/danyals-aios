"use client";

import { useState } from "react";
import { REQUEST_KINDS, REQUEST_STATUS_META, type RequestKind } from "@/lib/client";
import { useClient } from "./ClientContext";
import ClientHeader from "./ClientHeader";

// The Requests section — a lightweight channel from the client to the
// agency admin. Raise a request (unlock a graph, ask for a report, flag an
// issue) and track its status. Submitted requests land in the admin's
// support queue (tickets) once the backend is wired.
export default function ClientRequests() {
  const { requests, addRequest } = useClient();
  const [kind, setKind] = useState<RequestKind>("Report");
  const [subject, setSubject] = useState("");
  const [detail, setDetail] = useState("");
  const [sent, setSent] = useState(false);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

  const valid = subject.trim().length > 3;
  const open = requests.filter((r) => r.status !== "resolved").length;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!valid || busy) return;
    setFailed(false);
    setSent(false);
    setBusy(true);
    // Only confirm + clear the form once the POST actually succeeds; on failure,
    // keep what the client typed and show a retry-able error.
    addRequest(
      { kind, subject: subject.trim(), detail: detail.trim() },
      {
        onSuccess: () => {
          setBusy(false);
          setSubject(""); setDetail(""); setKind("Report");
          setSent(true);
          setTimeout(() => setSent(false), 2600);
        },
        onError: () => {
          setBusy(false);
          setFailed(true);
        },
      },
    );
  }

  return (
    <div className="tw cl">
      <ClientHeader
        eyebrow=""
        focus={
          <>
            <span className="cl-focus-k">Requests</span>
            <span className="cl-focus-v">{open} open with your team</span>
            <span className="cl-focus-note">
              <span className="material-symbols-rounded">forum</span>We usually reply within a day
            </span>
          </>
        }
      />

      <div className="cl-req-grid">
        {/* compose */}
        <section className="card">
          <div className="card-h">
            <div>
              <div className="ct">New request</div>
              <div className="cs">Tell us what you need — we&apos;ll take it from here.</div>
            </div>
          </div>

          <form className="cl-req-form" onSubmit={submit}>
            <div className="fld">
              <label>What&apos;s this about?</label>
              <div className="cl-kinds">
                {REQUEST_KINDS.map((k) => (
                  <button
                    type="button"
                    key={k.key}
                    className={`cl-kind${kind === k.key ? " on" : ""}`}
                    style={{ ["--c" as string]: k.c }}
                    onClick={() => setKind(k.key)}
                    aria-pressed={kind === k.key}
                  >
                    <span className="material-symbols-rounded">{k.icon}</span>
                    <span>{k.label}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="fld">
              <label>Subject</label>
              <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="e.g. Please unlock the Backlink Profile graph" />
            </div>

            <div className="fld">
              <label>Details <span className="cl-opt">(optional)</span></label>
              <textarea rows={4} value={detail} onChange={(e) => setDetail(e.target.value)} placeholder="Add any context that would help us action this faster." />
            </div>

            <div className="cl-req-foot">
              {sent && <span className="cl-req-sent"><span className="material-symbols-rounded">check_circle</span>Request sent</span>}
              {failed && <span className="cl-req-sent err"><span className="material-symbols-rounded">error</span>Couldn&apos;t send — please try again</span>}
              <button type="submit" className="primary-btn" disabled={!valid || busy}>
                <span className="material-symbols-rounded">{busy ? "progress_activity" : "send"}</span>{busy ? "Sending…" : "Send request"}
              </button>
            </div>
          </form>
        </section>

        {/* history */}
        <section className="card">
          <div className="card-h">
            <div>
              <div className="ct">Your requests</div>
              <div className="cs">Everything you&apos;ve raised, newest first.</div>
            </div>
          </div>

          <div className="cl-req-list">
            {requests.map((r) => {
              const kindMeta = REQUEST_KINDS.find((k) => k.key === r.kind);
              const sm = REQUEST_STATUS_META[r.status];
              return (
                <div className="cl-req-row" key={r.id}>
                  <span className="cl-req-ic" style={{ ["--c" as string]: kindMeta?.c }}>
                    <span className="material-symbols-rounded">{kindMeta?.icon}</span>
                  </span>
                  <div className="cl-req-main">
                    <div className="cl-req-top">
                      <span className="cl-req-subj">{r.subject}</span>
                      <span className={`status-pill ${sm.cls}`}>
                        <span className="material-symbols-rounded" style={{ fontSize: 13 }}>{sm.icon}</span>{sm.label}
                      </span>
                    </div>
                    <div className="cl-req-meta">
                      <span>{r.kind}</span><span className="dot-sep">·</span><span>{r.ago}</span>
                    </div>
                    {r.detail && <div className="cl-req-detail">{r.detail}</div>}
                    {r.reply && (
                      <div className="cl-req-reply">
                        <span className="material-symbols-rounded">support_agent</span>
                        <span>{r.reply}</span>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}
