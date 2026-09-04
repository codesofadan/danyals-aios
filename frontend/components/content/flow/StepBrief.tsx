"use client";

// Screen 3 — the facts the pages are allowed to state, and how they should look.
//
// Proof points are REQUIRED and always were; what was missing was any hint of
// what a usable one looks like. The writer may state these and nothing else, so
// "great service" costs a page its credibility while "412 callouts in 2025, from
// our dispatch log" earns it. The placeholder now teaches that.
//
// The Experience interview is asked HERE, before the build, and not by the pipeline
// afterwards. It used to be the other way round: the operator filled in this whole
// screen, pressed Build on screen 4, and every queued page then parked itself at
// "waiting on your experience answers" — five questions they had never been shown,
// arriving after the one action they reasonably read as the last one. The questions
// are a pure function of the page kind chosen on screen 2, so there is nothing to
// wait for and nothing to pay for: they can simply be asked at the point the
// operator is already answering questions about the same pages.
//
// They are REQUIRED, because the pipeline's gate is a halt and not a warning. Making
// them optional here would only move the same dead end back to where it was.
//
// Design is a real choice between THREE real things: measure the client's actual
// site, replicate a design from any URL, or pick a template. Extraction wins when it
// succeeds, and says so.
//
// Replication is the one that closes QA 20 ("integrate Design Replicator into the
// Content module"). The replicator already measured a richer design system than the
// content analyzer does and threw it away; it now returns that profile on the job, so
// "replicate a design, then generate N pages on it" is ONE flow instead of two
// Playwright captures of the same URL. It carries the same copyright assertion the
// standalone Replicator enforces — never hardcoded, because the server checks it too.

import { useEffect, useMemo } from "react";
import { useExperienceQuestions, useSiteDesign } from "@/lib/hooks/content";
import { useReplicaJob, useReplicaRuns, useReplicate } from "@/lib/hooks/replica";
import { FRAMEWORKS, TEMPLATE_THEME_DEFAULTS, type Framework, type PageTemplate } from "@/lib/content";
import TemplateGallery from "@/components/content/TemplateGallery";
import { useToast, describeError } from "@/components/ui/Toast";
import { pageKind } from "@/lib/pageKinds";
import type { FlowState } from "./types";
import { lines } from "./types";

// A worked example per proof slot. Not decoration: the whole difference between an
// answer that clears the gate and one that gets cut is whether it names a checkable
// artifact, and showing one is far more effective than saying so.
const EXAMPLE: Record<string, string> = {
  founding_date: "Trading since March 2011 — Companies House registration 07612345",
  license_permit: "Texas Master Plumber licence M-41982, issued by the TSBPE",
  count_source: "412 emergency callouts in 2025, counted from our dispatch log",
  photo: "https://… — our own crew on the Rowlett slab job, 12 Feb 2025 (not stock)",
  review_source: "Google Business Profile — 187 reviews, 4.8 average, read at g.page/…",
  named_team: "Dave Whitmore, lead engineer, Gas Safe registration 512883",
  credential_source: "NICEIC Approved Contractor, certificate 2024/8812",
};

export default function StepBrief({
  state, patch,
}: {
  state: FlowState;
  patch: (p: Partial<FlowState>) => void;
}) {
  const kind = pageKind(state.kind);
  // Same query key as the orchestrator's own call, so the two share one fetch and
  // the Next button is gated on exactly the questions rendered below.
  const questions = useExperienceQuestions(kind.pageType);
  const asked = questions.data ?? [];
  const answered = asked.filter((q) => (state.experience[q.slotKey] ?? "").trim()).length;

  const extract = useSiteDesign();
  const replicate = useReplicate();
  const replicaJob = useReplicaJob(state.replicaJobId);
  const toast = useToast();

  // Replications this client ALREADY has, from the job ledger.
  //
  // The effect below adopts a design only from `state.replicaJobId` - a run this
  // screen started itself. So a replication launched from /admin/wordpress (the
  // Design Replicator card, which is where an operator naturally does it) left its
  // measured profile sitting in `job_runs.result` unread: the content job was then
  // generated with NO profile and silently fell back to the template default. The
  // work was paid for and invisible. The ledger has always held it - nothing here
  // was reading it.
  const pastRuns = useReplicaRuns(state.clientId || null);
  const reusable = useMemo(() => {
    const rows = pastRuns.data ?? [];
    return rows
      .map((r) => {
        const result = (r.result ?? {}) as { url?: string; design_profile?: unknown };
        return { run: r, url: result.url || "", profile: result.design_profile };
      })
      // A degraded run can finish having measured nothing; only offer runs that
      // actually carry a profile, so picking one can never be a no-op.
      .filter((x) => x.profile != null);
  }, [pastRuns.data]);

  // The replica job carries the measured design once it finishes. A degraded run that
  // produced no profile is NOT a silent failure — it falls back to measuring the
  // client's own site, and says so.
  const replicaStatus = replicaJob.data?.status;
  useEffect(() => {
    if (!state.replicaJobId || !replicaJob.data) return;
    const job = replicaJob.data;
    if (job.status !== "completed" && job.status !== "degraded") return;
    if (job.design_profile) {
      patch({ design: job.design_profile, designFrom: state.replicaUrl, replicaJobId: null });
      toast.success("Design replicated", `Colours, fonts and width taken from ${state.replicaUrl}.`);
    } else {
      patch({ replicaJobId: null });
      toast.error(
        "Replicated, but no design came back",
        "The run degraded before it measured a design system — measure the client's own site or pick a template instead.",
      );
    }
    // `patch` and `toast` are stable for this screen's lifetime; re-running on them
    // would re-fire the toast on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.replicaJobId, replicaStatus, replicaJob.data?.design_profile]);

  const runReplicate = () =>
    replicate.mutate(
      {
        client_id: state.clientId,
        url: state.replicaUrl.trim(),
        owner_confirmed_source: state.replicaOwnerConfirmed,
      },
      {
        onSuccess: (res) => patch({ replicaJobId: res.job_id }),
        onError: (e: unknown) => toast.error("Couldn't start the replication", describeError(e)),
      },
    );

  const runExtract = () =>
    extract.mutate(
      { site: state.siteDomain },
      {
        onSuccess: (res) => {
          if (res.status === "ok" && res.profile) {
            patch({ design: res.profile, designFrom: state.siteDomain });
            toast.success("Design measured", `Colours, fonts and section order taken from ${state.siteDomain}.`);
          } else {
            toast.error("Couldn't measure the site", res.reason || "The extractor degraded; a template will be used instead.");
          }
        },
        onError: (e: unknown) => toast.error("Couldn't measure the site", describeError(e)),
      },
    );

  return (
    <div style={{ display: "grid", gap: 16, maxWidth: 760 }}>
      <section className="card" style={{ padding: "var(--s-7)" }}>
        <div className="ct">What can these pages prove?</div>
        <div className="cs" style={{ margin: "4px 0 14px" }}>
          The writer may state these facts and nothing else. Anything vague gets cut rather
          than softened, so a number with a source beats an adjective every time.
        </div>
        <div className="fld">
          <label htmlFor="flow-proof">
            Proof points <span style={{ color: "var(--crit)" }}>*</span>
          </label>
          <textarea
            id="flow-proof" rows={4} value={state.proof}
            onChange={(e) => patch({ proof: e.target.value })}
            placeholder={"412 emergency callouts in 2025, from our dispatch log\nTexas Master Plumber licence M-41982\nMedian on-site time 47 minutes"}
          />
          <div className="fld-hint">
            One per line. {lines(state.proof).length === 0
              ? "At least one is required — pages cannot be written without something to stand on."
              : `${lines(state.proof).length} supplied.`}
          </div>
        </div>
        <div className="fld" style={{ marginTop: 12 }}>
          <label htmlFor="flow-services">Services offered</label>
          <textarea
            id="flow-services" rows={3} value={state.services}
            onChange={(e) => patch({ services: e.target.value })}
            placeholder={"Emergency leak repair\nWater heater replacement\nSlab leak detection"}
          />
        </div>
        <div className="fld-row" style={{ marginTop: 12 }}>
          <div className="fld">
            <label htmlFor="flow-testimonials">Testimonials (optional)</label>
            <textarea
              id="flow-testimonials" rows={3} value={state.testimonials}
              onChange={(e) => patch({ testimonials: e.target.value })}
              placeholder="One per line, with the customer's name if you have it"
            />
          </div>
          <div className="fld">
            <label htmlFor="flow-unique">Anything only you know (optional)</label>
            <textarea
              id="flow-unique" rows={3} value={state.uniqueData}
              onChange={(e) => patch({ uniqueData: e.target.value })}
              placeholder="Original data, internal stats, things competitors cannot say"
            />
          </div>
        </div>
      </section>

      <section className="card" style={{ padding: "var(--s-7)" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
          <div className="ct">What can you prove first-hand?</div>
          {asked.length > 0 && (
            <span className="cs" style={{ color: answered === asked.length ? "var(--ok)" : undefined }}>
              {answered} of {asked.length} answered
            </span>
          )}
        </div>
        <div className="cs" style={{ margin: "4px 0 14px", lineHeight: 1.6 }}>
          Every {kind.label.toLowerCase()} has to be able to back these {asked.length || "few"}{" "}
          claims, and the writer will not start without them. Answer once here and the whole
          batch is covered — <b>these are asked now precisely so the pages do not stop and
          ask later</b>. Name a number, a date, a document or a person; anything vague gets
          cut rather than softened.
        </div>

        {questions.isPending && <div className="cs">Working out what this page kind needs…</div>}
        {questions.isError && (
          <div className="fld-hint" style={{ color: "var(--warn)" }} role="alert">
            Couldn&apos;t load the proof questions. You can still continue — each page will
            ask them on its own Experience tab instead.
          </div>
        )}

        <div style={{ display: "grid", gap: 12 }}>
          {asked.map((q, i) => (
            <div className="fld" key={q.slotKey}>
              <label htmlFor={`flow-exp-${q.slotKey}`}>
                {i + 1}. {q.question} <span style={{ color: "var(--crit)" }}>*</span>
              </label>
              <textarea
                id={`flow-exp-${q.slotKey}`}
                rows={2}
                value={state.experience[q.slotKey] ?? ""}
                onChange={(e) =>
                  patch({ experience: { ...state.experience, [q.slotKey]: e.target.value } })
                }
                placeholder={EXAMPLE[q.slotKey] ?? ""}
              />
            </div>
          ))}
        </div>
      </section>

      <section className="card" style={{ padding: "var(--s-7)" }}>
        <div className="ct">How should the pages look?</div>
        <div className="cs" style={{ margin: "4px 0 14px" }}>
          Measuring the client&apos;s own site copies its palette, fonts and section order, so
          the new pages match what is already there. One paid call.
        </div>
        {state.design ? (
          <div role="status" style={{ display: "flex", gap: 9, alignItems: "center", color: "var(--ok)", fontSize: 13.5 }}>
            <span className="material-symbols-rounded">check_circle</span>
            Using the measured design from <b>{state.designFrom}</b>.
            <button
              type="button" className="mini-btn" style={{ marginLeft: 8 }}
              onClick={() => patch({ design: null, designFrom: "" })}
            >
              Use a template instead
            </button>
          </div>
        ) : (
          <>
            <button
              type="button" className="ghostbtn" onClick={runExtract}
              disabled={extract.isPending || !state.siteDomain}
              title={state.siteDomain ? undefined : "Measuring needs a site to measure"}
            >
              <span className="material-symbols-rounded">palette</span>
              {extract.isPending ? "Measuring the site…" : `Measure ${state.siteDomain || "the site"}`}
            </button>
            {/* Naming the cause, rather than a grey button with no explanation.
                A template below is the real alternative, so point at it. */}
            {!state.siteDomain && (
              <div className="cs" style={{ marginTop: 8 }}>
                No site chosen on screen 1, so there is nothing to measure. Pick a
                template below, or replicate a design from a URL.
              </div>
            )}

            {/* Reuse a design this client already paid to have measured. */}
            {reusable.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <div className="cs" style={{ marginBottom: 8 }}>
                  Or reuse a design already replicated for this client — no second
                  capture, no second charge.
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {reusable.map(({ run, url, profile }) => (
                    <button
                      key={run.id}
                      type="button"
                      className="chip"
                      title={url || "replicated design"}
                      onClick={() => {
                        patch({ design: profile as FlowState["design"], designFrom: url });
                        toast.success(
                          "Design reused",
                          "Colours, fonts and width taken from the earlier replication of " +
                            (url || "this client's site") + ".",
                        );
                      }}
                    >
                      <span className="material-symbols-rounded">history</span>
                      {url || "replicated design"}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Replicate a design from ANY url — the Design Replicator, in the flow
                that actually needs it. */}
            <div style={{ marginTop: 16 }}>
              <div className="cs" style={{ marginBottom: 8 }}>
                Or replicate a design from another page — its palette, fonts and width
                become the design these pages are built on.
              </div>
              <div className="fld">
                <label htmlFor="flow-replica-url">Page to replicate</label>
                <input
                  id="flow-replica-url" value={state.replicaUrl}
                  onChange={(e) => patch({ replicaUrl: e.target.value })}
                  placeholder="https://example.com/the-page-to-copy"
                />
              </div>
              <label style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13, margin: "6px 0 10px" }}>
                <input
                  type="checkbox" checked={state.replicaOwnerConfirmed}
                  onChange={(e) => patch({ replicaOwnerConfirmed: e.target.checked })}
                />
                <span>
                  I confirm the client owns this design, or is licensed to reuse it.
                  Replicating copies someone&apos;s layout and styling.
                </span>
              </label>
              <button
                type="button" className="ghostbtn"
                onClick={runReplicate}
                disabled={
                  replicate.isPending || !!state.replicaJobId ||
                  !state.replicaOwnerConfirmed || !state.clientId ||
                  !state.replicaUrl.trim().startsWith("http")
                }
              >
                <span className="material-symbols-rounded">content_copy</span>
                {state.replicaJobId
                  ? `Replicating… (${replicaStatus ?? "queued"})`
                  : replicate.isPending ? "Starting…" : "Replicate this design"}
              </button>
              {replicate.isError && (
                <div className="fld-hint" style={{ color: "var(--warn)" }} role="alert">
                  {(replicate.error as Error)?.message ?? "Couldn't start the replication."}
                </div>
              )}
            </div>
          </>
        )}
        {!state.design && (
          <>
            <div className="cs" style={{ margin: "16px 0 10px" }}>
              Or pick a template and tune it. Leave it on Auto to use the blueprint that
              belongs to the page kind you chose.
            </div>
            <TemplateGallery
              value={state.template}
              theme={state.theme}
              onSelect={(tpl) => patch({
                template: tpl,
                // Switching to a NEW template seeds its curated theme; re-picking
                // the same one keeps whatever the operator has customised.
                ...(tpl !== "Auto" && tpl !== state.template
                  ? { theme: TEMPLATE_THEME_DEFAULTS[tpl as PageTemplate] }
                  : {}),
              })}
              onTheme={(theme) => patch({ theme })}
            />
          </>
        )}
      </section>

      <section className="card" style={{ padding: "var(--s-7)" }}>
        <div className="ct">Copywriting framework</div>
        <div className="cs" style={{ margin: "4px 0 12px" }}>
          The persuasive structure the body follows. Auto picks the one that suits the page kind.
        </div>
        <div className="fld" style={{ maxWidth: 260 }}>
          <label htmlFor="flow-framework">Framework</label>
          <select
            id="flow-framework" value={state.framework}
            onChange={(e) => patch({ framework: e.target.value as Framework | "Auto" })}
          >
            <option value="Auto">Auto — choose for me</option>
            {FRAMEWORKS.map((f) => (
              <option key={f.key} value={f.key}>{f.key} — {f.expansion}</option>
            ))}
          </select>
        </div>
      </section>
    </div>
  );
}
