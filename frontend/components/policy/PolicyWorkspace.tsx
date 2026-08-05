"use client";

import AskBox from "./AskBox";
import ChangeFeed from "./ChangeFeed";
import KnowledgeBase from "./KnowledgeBase";
import Recommendations from "./Recommendations";
import { useGeneratePolicyBrief } from "@/lib/hooks/policy";
import { useSpendHalted } from "@/lib/hooks/cost";

export default function PolicyWorkspace() {
  return (
    <div className="pr-wrap">
      <div className="row-single">
        <BriefBar />
      </div>

      <div className="row-single">
        <AskBox />
      </div>

      <div className="row-single">
        <Recommendations />
      </div>

      <div className="row-single">
        <ChangeFeed />
      </div>

      <div className="row-single">
        <KnowledgeBase />
      </div>
    </div>
  );
}

// The daily-brief control: Policy Radar surfaces 6 fresh, Anthropic-researched policy
// items each day automatically. Leads can force a refresh here (a paid action, so it is
// disabled while the global API-spend halt is engaged). The brief is generated async, so
// the button reports "requested" and the panels below refresh a few seconds later.
function BriefBar() {
  const gen = useGeneratePolicyBrief();
  const { halted } = useSpendHalted();

  return (
    <section className="card pr-brief">
      <div className="card-h">
        <div>
          <div className="ct">
            <span className="material-symbols-rounded pr-ask-star">auto_awesome</span>
            Daily policy brief
          </div>
          <div className="cs">
            Six current Google Search policy &amp; algorithm developments, researched fresh
            every day by Claude. Ask any of them in depth above.
          </div>
        </div>
        <button
          className="pr-ask-btn"
          type="button"
          onClick={() => !gen.isPending && !halted && gen.mutate()}
          disabled={gen.isPending || halted}
        >
          {gen.isPending ? "Requesting…" : "Generate today's brief"}
        </button>
      </div>

      {halted && (
        <div className="pr-empty pr-ask-msg" role="status">
          API spend is halted, so generating a brief is paused. Resume spend in Cost Controls to run one.
        </div>
      )}

      {gen.isSuccess && (
        <div className="pr-empty pr-ask-msg" role="status">
          Requested — Claude is researching today&apos;s brief. The panels below will refresh in a few seconds.
        </div>
      )}

      {gen.isError && (
        <div className="pr-empty pr-ask-msg">
          Couldn&apos;t start the brief. {(gen.error as Error)?.message ?? "Leads only — try again"}.
        </div>
      )}
    </section>
  );
}
