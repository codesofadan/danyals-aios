"use client";

// One content job, every concern - the detail page content jobs never had.
//
// GET /content/jobs/{code} existed unused, so a job's deep concerns (draft,
// schema, QA, keywords) lived only inside a review modal, the approve buttons
// showed NO quality score, republish had no surface at all, and the fourteen
// pipeline stages the worker streams rendered as a single word. This page is
// the spec's DETAIL archetype for the content module:
//
//   - Draft & data: the proven ReviewPreview renderer (article/outline/schema/
//     keywords/links/QA) embedded read-only; approval happens in the HEADER.
//   - Process: the canonical pipeline as a timeline against the job's live
//     stage. Per-stage history is not stored server-side, so done/pending are
//     DERIVED from position relative to the current stage - the code says so
//     rather than pretending to a record it does not have.
//
// APPROVAL SEES THE SCORE (decision D-4's unbuilt half). The approve dialog
// renders the QA verdict inline; approving a draft whose scorecard FAILED
// requires typing PUBLISH. The score stays advisory - the human's approval is
// the gate - but blind approval stops being the default path.

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import type { ContentJob } from "@/lib/content";
import {
  useContentJob,
  useContentKeywords,
  useContentLinks,
  useContentQa,
  useRepublishJob,
  useReviewContentJob,
} from "@/lib/hooks/content";
import DetailShell from "@/components/ui/DetailShell";
import StageTimeline, { type Stage } from "@/components/ui/StageTimeline";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import QueryGuard from "@/components/ui/QueryGuard";
import { qaVerdict } from "@/lib/content";
import ExperiencePanel from "./ExperiencePanel";
import { useToast } from "@/components/ui/Toast";
import ReviewPreview from "./ReviewPreview";

// The canonical pipeline, as the operator should read it. The worker's six
// research sub-stages all present under one label (mirrors _STAGE_LABEL in
// workers/tasks/content.py); "Review" is the human gate; "Publish" the leg
// republish re-runs.
const PIPELINE_VIEW: { key: string; label: string; detail: string }[] = [
  { key: "Research", label: "Research", detail: "SERP pull, clustering, format, fan-out, winnability, teardown" },
  { key: "Outline", label: "Outline", detail: "headings, layout and meta planned" },
  { key: "Draft", label: "Draft", detail: "the article, written against the brief" },
  { key: "Titles & meta", label: "Titles & meta", detail: "title tag and description" },
  { key: "Schema", label: "Schema", detail: "JSON-LD built and validated" },
  { key: "Images", label: "Images", detail: "planned imagery, when a provider is configured" },
  { key: "Assemble", label: "Assemble", detail: "layout picked, page put together" },
  { key: "QA", label: "QA", detail: "the 14-dimension scorecard (advisory)" },
  { key: "Review", label: "Review", detail: "the human gate - the one enforced boundary" },
  { key: "Publish", label: "Publish", detail: "plugin → REST → artifact" },
];

function stagesFor(job: ContentJob): Stage[] {
  const current = job.stage || "";
  const idx = PIPELINE_VIEW.findIndex((s) => current.startsWith(s.key));
  const failed = job.status === "failed";
  const finished = job.status === "done" || job.status === "degraded";
  return PIPELINE_VIEW.map((s, i) => {
    let state: Stage["state"] = "pending";
    if (finished) state = "done";
    else if (idx === -1) state = job.status === "queued" ? "pending" : i === 0 ? "running" : "pending";
    else if (i < idx) state = "done";
    else if (i === idx) state = failed ? "failed" : "running";
    return { key: s.key, label: s.label, state, detail: i === idx && current !== s.key ? current : s.detail };
  });
}

/** The published page's URL, when the done job's stage label carries one. */
function liveUrl(job: ContentJob): string | null {
  if (job.status !== "done") return null;
  const m = job.stage.match(/https?:\/\/\S+/);
  return m ? m[0] : null;
}

function csvEscape(v: unknown): string {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export default function ContentJobDetail({ code }: { code: string }) {
  const router = useRouter();
  const toast = useToast();
  const jobQ = useContentJob(code);
  const qaQ = useContentQa(code);
  const keywordsQ = useContentKeywords(code);
  const linksQ = useContentLinks(code);
  const review = useReviewContentJob();
  const republish = useRepublishJob();

  const [prompt, setPrompt] = useState<null | "approve" | "reject" | "republish">(null);
  const [editNote, setEditNote] = useState("");
  const [editing, setEditing] = useState(false);

  const job = jobQ.data;
  const qa = qaQ.data?.qa ?? null;
  // Scored only when a real number came back; see qaVerdict.
  const verdict = qaVerdict(qa);

  // The CSV the operator asked for: the job's keyword map + internal links +
  // entity coverage, one file, built from data already on screen.
  const exportCsv = useMemo(() => {
    return () => {
      // The real payload shapes (lib/hooks/content.ts): keywords is a keyed plan
      // (primary / secondary / semantic_entities / questions), links a nested list.
      const rows: string[] = ["section,item,value"];
      const kw = keywordsQ.data?.keywords ?? null;
      if (kw) {
        if (kw.primary) rows.push(["keyword", "primary", csvEscape(kw.primary)].join(","));
        for (const t of kw.secondary ?? []) rows.push(["keyword", "secondary", csvEscape(t)].join(","));
        for (const t of kw.semantic_entities ?? []) rows.push(["entity", "semantic", csvEscape(t)].join(","));
        for (const q of kw.questions ?? []) rows.push(["question", "faq", csvEscape(q)].join(","));
        if (kw.intent) rows.push(["keyword", "intent", csvEscape(kw.intent)].join(","));
      }
      for (const l of linksQ.data?.links?.links ?? []) {
        rows.push(["internal_link", csvEscape(l.anchor), csvEscape(l.url)].join(","));
      }
      const blob = new Blob([rows.join("\n")], { type: "text/csv" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${code}-content.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    };
  }, [keywordsQ.data, linksQ.data, code]);

  if (jobQ.isError) {
    return (
      <section className="card" style={{ maxWidth: 520, margin: "48px auto", textAlign: "center", padding: 28 }}>
        <div className="ct">Couldn&apos;t load job {code}</div>
        <div className="cs" style={{ marginTop: 8 }}>
          It may not exist, or the request failed. <Link href="/admin/content">Back to Content</Link>.
        </div>
      </section>
    );
  }
  if (!job) {
    return <div role="status" style={{ padding: 48, textAlign: "center", color: "var(--muted)" }}>Loading job {code}…</div>;
  }

  const inReview = job.status === "needs_review";
  const republishable = job.status === "done" || job.status === "degraded";
  const url = liveUrl(job);
  // Only a REAL verdict can fail. An unscored page is not a failed one, and
  // making the operator type PUBLISH for a failure nobody measured is the
  // over-confirmation that trains people to click through the dialogs that matter.
  const qaFailed = verdict !== null && !verdict.passed;

  return (
    <>
      <DetailShell
        eyebrow="Content job"
        title={job.topic}
        statusPill={
          <span className={`status-pill ${job.status === "done" ? "ok" : job.status === "failed" ? "crit" : job.status === "degraded" ? "warn" : "mut"}`}>
            {job.status.replace("_", " ")}
          </span>
        }
        facts={[
          { label: "Client", value: job.client },
          { label: "Page type", value: job.pageType },
          { label: "Framework", value: job.framework },
          { label: "Words", value: job.words ? job.words.toLocaleString() : "—" },
          { label: "Cost", value: `$${job.cost.toFixed(2)}` },
          {
            label: "QA",
            // Unscored is not "failed". `qa_score` is `{}` when the gate produced
            // no verdict, and `{}` is truthy - this used to render "NaN · failed".
            value: verdict
              ? `${Math.round(verdict.total)} · ${verdict.passed ? "passed" : "failed"} (advisory)`
              : "not scored",
          },
        ]}
        actions={
          <>
            {inReview && (
              <>
                <button type="button" className="primary-btn" onClick={() => setPrompt("approve")}>
                  <span className="material-symbols-rounded">task_alt</span>Approve
                </button>
                <button type="button" className="ghostbtn" onClick={() => setEditing(true)}>
                  Request edits
                </button>
                <button type="button" className="ghostbtn" onClick={() => setPrompt("reject")}>
                  Reject
                </button>
              </>
            )}
            {republishable && (
              <button type="button" className="ghostbtn" onClick={() => setPrompt("republish")}>
                <span className="material-symbols-rounded">publish</span>Republish
              </button>
            )}
            {url && (
              <a className="ghostbtn" href={url} target="_blank" rel="noopener noreferrer">
                <span className="material-symbols-rounded">open_in_new</span>Open live page
              </a>
            )}
            <button type="button" className="ghostbtn" onClick={exportCsv}>
              <span className="material-symbols-rounded">download</span>Export CSV
            </button>
          </>
        }
        tabs={[
          { key: "draft", label: "Draft & data", icon: "article" },
          { key: "process", label: "Process", icon: "route" },
          // The gate that holds this page. Placed beside Process because that is
          // where an operator looks when they want to know why nothing is moving.
          { key: "experience", label: "Experience", icon: "quiz" },
        ]}
      >
        {(tab) =>
          tab === "experience" ? (
            <ExperiencePanel code={code} />
          ) : tab === "process" ? (
            <section className="card" style={{ padding: "var(--s-7)" }}>
              <div className="cs" style={{ marginBottom: "var(--s-6)", maxWidth: 560 }}>
                The pipeline, against this job&apos;s live stage
                {job.stage ? <> (currently <b>{job.stage}</b>)</> : null}. Completed and
                pending are derived from position — the worker streams its current stage,
                not a per-stage history.
              </div>
              <StageTimeline stages={stagesFor(job)} />
            </section>
          ) : (
            // The proven renderer, read-only: approval lives in THIS page's
            // header so there is exactly one action surface.
            <ReviewPreview job={job} onAction={() => undefined} hideActions />
          )
        }
      </DetailShell>

      <ConfirmDialog
        open={prompt === "approve"}
        tone={qaFailed ? "danger" : "caution"}
        title="Approve and publish this draft?"
        body={
          <QueryGuard queries={[qaQ]} label="the QA verdict" minHeight={60}>
            {verdict ? (
              <>
                The QA scorecard reads <b>{Math.round(verdict.total)} / 100</b> —{" "}
                <b>{verdict.passed ? "passed" : "FAILED"}</b>
                {qa?.provisional ? " (provisional weights)" : ""}. It is advisory: your
                approval is the gate, and the page publishes to{" "}
                <b>{job.client}</b>&apos;s live site.
              </>
            ) : (
              <>No QA scorecard is stored for this draft. Your approval is the only gate.</>
            )}
          </QueryGuard>
        }
        reassurance={qaFailed ? undefined : "You can request edits instead — the writer re-drafts under your instruction."}
        confirmLabel="Approve & publish"
        typeToConfirm={qaFailed ? "PUBLISH" : undefined}
        pending={review.isPending}
        onCancel={() => setPrompt(null)}
        onConfirm={() =>
          review.mutate(
            { code, action: "approve" },
            {
              onSuccess: () => {
                setPrompt(null);
                toast.success(`Approved ${code} — publishing to ${job.client}`);
              },
              onError: (e) => toast.fromError(`Couldn't approve ${code}`, e),
            },
          )
        }
      />

      <ConfirmDialog
        open={prompt === "reject"}
        tone="danger"
        title="Reject this draft?"
        body={<>The job moves to <b>rejected</b> and nothing is published. The draft and its research are kept.</>}
        confirmLabel="Reject draft"
        pending={review.isPending}
        onCancel={() => setPrompt(null)}
        onConfirm={() =>
          review.mutate(
            { code, action: "reject" },
            {
              onSuccess: () => {
                setPrompt(null);
                toast.info(`Rejected ${code}`);
                router.push("/admin/content");
              },
              onError: (e) => toast.fromError(`Couldn't reject ${code}`, e),
            },
          )
        }
      />

      <ConfirmDialog
        open={prompt === "republish"}
        title="Republish this page?"
        body={
          <>
            The publish leg runs again for <b>{job.client}</b> — plugin, then REST, then
            artifact. Use it when a degraded job never reached the site, or a live page
            was lost site-side.
          </>
        }
        reassurance="The draft is not regenerated and no research is re-run — only the publish step."
        confirmLabel="Republish"
        pending={republish.isPending}
        onCancel={() => setPrompt(null)}
        onConfirm={() =>
          republish.mutate(code, {
            onSuccess: () => {
              setPrompt(null);
              toast.success(`Republishing ${code}`);
            },
            onError: (e) => toast.fromError(`Couldn't republish ${code}`, e),
          })
        }
      />

      {editing && (
        <ConfirmDialog
          open
          tone="normal"
          title="Request edits"
          body={
            <div className="fld">
              <label htmlFor="edit-note">What should change? The writer re-drafts under this instruction.</label>
              <textarea
                id="edit-note"
                rows={4}
                value={editNote}
                onChange={(e) => setEditNote(e.target.value)}
                style={{ width: "100%", marginTop: "var(--s-2)" }}
              />
            </div>
          }
          confirmLabel="Send back for edits"
          pending={review.isPending}
          onCancel={() => setEditing(false)}
          onConfirm={() =>
            review.mutate(
              { code, action: "edit", note: editNote.trim() || undefined },
              {
                onSuccess: () => {
                  setEditing(false);
                  setEditNote("");
                  toast.success(`${code} sent back with your instruction`);
                },
                onError: (e) => toast.fromError(`Couldn't request edits on ${code}`, e),
              },
            )
          }
        />
      )}
    </>
  );
}
