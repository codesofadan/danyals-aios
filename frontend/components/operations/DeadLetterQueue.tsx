"use client";

// ============================================================
// AIOS · Operations — THE DEAD LETTER QUEUE
//
// A dead letter is work the platform ACCEPTED and did not deliver. It is the most
// operationally important object on this screen: someone was told their job was
// queued, and it never happened. Every row carries the payload needed to run it
// again, so this queue is a to-do list rather than an obituary.
//
// GROUPED BY CAUSE (`reasonCode`), not by job name. Twelve lost jobs sharing one
// cause is one incident; twelve jobs with twelve causes is twelve. The grouping is
// what tells those apart at a glance.
//
// Open items arrive OLDEST FIRST — the opposite of every other feed here, and
// deliberately: the longest-unresolved lost job is the most urgent one.
//
// REPLAY surfaces the returned runId so the operator can follow the retry into the
// runs log instead of guessing whether it took. The replay gets its OWN idempotency
// key server-side (replay:<id>) — reusing the original would find the old terminal
// run and silently do nothing.
//
// RESOLVE requires a written decision (schema + CHECK constraint). A queue closed
// with no reasons written is a graveyard: the next person cannot tell "we fixed the
// underlying bug" from "we gave up on this one".
// ============================================================

import { useMemo, useState } from "react";
import { relativeTime, type DeadLetter, type ReplayResult } from "@/lib/jobs";
import { useReplayDeadLetter, useResolveDeadLetter } from "@/lib/hooks/jobs";

export default function DeadLetterQueue({
  rows,
  loading,
  openOnly,
  onOpenOnly,
  canAct,
  onFollowRun,
}: {
  rows: DeadLetter[];
  loading: boolean;
  openOnly: boolean;
  onOpenOnly: (v: boolean) => void;
  canAct: boolean;
  onFollowRun: (runId: string) => void;
}) {
  const replay = useReplayDeadLetter();
  const resolve = useResolveDeadLetter();

  // The runId a replay returned, kept per dead letter so the operator can follow
  // the retry after the list refetches.
  const [replayed, setReplayed] = useState<Record<string, ReplayResult>>({});
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [resolution, setResolution] = useState("");

  const groups = useMemo(() => {
    const m = new Map<string, DeadLetter[]>();
    for (const d of rows) {
      const cause = d.reasonCode || d.errorType || "unclassified";
      const arr = m.get(cause);
      if (arr) arr.push(d);
      else m.set(cause, [d]);
    }
    return [...m.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [rows]);

  const openCount = rows.filter((d) => d.open).length;
  const actionError =
    replay.error instanceof Error
      ? replay.error.message
      : resolve.error instanceof Error
        ? resolve.error.message
        : null;

  function submitResolve(id: string) {
    const text = resolution.trim();
    if (!text) return;
    resolve.mutate(
      { deadLetterId: id, resolution: text },
      {
        onSuccess: () => {
          setResolvingId(null);
          setResolution("");
        },
      },
    );
  }

  return (
    <section className={`card ops-dlq ${openCount > 0 ? "hot" : ""}`}>
      <div className="card-h">
        <div>
          <div className="ct">Dead letters</div>
          <div className="cs">
            Work the platform accepted and did not deliver. Each one carries the payload to run it again.
          </div>
        </div>
        <div className="tools">
          <span className={`pill-tag ${openCount > 0 ? "warn" : "ok"}`}>
            <span className="material-symbols-rounded">{openCount > 0 ? "report" : "check_circle"}</span>
            {openCount} open
          </span>
          <div className="seg" role="tablist" aria-label="Dead letter scope">
            <button
              type="button"
              role="tab"
              aria-selected={openOnly}
              className={openOnly ? "on" : undefined}
              onClick={() => onOpenOnly(true)}
            >
              Open
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={!openOnly}
              className={!openOnly ? "on" : undefined}
              onClick={() => onOpenOnly(false)}
            >
              All
            </button>
          </div>
        </div>
      </div>

      {actionError && (
        <div className="ops-err" role="alert">
          <span className="material-symbols-rounded">error</span>
          <span>{actionError}</span>
        </div>
      )}

      {rows.length === 0 ? (
        <div className="ops-empty">
          <span className="material-symbols-rounded">{loading ? "hourglass_top" : "verified"}</span>
          <div className="ops-empty-t">
            {loading ? "Loading the queue…" : openOnly ? "Nothing was lost" : "The queue is empty"}
          </div>
          <div className="ops-empty-s">
            {loading
              ? "Reading undelivered work."
              : "Every job the platform accepted was delivered or ended in a recorded outcome. Nothing is sitting undelivered."}
          </div>
        </div>
      ) : (
        groups.map(([cause, items]) => (
          <div className="ops-dl-group" key={cause}>
            <div className="ops-dl-gh">
              <span className="material-symbols-rounded">label_important</span>
              <span className="ops-dl-cause">{cause}</span>
              <span className="ops-dl-gc">
                {items.length} {items.length === 1 ? "job" : "jobs"}
              </span>
            </div>

            {items.map((d) => {
              const result = replayed[d.id];
              return (
                <div className="ops-dl-i" key={d.id}>
                  <div className="ops-dl-top">
                    <div>
                      <div className="ops-dl-name">{d.jobName}</div>
                      <div className="ops-dl-meta">
                        <span>{d.clientName || (d.clientId ? "Unnamed client" : "Platform-wide")}</span>
                        <span className="ops-q">{d.queue}</span>
                        <span>
                          <b>{d.attempts}</b> {d.attempts === 1 ? "attempt" : "attempts"}
                        </span>
                        {d.deadLetteredAt && <span>lost {relativeTime(d.deadLetteredAt)}</span>}
                        {!d.open && (
                          <span className="status-pill mut">{d.replayedAt ? "replayed" : "resolved"}</span>
                        )}
                      </div>
                    </div>

                    {canAct && d.open && (
                      <div className="ops-dl-acts">
                        <button
                          type="button"
                          className="ops-btn primary"
                          disabled={replay.isPending}
                          onClick={() =>
                            replay.mutate(d.id, {
                              onSuccess: (res: ReplayResult) =>
                                setReplayed((prev) => ({ ...prev, [d.id]: res })),
                            })
                          }
                        >
                          <span className="material-symbols-rounded">replay</span>
                          Replay
                        </button>
                        <button
                          type="button"
                          className="ops-btn"
                          onClick={() => {
                            setResolvingId(resolvingId === d.id ? null : d.id);
                            setResolution("");
                          }}
                        >
                          <span className="material-symbols-rounded">task_alt</span>
                          Resolve
                        </button>
                      </div>
                    )}
                  </div>

                  {(d.errorType || d.errorMessage) && (
                    <div className="ops-dl-err">
                      <b>{d.errorType || "Error"}</b>
                      {d.errorMessage ? ` — ${d.errorMessage}` : ""}
                    </div>
                  )}

                  {result && (
                    <div className="ops-dl-replayed">
                      <span className="material-symbols-rounded">north_east</span>
                      <span>
                        Replayed as run <b>{result.runId}</b>
                      </span>
                      <button type="button" className="ops-btn" onClick={() => onFollowRun(result.runId)}>
                        <span className="material-symbols-rounded">visibility</span>
                        Follow the retry
                      </button>
                    </div>
                  )}

                  {!result && d.replayedRunId && (
                    <div className="ops-dl-replayed">
                      <span className="material-symbols-rounded">north_east</span>
                      <span>
                        Replayed as run <b>{d.replayedRunId}</b>
                      </span>
                      <button
                        type="button"
                        className="ops-btn"
                        onClick={() => onFollowRun(d.replayedRunId as string)}
                      >
                        <span className="material-symbols-rounded">visibility</span>
                        Follow the retry
                      </button>
                    </div>
                  )}

                  {d.resolution && (
                    <div className="ops-dl-resolved">
                      <span className="material-symbols-rounded" style={{ fontSize: 15, verticalAlign: "-2px" }}>
                        task_alt
                      </span>{" "}
                      {d.resolution}
                    </div>
                  )}

                  {canAct && resolvingId === d.id && (
                    <div className="ops-dl-resolve">
                      <input
                        type="text"
                        maxLength={1000}
                        autoFocus
                        value={resolution}
                        placeholder="What was decided? (required — 'fixed the credential', 'client cancelled', …)"
                        onChange={(e) => setResolution(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") submitResolve(d.id);
                        }}
                        aria-label="Resolution"
                      />
                      <button
                        type="button"
                        className="ops-btn primary"
                        disabled={!resolution.trim() || resolve.isPending}
                        onClick={() => submitResolve(d.id)}
                      >
                        {resolve.isPending ? "Closing…" : "Close it"}
                      </button>
                    </div>
                  )}

                  <details className="ops-detail">
                    <summary>Payload &amp; trace</summary>
                    <div className="ops-facts" style={{ marginTop: 10 }}>
                      <div>
                        <div className="ops-fact-k">Correlation id</div>
                        <div className="ops-fact-v mono">{d.correlationId || "—"}</div>
                      </div>
                      <div>
                        <div className="ops-fact-k">Idempotency key</div>
                        <div className="ops-fact-v mono">{d.idempotencyKey || "—"}</div>
                      </div>
                      <div>
                        <div className="ops-fact-k">First failed</div>
                        <div className="ops-fact-v">{d.firstFailedAt ? relativeTime(d.firstFailedAt) : "—"}</div>
                      </div>
                      <div>
                        <div className="ops-fact-k">Original run</div>
                        <div className="ops-fact-v mono">{d.runId || "—"}</div>
                      </div>
                    </div>
                    <pre className="ops-pre">{JSON.stringify(d.payload, null, 2)}</pre>
                    {d.traceback && <pre className="ops-pre">{d.traceback}</pre>}
                  </details>
                </div>
              );
            })}
          </div>
        ))
      )}

      <div className="ops-note">
        <span className="material-symbols-rounded">info</span>
        <span>
          Open items are listed <b>oldest first</b> — the longest-unresolved lost job is the
          most urgent, not the least.
          {canAct
            ? " A replay runs the original arguments under a fresh idempotency key; closing one requires a written decision."
            : " Replay and resolve are lead actions (owner / admin / manager)."}
        </span>
      </div>
    </section>
  );
}
