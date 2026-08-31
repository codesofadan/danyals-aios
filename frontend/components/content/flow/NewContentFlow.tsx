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
      return lines(state.proof).length ? null : "Add at least one proof point — the pages may state these facts and nothing else.";
    }
    return null;
  }, [step, state]);

  const Body = () => {
    if (step === 1) return <StepClientSite state={state} patch={patch} />;
    if (step === 2) return <StepPages state={state} patch={patch} />;
    if (step === 3) return <StepBrief state={state} patch={patch} />;
    return <StepLaunch state={state} codes={codes} onDone={setCodes} />;
  };

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

      <Body />

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
