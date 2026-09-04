"use client";

// The content flow: four screens, one job each, the step in the URL.
//
// It replaces a five-step wizard that lived INLINE on the content board, below
// the KPIs and above the pipeline and the review queue - so a single scrolling
// page carried creating, watching and approving at once, and the operator's own
// summary of it was that there was no logic to it.
//
// Each screen states its own exit condition, and Next is disabled until it is
// met rather than failing later. Nothing here spends money except the two
// explicitly-labelled paid actions on screens 2 and 3.

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { pageKind } from "@/lib/pageKinds";
import { useExperienceQuestions } from "@/lib/hooks/content";
import StepClientSite from "./StepClientSite";
import StepPages from "./StepPages";
import StepBrief from "./StepBrief";
import StepLaunch from "./StepLaunch";
import { EMPTY_FLOW, lines, type FlowState } from "./types";

const STEPS = [
  { key: 1, label: "Client & site", hint: "Who it is for, and where it goes" },
  { key: 2, label: "Pages", hint: "What to build, and why those" },
  { key: 3, label: "Facts & look", hint: "What the pages may claim" },
  { key: 4, label: "Review & build", hint: "Confirm, then queue" },
] as const;

export default function NewContentFlow() {
  const router = useRouter();
  const params = useSearchParams();
  const [state, setState] = useState<FlowState>(EMPTY_FLOW);
  const [codes, setCodes] = useState<string[] | null>(null);

  // The proof questions this page kind requires. Fetched at the ORCHESTRATOR so the
  // Next button is gated on the same list screen 3 renders (one shared query), and so
  // it is already in cache by the time the operator reaches that screen.
  const questions = useExperienceQuestions(state.kind ? pageKind(state.kind).pageType : null);
  const asked = useMemo(() => questions.data ?? [], [questions.data]);

  const raw = Number(params?.get("step") ?? 1);
  const step = Number.isFinite(raw) && raw >= 1 && raw <= 4 ? raw : 1;

  const patch = useCallback(
    (p: Partial<FlowState>) => setState((s) => ({ ...s, ...p })),
    [],
  );

  const go = (n: number) => {
    const q = new URLSearchParams(params?.toString() ?? "");
    q.set("step", String(n));
    router.push(`/admin/content/new?${q}`);
  };

  // Each screen's exit condition, stated once and used for BOTH the button and
  // the sentence explaining why it is disabled.
  const blocker = useMemo(() => {
    if (step === 1) {
      // The CLIENT is the only thing screen 1 must produce. The site used to be
      // required too, which made the flow unexitable for a client with no `sites`
      // row - and the backend never needed one: site_domain is optional on both
      // creation schemas and generation completes without it.
      if (!state.clientId) return "Choose a client to continue.";
      return null;
    }
    if (step === 2) return state.picks.length ? null : "Select at least one page to build.";
    if (step === 3) {
      if (!lines(state.proof).length) {
        return "Add at least one proof point — the pages may state these facts and nothing else.";
      }
      // The Experience interview is a HALT in the pipeline, not a warning, so letting
      // the operator past it here would only move the dead end back to where it was:
      // a queued page parked on questions nobody had been shown. A failed fetch leaves
      // `asked` empty and does not block - the per-page tab still catches it.
      const outstanding = asked.filter((q) => !(state.experience[q.slotKey] ?? "").trim());
      if (outstanding.length) {
        return `Answer the ${outstanding.length} remaining proof question${outstanding.length === 1 ? "" : "s"} — the writer will not start without them.`;
      }
      return null;
    }
    return null;
  }, [step, state, asked]);

  // A truth that does NOT block, and so cannot be said by `blocker`.
  //
  // If the questions never loaded, `asked` is empty and the gate below silently
  // passes - a failed request wearing the face of "nothing is required". That is
  // survivable (each page still asks on its own Experience tab, so nothing gets
  // written on invented facts) but it must not be silent, because the operator would
  // otherwise reach screen 4 believing the interview was done.
  const notice =
    step === 3 && questions.isError
      ? "Couldn't load the proof questions, so this screen can't check them. Each page will ask for them on its own Experience tab instead."
      : null;

  // Rendered INLINE, not through a `const Body = () => …` defined in this function.
  //
  // That shape looks tidier and is a remount bug: a component declared during render
  // is a NEW type on every render, so React tears the whole step subtree down and
  // builds it again each time this component re-renders — which is every keystroke,
  // because every field patches state held up here. Everything the step owned
  // LOCALLY was destroyed with it: screen 2's source tabs snapped back to "Keyword
  // bank" mid-entry, and screen 3's textareas lost focus after each character.
  const body =
    step === 1 ? <StepClientSite state={state} patch={patch} />
    : step === 2 ? <StepPages state={state} patch={patch} />
    : step === 3 ? <StepBrief state={state} patch={patch} />
    : <StepLaunch state={state} codes={codes} onDone={setCodes} />;

  return (
    <div className="tw">
      <ol className="wiz-steps co-wiz-steps" style={{ marginBottom: 22 }}>
        {STEPS.map((s) => {
          const done = s.key < step;
          return (
            <li key={s.key} className={`wiz-step ${done ? "done" : s.key === step ? "on" : ""}`}>
              <span className="wiz-dot">
                {done ? <span className="material-symbols-rounded">check</span> : s.key}
              </span>
              <span className="wiz-slabel">
                {s.label}
                <span className="cs" style={{ display: "block", fontWeight: 400 }}>{s.hint}</span>
              </span>
            </li>
          );
        })}
      </ol>

      {body}

      {!codes && (
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 24 }}>
          {step > 1 ? (
            <button type="button" className="ghostbtn" onClick={() => go(step - 1)}>
              <span className="material-symbols-rounded">arrow_back</span>Back
            </button>
          ) : (
            <Link className="ghostbtn" href="/admin/content">
              <span className="material-symbols-rounded">arrow_back</span>Cancel
            </Link>
          )}
          {step < 4 && (
            <>
              <button
                type="button" className="primary-btn"
                onClick={() => go(step + 1)}
                disabled={Boolean(blocker)}
              >
                Next: {STEPS[step].label}
                <span className="material-symbols-rounded">arrow_forward</span>
              </button>
              {blocker && <span className="cs">{blocker}</span>}
              {!blocker && notice && (
                <span className="cs" style={{ color: "var(--warn)" }} role="status">{notice}</span>
              )}
            </>
          )}
          {step >= 2 && !blocker && (
            <span className="cs" style={{ marginLeft: "auto" }}>
              {state.picks.length} × {pageKind(state.kind).label.toLowerCase()} for {state.clientName}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
