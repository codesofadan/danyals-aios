"use client";

// MY QUEUE - what is being worked on for this client, right now.
//
// It replaces the Milestones tab. Milestones rendered the five-stage lifecycle and
// nothing else, so it answered "where are we in the plan?" and never the question a
// client actually opens the portal to ask: what is happening this week, what landed,
// and what am I waiting on. Those three answers already existed in the API - the
// project's stages, the deliverables ledger and the client's own requests - and were
// spread across three screens, one of which showed only a third of the picture.
//
// So this screen composes the THREE reads rather than adding a fourth endpoint:
//   /portal/milestones   -> the stage the engagement is on, and what advances it
//   /portal/deliverables -> what has actually been handed over
//   /portal/requests     -> what the client has asked for and not yet had answered
//
// Nothing here is derived from a placeholder. A missing project is a real state (the
// engagement has not been set up), and it is rendered as that rather than as an empty
// timeline, because "no milestones yet" and "we have not started" read very
// differently to someone paying for the work.

import Link from "next/link";
import QueryGuard from "@/components/ui/QueryGuard";
import {
  useClientDeliverables,
  useClientMilestones,
  useClientRequests,
} from "@/lib/hooks/portalClient";
import {
  currentStage,
  LIFECYCLE,
  projectProgress,
  STAGE_STATUS_META,
  type Stage,
} from "@/lib/milestones";

const stageLabel = (key: string): string =>
  LIFECYCLE.find((l) => l.key === key)?.label ?? key;

const stageIcon = (key: string): string =>
  LIFECYCLE.find((l) => l.key === key)?.icon ?? "radio_button_unchecked";

export default function ClientQueue() {
  const projectQ = useClientMilestones();
  const deliverablesQ = useClientDeliverables();
  const requestsQ = useClientRequests();

  const project = projectQ.data ?? null;
  const deliverables = deliverablesQ.data ?? [];
  const requests = requestsQ.data ?? [];

  const stages: Stage[] = project?.stages ?? [];
  const active = stages.filter((s) => s.status === "in_progress" || s.status === "blocked");
  const next = stages.filter((s) => s.status === "upcoming");
  const doneStages = stages.filter((s) => s.status === "completed");
  const openRequests = requests.filter((r) => r.status !== "resolved");
  const recent = deliverables.filter((d) => d.status === "ready").slice(0, 6);

  return (
    <div className="tw">
      <QueryGuard
        queries={[projectQ, deliverablesQ, requestsQ]}
        label="your queue"
        minHeight={220}
      >
        {
          <div style={{ display: "grid", gap: 16 }}>
            {/* --- Where the engagement is ------------------------------------ */}
            {project ? (
              <section className="card" style={{ padding: "var(--s-7)" }}>
                <div style={{ display: "flex", gap: 14, alignItems: "baseline", flexWrap: "wrap" }}>
                  <div className="ct">Where your project is</div>
                  <span className={`status-pill ${STAGE_STATUS_META[currentStage(project).status].cls}`}>
                    {stageLabel(currentStage(project).key)}
                  </span>
                  <span className="cs" style={{ marginLeft: "auto" }}>
                    {projectProgress(project)}% through the plan
                  </span>
                </div>

                <div className="cq-bar" aria-hidden>
                  <span style={{ width: `${projectProgress(project)}%` }} />
                </div>

                <ol className="cq-steps">
                  {stages.map((s) => {
                    const meta = STAGE_STATUS_META[s.status];
                    return (
                      <li key={s.key} className={`cq-step ${s.status}`}>
                        <span className="cq-dot" style={{ background: meta.color }}>
                          <span className="material-symbols-rounded">{stageIcon(s.key)}</span>
                        </span>
                        <div className="cq-step-b">
                          <div className="cq-step-t">{stageLabel(s.key)}</div>
                          <div className="cs">{meta.label}</div>
                        </div>
                      </li>
                    );
                  })}
                </ol>
              </section>
            ) : (
              <section className="card" style={{ padding: "var(--s-7)" }}>
                <div className="ct">Your project hasn&apos;t been set up yet</div>
                <div className="cs" style={{ marginTop: 6, lineHeight: 1.6 }}>
                  Your account is active, but the delivery plan has not been created. Your
                  account manager sets this up at kickoff — nothing is missing on your side.
                </div>
              </section>
            )}

            {/* --- Happening now ---------------------------------------------- */}
            <section className="card" style={{ padding: "var(--s-7)" }}>
              <div className="ct">Happening now</div>
              {active.length === 0 ? (
                <div className="cs" style={{ marginTop: 8 }}>
                  Nothing is mid-flight this moment. {next.length > 0
                    ? `${stageLabel(next[0].key)} is the next stage to start.`
                    : "Your team will move the next stage on when it begins."}
                </div>
              ) : (
                <ul className="cq-list">
                  {active.map((s) => (
                    <li key={s.key}>
                      <span className="material-symbols-rounded">{stageIcon(s.key)}</span>
                      <div>
                        <b>{stageLabel(s.key)}</b>
                        <div className="cs">
                          {s.status === "blocked" ? "Blocked — " : "In progress — "}
                          {/* auto_source names the job or audit that advances this
                              stage. It is the honest answer to "who is doing what": a
                              stage moves when real work completes, not on a schedule. */}
                          {s.auto_source || "your team is on it"}
                          {s.updated_at ? ` · updated ${s.updated_at}` : ""}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* --- What landed ------------------------------------------------- */}
            <section className="card" style={{ padding: "var(--s-7)" }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
                <div className="ct">What has landed</div>
                <Link className="cs" href="/client/reports" style={{ marginLeft: "auto" }}>
                  All reports →
                </Link>
              </div>
              {recent.length === 0 ? (
                <div className="cs" style={{ marginTop: 8 }}>
                  Nothing has been delivered yet. Finished work appears here the moment
                  your team releases it.
                </div>
              ) : (
                <ul className="cq-list">
                  {recent.map((d) => (
                    <li key={d.id}>
                      <span className="material-symbols-rounded">{d.icon || "description"}</span>
                      <div>
                        <b>{d.title}</b>
                        <div className="cs">
                          {d.kind}
                          {d.period ? ` · ${d.period}` : ""}
                          {d.date ? ` · ${d.date}` : ""}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {/* --- What you are waiting on -------------------------------------- */}
            <section className="card" style={{ padding: "var(--s-7)" }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
                <div className="ct">What you&apos;re waiting on</div>
                <Link className="cs" href="/client/requests" style={{ marginLeft: "auto" }}>
                  Raise a request →
                </Link>
              </div>
              {openRequests.length === 0 ? (
                <div className="cs" style={{ marginTop: 8 }}>
                  You have no open requests. Anything you ask for shows here until it is
                  answered.
                </div>
              ) : (
                <ul className="cq-list">
                  {openRequests.map((r) => (
                    <li key={r.id}>
                      <span className="material-symbols-rounded">forum</span>
                      <div>
                        <b>{r.subject}</b>
                        <div className="cs">
                          {r.status}
                          {r.kind ? ` · ${r.kind}` : ""}
                          {r.ago ? ` · ${r.ago}` : ""}
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {doneStages.length > 0 && (
              <section className="card" style={{ padding: "var(--s-7)" }}>
                <div className="ct">Already done</div>
                <div className="cq-chips">
                  {doneStages.map((s) => (
                    <span key={s.key} className="chip">
                      <span className="material-symbols-rounded">check</span>
                      {stageLabel(s.key)}
                    </span>
                  ))}
                </div>
              </section>
            )}
          </div>
        }
      </QueryGuard>
    </div>
  );
}
