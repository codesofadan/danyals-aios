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
import { useExperienceQuestions, useGenerateFromResearch } from "@/lib/hooks/content";
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
  // Shared query key with screen 3, so this is the cached list rather than a refetch.
  // Screen 3's Next button already enforces this; repeating it here closes the one
  // way round it, which is deep-linking straight to ?step=4.
  const asked = useExperienceQuestions(kind.pageType).data ?? [];
  const answered = asked.filter((q) => (state.experience[q.slotKey] ?? "").trim()).length;
  const proofMissing = asked.length > 0 && answered < asked.length;
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
        //
        // Sent ONLY when it is a registered site: `_chosen_site` 400s on a domain
        // that is not registered to the client, so a domain merely derived from the
        // business profile (used for research) must be omitted here. Omitted, the
        // backend applies its own fallback - first registered site, else none.
        ...(state.siteRegistered && state.siteDomain ? { siteDomain: state.siteDomain } : {}),
        framework: state.framework,
        // An explicit template wins over the kind's default blueprint; "Auto"
        // falls back to the blueprint the chosen page kind derives.
        template: state.template !== "Auto" ? state.template : kind.template,
        target: state.target,
        proofPoints: lines(state.proof).slice(0, 12),
        testimonials: lines(state.testimonials).slice(0, 12),
        uniqueData: lines(state.uniqueData).slice(0, 12),
        services: lines(state.services).slice(0, 20),
        // The Experience interview, answered on screen 3. It rides on the job so the
        // pipeline's SME stage SEEDS the dossier rather than halting to ask - the
        // whole reason the interview moved to the front. Only non-empty answers are
        // sent: an empty string is not an answer, and the gate would (rightly) still
        // stop the page rather than treat a blank as satisfied.
        experience: Object.fromEntries(
          Object.entries(state.experience)
            .map(([k, v]) => [k, String(v).trim()])
            .filter(([, v]) => v),
        ),
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
              Each page now runs research, drafting and QA on its own. Your proof answers
              travel with them, so they go straight to writing rather than stopping to ask.
              <b> Nothing reaches the site without your review.</b> If a page does need
              something you have not supplied, it says so on its Experience tab.
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
                    <Link className="mini-btn" href={`/admin/content/${c}`}>
                      Follow it
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
          {/* Say which site will actually be published to, including the two cases
              where it is not the one on screen 1 - finding that out afterwards is
              how a page ends up on the wrong site. */}
          <dt className="cs">On</dt>
          <dd style={{ margin: 0 }}>
            {state.siteRegistered && state.siteDomain
              ? state.siteDomain
              : state.siteDomain
                ? `${state.siteDomain} (research only — publishes to their registered site)`
                : "No site chosen — saved for review, published later"}
          </dd>
          <dt className="cs">Grounded in</dt>
          <dd style={{ margin: 0 }}>{facts} proof point{facts === 1 ? "" : "s"}</dd>
          {/* Say that the interview is DONE. Its absence is what used to surface as a
              parked page ten minutes later, so its presence is worth stating here. */}
          {asked.length > 0 && (
            <>
              <dt className="cs">Experience</dt>
              <dd style={{ margin: 0, color: proofMissing ? "var(--warn)" : "var(--ok)" }}>
                {answered} of {asked.length} answered
                {proofMissing ? " — the rest will be asked per page" : " — no page will stop to ask"}
              </dd>
            </>
          )}
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
          disabled={
            generate.isPending || halted || state.picks.length === 0 || facts === 0 || proofMissing
          }
        >
          <span className="material-symbols-rounded">rocket_launch</span>
          {generate.isPending ? "Queueing…" : `Build ${state.picks.length} page${state.picks.length === 1 ? "" : "s"}`}
        </button>
        <div className="cs" style={{ marginTop: 8 }}>
          {facts === 0
            ? "Add at least one proof point first — a page with nothing to stand on will not be written."
            : proofMissing
              ? `Go back to Facts & look and answer the remaining ${asked.length - answered} proof question${asked.length - answered === 1 ? "" : "s"} — the writer will not start without them.`
              : "Nothing publishes without your approval."}
        </div>
      </div>
    </div>
  );
}
