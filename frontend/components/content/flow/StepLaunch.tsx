"use client";

// Screen 4 — what is about to happen, what it costs, and then commit.
//
// The old flow's commit was a button among other buttons. This states the whole
// consequence first: how many pages, for whom, on which site, from which facts -
// and that every one of them stops for a human before anything reaches the site.
//
// It also says plainly what happens NEXT, because the doctrine engine holds each
// page until its first-party facts are supplied, and an operator who does not
// expect that reads a held page as a broken one.

import Link from "next/link";
import { useSpendHalted } from "@/lib/hooks/cost";
import { useGenerateFromResearch } from "@/lib/hooks/content";
import { profileFromTemplate } from "@/lib/content";
import { pageKind } from "@/lib/pageKinds";
import { useToast, describeError } from "@/components/ui/Toast";
import type { FlowState } from "./types";
import { lines } from "./types";

export default function StepLaunch({
  state, onDone, codes,
}: {
  state: FlowState;
  onDone: (codes: string[]) => void;
  codes: string[] | null;
}) {
  const { halted } = useSpendHalted();
  const generate = useGenerateFromResearch();
  const toast = useToast();
  const kind = pageKind(state.kind);
  const designToSend =
    state.design ??
    (state.template !== "Auto" ? profileFromTemplate(state.template, state.theme) : null);

  const launch = () =>
    generate.mutate(
      {
        items: state.picks,
        clientId: state.clientId,
        // The site chosen on screen 1. Without this the backend takes the client's
        // FIRST site, so the picker changed what was researched and nothing else -
        // the page then published wherever happened to be first.
        siteDomain: state.siteDomain,
        framework: state.framework,
        // An explicit template wins over the kind's default blueprint; "Auto"
        // falls back to the blueprint the chosen page kind derives.
        template: state.template !== "Auto" ? state.template : kind.template,
        target: state.target,
        proofPoints: lines(state.proof).slice(0, 12),
        testimonials: lines(state.testimonials).slice(0, 12),
        uniqueData: lines(state.uniqueData).slice(0, 12),
        services: lines(state.services).slice(0, 20),
        // A MEASURED profile beats a template every time - it is the client's
        // real site rather than a guess at it. A picked template synthesises one
        // so the colours and fonts the operator chose actually travel.
        ...(designToSend ? { designProfile: designToSend } : {}),
      },
      {
        onSuccess: (r) => {
          onDone(r.jobs);
          toast.success(
            `${r.jobs.length} page${r.jobs.length === 1 ? "" : "s"} queued`,
            "Each one stops for your review before anything reaches the site.",
          );
        },
        onError: (e: unknown) => toast.error("Couldn't queue the pages", describeError(e)),
      },
    );

  if (codes) {
    return (
      <section className="card" style={{ padding: "var(--s-7)", maxWidth: 640 }}>
        <div style={{ display: "flex", gap: 11, alignItems: "flex-start" }}>
          <span className="material-symbols-rounded" style={{ fontSize: 26, color: "var(--ok)" }}>
            check_circle
          </span>
          <div>
            <div className="ct">{codes.length} page{codes.length === 1 ? "" : "s"} queued</div>
            <div className="cs" style={{ marginTop: 6, lineHeight: 1.6 }}>
              Each page now runs research, drafting and QA on its own. <b>Most will stop and
              ask you for first-party facts</b> before they will write — that is the gate that
              stops the writer inventing credentials, and it is answered on each page&apos;s
              Experience tab.
            </div>
          </div>
        </div>
        <div className="tbl-wrap" style={{ marginTop: 16 }}>
          <table className="tbl">
            <tbody>
              {codes.map((c) => (
                <tr key={c}>
                  <td><Link href={`/admin/content/${c}`}><strong>{c}</strong></Link></td>
                  <td style={{ textAlign: "right" }}>
                    <Link className="mini-btn" href={`/admin/content/${c}?tab=experience`}>
                      Answer its questions
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
          <Link className="primary-btn" href="/admin/content">Back to the board</Link>
          <Link className="ghostbtn" href="/admin/content/new">Start another set</Link>
        </div>
      </section>
    );
  }

  const facts = lines(state.proof).length;
  return (
    <div style={{ display: "grid", gap: 16, maxWidth: 700 }}>
      <section className="card" style={{ padding: "var(--s-7)" }}>
        <div className="ct">About to build</div>
        <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "9px 18px", margin: "14px 0 0" }}>
          <dt className="cs">Pages</dt>
          <dd style={{ margin: 0, fontWeight: 700, color: "var(--ink)" }}>
            {state.picks.length} × {kind.label.toLowerCase()}
          </dd>
          <dt className="cs">For</dt>
          <dd style={{ margin: 0 }}>{state.clientName || "—"}</dd>
          <dt className="cs">On</dt>
          <dd style={{ margin: 0 }}>{state.siteDomain || "—"}</dd>
          <dt className="cs">Grounded in</dt>
          <dd style={{ margin: 0 }}>{facts} proof point{facts === 1 ? "" : "s"}</dd>
          <dt className="cs">Look</dt>
          <dd style={{ margin: 0 }}>
            {state.design
              ? state.designFrom && state.designFrom === state.replicaUrl
                ? `Replicated from ${state.designFrom}`
                : `Measured from ${state.designFrom}`
              : state.template !== "Auto"
                ? `${state.template.replace(/_/g, " ")} template, recoloured`
                : `${kind.label} blueprint`}
          </dd>
          <dt className="cs">Publishes to</dt>
          <dd style={{ margin: 0 }}>{state.target} — as a draft, never live</dd>
        </dl>
      </section>

      {halted && (
        <div role="alert" className="co-degrade">
          <span className="material-symbols-rounded">pause_circle</span>
          <div>
            <b>API spend is halted</b>
            <div className="cs">
              Nothing can be written while the halt is on. Lift it on Cost Controls, then come back —
              your selections are still here.
            </div>
          </div>
        </div>
      )}

      <div>
        <button
          type="button" className="primary-btn"
          onClick={launch}
          disabled={generate.isPending || halted || state.picks.length === 0 || facts === 0}
        >
          <span className="material-symbols-rounded">rocket_launch</span>
          {generate.isPending ? "Queueing…" : `Build ${state.picks.length} page${state.picks.length === 1 ? "" : "s"}`}
        </button>
        <div className="cs" style={{ marginTop: 8 }}>
          {facts === 0
            ? "Add at least one proof point first — a page with nothing to stand on will not be written."
            : "Nothing publishes without your approval."}
        </div>
      </div>
    </div>
  );
}
