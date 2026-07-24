"use client";

import { useState } from "react";
import { useStartOnboarding } from "@/lib/hooks/tools";
import { ActionCard, ClientSelect, PermNote, ToolActionResult } from "./shared";
import type { ToolActionProps } from "./registry";

/** Client Onboarding — start an activation run for a client and seed its checklist
 *  (POST /client-onboarding/runs). One live run per client; the board below tracks
 *  each step's owner and status. */
export default function ClientOnboardingActions({ accent }: ToolActionProps) {
  const [clientId, setClientId] = useState("");
  const start = useStartOnboarding();

  const canRun = !!clientId && !start.isPending;
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canRun) return;
    start.mutate({ client_id: clientId });
  };

  return (
    <ActionCard
      title="Start onboarding"
      subtitle="Seed the activation checklist and begin collecting client access."
      icon="person_add"
      accent={accent}
    >
      <form onSubmit={submit}>
        <ClientSelect value={clientId} onChange={setClientId} />
        <button type="submit" className="primary-btn wide" disabled={!canRun}>
          <span className="material-symbols-rounded">person_add</span>
          {start.isPending ? "Starting…" : "Start onboarding"}
        </button>
      </form>
      <ToolActionResult
        error={start.error}
        success={start.isSuccess ? "Onboarding started — the 11-step checklist is now on the board." : null}
      />
      <PermNote>Starting an onboarding run needs owner / admin / manager access.</PermNote>
    </ActionCard>
  );
}
