"use client";

// A bulk content build, as one thing.
//
// WHAT WAS MISSING. A research fan-out creates thirty independent jobs — right, because
// that is what lets them run in parallel and stops one failure taking the rest down — but
// nothing recorded that they belonged together. Thirty rows landed in a board of every job
// the agency has ever run, mixed with other clients', and there was no way to ask "how is
// Tuesday's batch doing", no spend bound for the run as a whole, and no way to pick up the
// pages a budget hold stranded.
//
// THE HELD ROW IS THE POINT. A job blocked on budget, a missing key or the batch ceiling
// degrades honestly: it holds at drafting with a "Held — …" stage and an unchanged cost,
// deliberately NOT failed, because nothing is wrong with it. But a held job is not queued,
// so nothing will ever pick it up on its own. Before this the only way back was to know
// each code and re-enqueue it by hand, which meant nobody did.

import { useState } from "react";
import {
  useContentBatch,
  useContentBatches,
  useResumeBatch,
  useUpdateBatch,
  type ContentBatch,
} from "@/lib/hooks/content";
import QueryGuard from "@/components/ui/QueryGuard";
import EmptyState from "@/components/ui/EmptyState";
import { useToast, describeError } from "@/components/ui/Toast";

const money = (n: number) => `$${n.toFixed(2)}`;

function Bar({ batch }: { batch: ContentBatch }) {
  // Segments in lifecycle order so the eye reads left-to-right as progress. `held` gets its
  // own colour because it is the one state that needs a human.
  const total = Math.max(batch.jobs, 1);
  const seg = (n: number, colour: string, label: string) =>
    n > 0 ? (
      <span
        key={label}
        title={`${label}: ${n}`}
        style={{ width: `${(n / total) * 100}%`, background: colour, display: "block", height: 8 }}
      />
    ) : null;
  return (
    <div style={{ display: "flex", borderRadius: 6, overflow: "hidden", background: "var(--line)" }}>
      {seg(batch.done, "var(--ok)", "published")}
      {seg(batch.inReview, "var(--accent, #7B69EE)", "in review")}
      {seg(batch.running, "var(--muted)", "running")}
      {seg(batch.held, "var(--warn)", "held")}
      {seg(batch.stopped, "var(--crit)", "stopped")}
    </div>
  );
}

function BatchDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useContentBatch(id);
  const resume = useResumeBatch(id);
  const update = useUpdateBatch(id);
  const toast = useToast();
  const [ceiling, setCeiling] = useState("");

  const data = q.data;
  const held = (data?.jobs ?? []).filter((j) => j.held);

  return (
    <QueryGuard queries={[q]} label="this batch" minHeight={160}>
      {data && (
        <section className="card" style={{ padding: "var(--s-7)" }}>
          <div className="card-h" style={{ padding: 0, marginBottom: 12 }}>
            <div>
              <div className="ct">{data.label || "Untitled batch"}</div>
              <div className="cs" style={{ marginTop: 4 }}>
                {data.client}
                {data.contentType ? ` · ${data.contentType}` : ""} · {data.jobs.length} pages ·
                spent {money(data.spent)}
                {data.costCeiling !== null ? ` of ${money(data.costCeiling)}` : " (no ceiling)"}
              </div>
            </div>
            <button type="button" className="ghostbtn" onClick={onClose}>
              Close
            </button>
          </div>

          {held.length > 0 ? (
            <div
              className="card"
              style={{ padding: "12px 14px", marginBottom: 12, borderLeft: "4px solid var(--warn)" }}
            >
              <b>
                {held.length} page{held.length === 1 ? "" : "s"} held
              </b>
              <div className="cs" style={{ marginTop: 4 }}>
                Held is not failed — nothing is wrong with these pages, they are waiting on
                budget or a key. Raise the ceiling if that is what stopped them, then resume.
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "center" }}>
                <input
                  style={{ width: 120 }}
                  value={ceiling}
                  onChange={(e) => setCeiling(e.target.value)}
                  placeholder="New ceiling $"
                  aria-label="New batch spend ceiling in dollars"
                />
                <button
                  type="button"
                  className="ghostbtn"
                  disabled={update.isPending || !ceiling.trim()}
                  onClick={() =>
                    update.mutate(
                      { costCeiling: Number(ceiling) },
                      {
                        onSuccess: () => {
                          setCeiling("");
                          toast.success("Ceiling updated");
                        },
                        onError: (e) => toast.error("Couldn't change the ceiling", describeError(e)),
                      },
                    )
                  }
                >
                  Raise ceiling
                </button>
                <button
                  type="button"
                  className="primary-btn"
                  disabled={resume.isPending}
                  onClick={() =>
                    resume.mutate(undefined, {
                      onSuccess: (r) =>
                        toast.success(
                          `Resumed ${r.resumed.length} page${r.resumed.length === 1 ? "" : "s"}`,
                          r.skipped.length
                            ? `${r.skipped.length} left alone — only held pages are resumable.`
                            : undefined,
                        ),
                      onError: (e) => toast.error("Couldn't resume the batch", describeError(e)),
                    })
                  }
                >
                  {resume.isPending ? "Resuming…" : "Resume held pages"}
                </button>
              </div>
            </div>
          ) : null}

          <table className="alt-table">
            <thead>
              <tr>
                <th>Page</th>
                <th>Status</th>
                <th>Stage</th>
                <th className="num">Words</th>
                <th className="num">Cost</th>
              </tr>
            </thead>
            <tbody>
              {data.jobs.map((j) => (
                <tr key={j.code}>
                  <td>
                    <a href={`/admin/content/${j.code}`}>{j.code}</a>
                    <div className="cs">{j.topic}</div>
                  </td>
                  <td>
                    <span className={`status-pill ${j.held ? "warn" : j.status === "done" ? "ok" : "mut"}`}>
                      {j.held ? "held" : j.status.replace("_", " ")}
                    </span>
                  </td>
                  <td className="cs">{j.stage}</td>
                  <td className="num">{j.words ? j.words.toLocaleString() : "—"}</td>
                  <td className="num">{money(j.cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </QueryGuard>
  );
}

export default function BatchBoard() {
  const q = useContentBatches();
  const [open, setOpen] = useState<string | null>(null);

  if (open) return <BatchDetail id={open} onClose={() => setOpen(null)} />;

  return (
    <QueryGuard queries={[q]} label="the content batches" minHeight={160}>
      {q.data && q.data.length === 0 ? (
        <EmptyState
          icon="layers"
          title="No bulk builds yet"
          hint="A research fan-out creates a batch: pick pages in the wizard and every page from that run is grouped here, with its spend and any pages that stopped."
        />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {(q.data ?? []).map((b) => (
            <button
              key={b.id}
              type="button"
              className="card"
              onClick={() => setOpen(b.id)}
              style={{ padding: "14px 18px", textAlign: "left", cursor: "pointer" }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                <div>
                  <b>{b.label || "Untitled batch"}</b>
                  <div className="cs" style={{ marginTop: 2 }}>
                    {b.client}
                    {b.contentType ? ` · ${b.contentType}` : ""} · {b.jobs} pages
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div className="cs">
                    {money(b.spent)}
                    {b.costCeiling !== null ? ` of ${money(b.costCeiling)}` : ""}
                  </div>
                  {b.held > 0 ? (
                    <span className="status-pill warn" style={{ marginTop: 4 }}>
                      {b.held} held
                    </span>
                  ) : b.done === b.jobs && b.jobs > 0 ? (
                    <span className="status-pill ok" style={{ marginTop: 4 }}>
                      complete
                    </span>
                  ) : null}
                </div>
              </div>
              <div style={{ marginTop: 10 }}>
                <Bar batch={b} />
              </div>
            </button>
          ))}
        </div>
      )}
    </QueryGuard>
  );
}
