"use client";

import {
  LIFECYCLE, STAGE_STATUS_META, HEALTH_META, projectProgress, currentStage,
} from "@/lib/milestones";
import { useClientMilestones } from "@/lib/hooks/portalClient";
import ClientHeader from "./ClientHeader";

// The client's project timeline — the same milestone stages the agency
// auto-advances as audits complete and content publishes. Read-only for
// the client: they track progress, they don't edit it.
export default function ClientMilestones() {
  const projectQ = useClientMilestones();
  const project = projectQ.data;

  return (
    <div className="tw cl">
      <ClientHeader
        focus={
          <>
            <span className="cl-focus-k">Project health</span>
            <span className="cl-focus-v">{project ? HEALTH_META[project.health].label : "—"}</span>
            <span className="cl-focus-note">
              <span className="material-symbols-rounded">flag</span>
              {project
                ? `${projectProgress(project)}% complete`
                : projectQ.isError
                  ? "Couldn't load"
                  : "No active project"}
            </span>
          </>
        }
      />

      {projectQ.isLoading ? (
        <div className="pt-empty">
          <span className="material-symbols-rounded spin">progress_activity</span>
          <div className="pt-empty-t">Loading your timeline…</div>
        </div>
      ) : projectQ.isError ? (
        // A FAILED FETCH IS NOT AN EMPTY TIMELINE, and the reverse is just as wrong:
        // "no project yet" is a 404, which the hook resolves to `null` so it lands in
        // the empty branch below. Only a genuine failure (5xx, network, auth) reaches
        // here, so this message is never shown to a client whose onboarding simply
        // has not started.
        <div className="pt-empty">
          <span className="material-symbols-rounded">error</span>
          <div className="pt-empty-t">Couldn&apos;t load your timeline</div>
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
      ) : !project ? (
        <div className="pt-empty">
          <span className="material-symbols-rounded">flag</span>
          <div className="pt-empty-t">No milestones yet</div>
          <div className="pt-empty-s">Your engagement timeline will appear here once onboarding begins.</div>
        </div>
      ) : (
        <>
          {/* progress summary */}
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
                    {LIFECYCLE.find((s) => s.key === currentStage(project).key)?.label}
                  </span>
                </div>
              </div>
              <div className="cl-ms-bar">
                <span style={{ width: `${projectProgress(project)}%` }} />
              </div>
            </div>
          </section>

          {/* stepper */}
          <section className="card">
            <div className="card-h">
              <div>
                <div className="ct">Delivery timeline</div>
                <div className="cs">Every stage of your SEO engagement, updated automatically.</div>
              </div>
            </div>

            <div className="cl-steps">
              {project.stages.map((stage, i) => {
                const meta = LIFECYCLE.find((s) => s.key === stage.key)!;
                const sm = STAGE_STATUS_META[stage.status];
                const last = i === project.stages.length - 1;
                return (
                  <div className={`cl-step ${stage.status}`} key={stage.key}>
                    <div className="cl-step-rail">
                      <span className="cl-step-node" style={{ color: sm.color }}>
                        <span className="material-symbols-rounded">{sm.icon}</span>
                      </span>
                      {!last && <span className="cl-step-line" />}
                    </div>
                    <div className="cl-step-body">
                      <div className="cl-step-top">
                        <span className="cl-step-ic material-symbols-rounded">{meta.icon}</span>
                        <span className="cl-step-t">{meta.label}</span>
                        <span className={`status-pill ${sm.cls}`}>{sm.label}</span>
                      </div>
                      <div className="cl-step-src">{stage.auto_source}</div>
                      <div className="cl-step-time">
                        <span className="material-symbols-rounded">schedule</span>Updated {stage.updated_at}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
