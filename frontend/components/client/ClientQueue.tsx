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
//   /portal/milestones   -> the stage the engagement is on, and how far through it is
//   /portal/deliverables -> what has actually been handed over
//   /portal/requests     -> what the client has asked for and not yet had answered
//
// IT USES THE PORTAL'S OWN CLASSES - `cl-stat-card`, `cl-ms-bar`, `cl-rp-row` -
// and defines no new ones. The first cut of this screen invented a
// `cq-*` vocabulary and never wrote the stylesheet for it, so every rule resolved to
// nothing: the progress bar was an empty div, the stepper was a default-numbered
// <ol>, and the lists were browser bullets. Reusing the vocabulary the rest of the
// portal is built from is both the fix and the reason it cannot recur - there is no
// private stylesheet here to forget.
//
// Nothing is derived from a placeholder. A missing project is a real state (the
// engagement has not been set up) and reads as that, never as an empty timeline:
// "no milestones yet" and "we have not started" mean very different things to
// someone paying for the work.

import Link from "next/link";
import ClientHeader from "./ClientHeader";
import {
  useClientDeliverables,
  useClientMilestones,
  useClientRequests,
} from "@/lib/hooks/portalClient";
import {
  currentStage,
  LIFECYCLE,
  projectProgress,
} from "@/lib/milestones";

//: The accent each deliverable kind carries in its row icon (`--c`, read by
//: `.cl-rp-ic`). Same series the rest of the portal colours charts with.
const KIND_COLOR: Record<string, string> = {
  Audit: "var(--c1)",
  Monthly: "var(--c2)",
  Content: "var(--violet)",
  Backlinks: "var(--c4)",
  Local: "var(--ok)",
};

const STATUS_PILL: Record<string, string> = {
  open: "info",
  pending: "warn",
  resolved: "ok",
};

const stageMeta = (key: string) => LIFECYCLE.find((l) => l.key === key);

export default function ClientQueue() {
  const projectQ = useClientMilestones();
  const deliverablesQ = useClientDeliverables();
  const requestsQ = useClientRequests();

  const project = projectQ.data ?? null;
  const deliverables = deliverablesQ.data ?? [];
  const requests = requestsQ.data ?? [];

  const ready = deliverables.filter((d) => d.status === "ready");
  const openRequests = requests.filter((r) => r.status !== "resolved");
  const stages = project?.stages ?? [];
  const doneCount = stages.filter((s) => s.status === "completed").length;
  const active = stages.filter((s) => s.status === "in_progress" || s.status === "blocked");

  return (
    <div className="tw cl">
      <ClientHeader
        focus={
          <>
            <span className="cl-focus-k">Working on now</span>
            <span className="cl-focus-v">
              {/* With nothing in progress this said "Between stages" while the stat
                  card beside it said "Onboarding is current" - the same page
                  disagreeing with itself. Fall back to the CURRENT stage, which is
                  what `currentStage` already resolves and what the rest of the
                  screen shows. */}
              {active.length > 0
                ? stageMeta(active[0].key)?.label ?? active[0].key
                : project
                  ? stageMeta(currentStage(project).key)?.label ?? "In planning"
                  : "Not started"}
            </span>
            <span className="cl-focus-note">
              <span className="material-symbols-rounded">bolt</span>
              {project
                ? `${projectProgress(project)}% of the plan complete`
                : projectQ.isError
                  ? "Couldn't load"
                  : "Your plan hasn't been set up"}
            </span>
          </>
        }
      />

      {projectQ.isLoading ? (
        <div className="pt-empty">
          <span className="material-symbols-rounded spin">progress_activity</span>
          <div className="pt-empty-t">Loading your queue…</div>
        </div>
      ) : projectQ.isError ? (
        // A FAILED FETCH IS NOT AN EMPTY QUEUE. "No project yet" is a 404, which the
        // hook resolves to `null` and which lands in the empty branch below, so this
        // message never reaches a client whose onboarding simply has not begun.
        <div className="pt-empty">
          <span className="material-symbols-rounded">error</span>
          <div className="pt-empty-t">Couldn&apos;t load your queue</div>
          <div className="pt-empty-s">There was a problem reaching the server.</div>
          <button
            className="primary-btn sm"
            type="button"
            onClick={() => void projectQ.refetch()}
            disabled={projectQ.isFetching}
            style={{ marginTop: 12 }}
          >
            <span className={`material-symbols-rounded${projectQ.isFetching ? " spin" : ""}`}>
              {projectQ.isFetching ? "progress_activity" : "refresh"}
            </span>
            {projectQ.isFetching ? "Retrying…" : "Retry"}
          </button>
        </div>
      ) : (
        <>
          {/* --- the three numbers, in the portal's stat-card language ---------- */}
          <div className="cl-stats">
            <div className="cl-stat-card">
              <div className="cl-stat-k">Stages complete</div>
              <div className="cl-stat-big">
                {doneCount}
                <span className="cl-stat-u">/ {stages.length || 5}</span>
              </div>
              <div className="cl-stat-sub">
                {project
                  ? `${stageMeta(currentStage(project).key)?.label} is current`
                  : "Your plan hasn't been set up yet"}
              </div>
            </div>
            <div className="cl-stat-card">
              <div className="cl-stat-k">Delivered to you</div>
              <div className="cl-stat-big">{ready.length}</div>
              <div className="cl-stat-sub">
                {ready.length === 0 ? (
                  "Nothing handed over yet"
                ) : (
                  <Link href="/client/reports" className="cl-stat-link">
                    View your reports →
                  </Link>
                )}
              </div>
            </div>
            <div className="cl-stat-card">
              <div className="cl-stat-k">Open requests</div>
              <div className="cl-stat-big">{openRequests.length}</div>
              <div className="cl-stat-sub">
                {openRequests.length === 0 ? (
                  <Link href="/client/requests" className="cl-stat-link">
                    Ask us for something →
                  </Link>
                ) : (
                  "Waiting on your team"
                )}
              </div>
            </div>
          </div>

          {/* --- how far through the plan --------------------------------------- */}
          {project ? (
            <section className="card cl-ms-head">
              <div className="cl-ms-progress">
                <div className="cl-ms-progress-top">
                  <div>
                    <div className="cl-ms-progress-l">Overall progress</div>
                    <div className="cl-ms-progress-v">{projectProgress(project)}%</div>
                  </div>
                  <div className="cl-ms-current">
                    <span className="cl-ms-current-l">Current stage</span>
                    <span className="cl-ms-current-v">
                      {stageMeta(currentStage(project).key)?.label}
                    </span>
                  </div>
                </div>
                <div className="cl-ms-bar">
                  <span style={{ width: `${projectProgress(project)}%` }} />
                </div>
              </div>
            </section>
          ) : (
            <section className="card">
              <div className="pt-empty">
                <span className="material-symbols-rounded">flag</span>
                <div className="pt-empty-t">Your plan hasn&apos;t been set up yet</div>
                <div className="pt-empty-s">
                  Your account is active, but the delivery plan is created at kickoff.
                  Nothing is missing on your side.
                </div>
              </div>
            </section>
          )}

          {/* --- what landed ---------------------------------------------------- */}
          <section className="card">
            <div className="card-h">
              <div>
                <div className="ct">What has landed</div>
                <div className="cs">Finished work, newest first.</div>
              </div>
              <Link href="/client/reports" className="mini-btn">All reports</Link>
            </div>
            {deliverablesQ.isError ? (
              <div className="pt-empty">
                <span className="material-symbols-rounded">error</span>
                <div className="pt-empty-t">Couldn&apos;t load your deliverables</div>
              </div>
            ) : ready.length === 0 ? (
              <div className="pt-empty">
                <span className="material-symbols-rounded">inbox</span>
                <div className="pt-empty-t">Nothing delivered yet</div>
                <div className="pt-empty-s">
                  Finished work appears here the moment your team releases it.
                </div>
              </div>
            ) : (
              <div className="cl-rp-list">
                {ready.slice(0, 6).map((d) => (
                  <div
                    className="cl-rp-row"
                    key={d.id}
                    style={{ ["--c" as string]: KIND_COLOR[d.kind] ?? "var(--c2)" }}
                  >
                    <span className="cl-rp-ic">
                      <span className="material-symbols-rounded">{d.icon || "description"}</span>
                    </span>
                    <div className="cl-rp-main">
                      <div className="cl-rp-t">{d.title}</div>
                      <div className="cl-rp-meta">
                        <span className="cl-rp-kind">{d.kind}</span>
                        {d.period && <><span className="dot-sep">·</span><span>{d.period}</span></>}
                        {d.date && <><span className="dot-sep">·</span><span>{d.date}</span></>}
                      </div>
                    </div>
                    <div className="cl-rp-actions">
                      {d.size && <span className="cl-rp-size">{d.size}</span>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* --- what you're waiting on ----------------------------------------- */}
          <section className="card">
            <div className="card-h">
              <div>
                <div className="ct">What you&apos;re waiting on</div>
                <div className="cs">Requests you&apos;ve raised that aren&apos;t answered yet.</div>
              </div>
              <Link href="/client/requests" className="mini-btn">Raise a request</Link>
            </div>
            {requestsQ.isError ? (
              <div className="pt-empty">
                <span className="material-symbols-rounded">error</span>
                <div className="pt-empty-t">Couldn&apos;t load your requests</div>
              </div>
            ) : openRequests.length === 0 ? (
              <div className="pt-empty">
                <span className="material-symbols-rounded">forum</span>
                <div className="pt-empty-t">Nothing outstanding</div>
                <div className="pt-empty-s">
                  Anything you ask for stays here until your team answers it.
                </div>
              </div>
            ) : (
              <div className="cl-rp-list">
                {openRequests.map((r) => (
                  <div
                    className="cl-rp-row"
                    key={r.id}
                    style={{ ["--c" as string]: "var(--violet)" }}
                  >
                    <span className="cl-rp-ic">
                      <span className="material-symbols-rounded">forum</span>
                    </span>
                    <div className="cl-rp-main">
                      <div className="cl-rp-t">{r.subject}</div>
                      <div className="cl-rp-meta">
                        <span className="cl-rp-kind">{r.kind}</span>
                        {r.ago && <><span className="dot-sep">·</span><span>{r.ago}</span></>}
                      </div>
                    </div>
                    <div className="cl-rp-actions">
                      <span className={`status-pill ${STATUS_PILL[r.status] ?? "mut"}`}>
                        {r.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
