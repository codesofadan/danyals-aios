"use client";

// The owner-only danger zone. Both actions are real and irreversible, so both
// require typed acknowledgement - and the purge states exactly what dies: the
// append-only activity log, which is the platform's audit trail.

import { useState } from "react";
import { usePurgeActivity, useResetSettings } from "@/lib/hooks/settings";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useToast, describeError } from "@/components/ui/Toast";

export default function DangerTab() {
  const reset = useResetSettings();
  const purge = usePurgeActivity();
  const toast = useToast();
  const [confirming, setConfirming] = useState<"reset" | "purge" | null>(null);

  return (
    <div style={{ maxWidth: 640 }}>
      <div className="cs" style={{ marginBottom: 14 }}>
        Owner-only. Each action states its blast radius and requires typing it out.
      </div>

      <section className="card" style={{ padding: 18, borderColor: "var(--warn)" }}>
        <div className="ct">Reset settings to defaults</div>
        <div className="cs" style={{ margin: "6px 0 12px" }}>
          Workspace and security settings return to their shipped defaults. Clients, users,
          jobs and every other record are untouched.
        </div>
        <button type="button" className="ghostbtn" onClick={() => setConfirming("reset")} disabled={reset.isPending}>
          {reset.isPending ? "Resetting…" : "Reset settings"}
        </button>
      </section>

      <section className="card" style={{ padding: 18, marginTop: 14, borderColor: "var(--crit)" }}>
        <div className="ct" style={{ color: "var(--crit)" }}>Purge the activity log</div>
        <div className="cs" style={{ margin: "6px 0 12px" }}>
          Permanently deletes the platform&apos;s entire audit trail — every recorded sign-in,
          change and action, for all time. There is no export step here and no undo.
        </div>
        <button type="button" className="danger-btn" onClick={() => setConfirming("purge")} disabled={purge.isPending}>
          {purge.isPending ? "Purging…" : "Purge activity log"}
        </button>
      </section>

      <ConfirmDialog
        open={confirming === "reset"}
        title="Reset settings to defaults?"
        body="Workspace and security settings return to their shipped defaults immediately."
        reassurance="Clients, users, content, audits and all other records are untouched."
        confirmLabel="Reset settings"
        tone="caution"
        typeToConfirm="RESET"
        pending={reset.isPending}
        onCancel={() => setConfirming(null)}
        onConfirm={() =>
          reset.mutate(undefined, {
            onSuccess: () => { setConfirming(null); toast.success("Settings reset to defaults"); },
            onError: (e: unknown) => { setConfirming(null); toast.error("Couldn't reset", describeError(e)); },
          })
        }
      />
      <ConfirmDialog
        open={confirming === "purge"}
        title="Purge the entire activity log?"
        body="Every audit-trail entry is permanently deleted. This is the record of who did what — once purged it cannot be reconstructed."
        confirmLabel="Purge forever"
        tone="danger"
        typeToConfirm="PURGE"
        pending={purge.isPending}
        onCancel={() => setConfirming(null)}
        onConfirm={() =>
          purge.mutate(undefined, {
            onSuccess: (r) => { setConfirming(null); toast.success("Activity log purged", `${r.purged} entries permanently deleted.`); },
            onError: (e: unknown) => { setConfirming(null); toast.error("Couldn't purge", describeError(e)); },
          })
        }
      />
    </div>
  );
}
