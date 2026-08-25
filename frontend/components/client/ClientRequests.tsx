"use client";

import { useEffect, useRef, useState } from "react";
import { REQUEST_KINDS, REQUEST_STATUS_META, type RequestKind } from "@/lib/client";
import PortalThread from "@/components/threads/PortalThread";
import { useClient } from "./ClientContext";
import ClientHeader from "./ClientHeader";

// The Requests section — a lightweight channel from the client to the
// agency admin. Raise a request (ask for a report, request access, flag an
// issue) and track its status. Submitted requests POST to /portal/requests and
// land in the admin's support queue; the history reads GET /portal/requests.
export default function ClientRequests() {
  const { requests, requestsLoading, requestsError, refetchRequests, addRequest } = useClient();
  const [kind, setKind] = useState<RequestKind>("Report");
  const [subject, setSubject] = useState("");
  const [detail, setDetail] = useState("");
  const [sent, setSent] = useState(false);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  // Track the transient "sent" banner timer so navigating away mid-flash can't
  // fire setState on an unmounted component (an uncancelled timer).
  const sentTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (sentTimer.current) clearTimeout(sentTimer.current); }, []);

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
          if (sentTimer.current) clearTimeout(sentTimer.current);
          sentTimer.current = setTimeout(() => setSent(false), 2600);
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

          {requestsLoading ? (
            <div className="pt-empty sm">
              <span className="material-symbols-rounded spin">progress_activity</span>
              <div className="pt-empty-t">Loading your requests…</div>
            </div>
          ) : requestsError ? (
            <div className="pt-empty sm">
              <span className="material-symbols-rounded">error</span>
              <div className="pt-empty-t">Couldn&apos;t load your requests</div>
              <div className="pt-empty-s">There was a problem reaching the server.</div>
              <button className="primary-btn sm" type="button" onClick={refetchRequests} style={{ marginTop: 12 }}>
                <span className="material-symbols-rounded">refresh</span>Retry
              </button>
            </div>
          ) : requests.length === 0 ? (
            <div className="pt-empty sm">
              <span className="material-symbols-rounded">forum</span>
              <div className="pt-empty-t">No requests yet</div>
              <div className="pt-empty-s">Raise one on the left and we&apos;ll get right on it.</div>
            </div>
          ) : (
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
                    {/* The pre-0098 one-shot reply. Kept while the column is still
                        written, so an answer sent before threads existed is not lost
                        from the client's view; migration 0099 also copied it into the
                        thread, so this renders only until the column is retired. */}
                    {r.reply && (
                      <div className="cl-req-reply">
                        <span className="material-symbols-rounded">support_agent</span>
                        <span>{r.reply}</span>
                      </div>
                    )}
                    <PortalThread code={r.id} />
                  </div>
                </div>
              );
            })}
          </div>
          )}
        </section>
      </div>
    </div>
  );
}
