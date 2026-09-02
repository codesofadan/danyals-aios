"use client";

import Link from "next/link";

// ============================================================
// AIOS · Design Replicator
// Rebuild a page the client already owns as a native Elementor page on the
// client's connected WordPress site (POST /replica), with the run list read back
// from the JOB LEDGER (GET /jobs/runs?jobName=replica.publish).
// Lives on the WordPress screen because the output IS a WordPress publish.
// The ownership checkbox is a hard gate: the rebuild carries the source's own
// copy and imagery, so the operator must assert the client owns the site —
// the submit stays disabled (and the server 400s) without it.
//
// THE JOB HANDLE USED TO LIVE IN REACT STATE ALONE. `useState<string|null>` was
// set in the mutation's onSuccess and read nowhere else, so navigating away or
// refreshing discarded the only reference to a job that was still running: the
// work carried on, invisibly, and the operator had no route back to it. Reported
// as "the queue disappears". The ledger was already the durable record - this
// screen simply never read it.
// ============================================================

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useClients } from "@/lib/hooks/clients";
import { REPLICA_RUNS_KEY, useReplicate, useReplicaRuns } from "@/lib/hooks/replica";
import type { JobRun } from "@/lib/jobs";
import { isReplicaActive, type ReplicaStatus } from "@/lib/replica";
import { SelectField, TextField } from "@/components/ui/Field";

// THEME TOKENS, not a private palette. This block used to declare its own
// CARD/LINE/INK/MAROON constants, copy-pasted from WpConnections.tsx, and the
// fallbacks were doing the painting: `--maroon` and `--blush` are defined
// NOWHERE, so `var(--maroon, #6E1423)` always resolved to that maroon - a dead
// pre-violet palette. Two components on this screen therefore rendered a
// different brand from the rest of the product. These now read the real theme.
const CARD = "var(--card)";
const LINE = "var(--line)";
const INK = "var(--ink)";
const ACCENT = "var(--violet)";

const PILL_TONE: Record<string, { bg: string; fg: string }> = {
  ok: { bg: "color-mix(in srgb, var(--ok) 12%, transparent)", fg: "var(--ok)" },
  warn: { bg: "color-mix(in srgb, var(--warn) 14%, transparent)", fg: "var(--warn)" },
  bad: { bg: "color-mix(in srgb, var(--crit) 12%, transparent)", fg: "var(--crit)" },
  idle: { bg: "var(--well)", fg: "var(--muted)" },
};

const STATUS_PILL: Record<ReplicaStatus, { label: string; tone: keyof typeof PILL_TONE }> = {
  queued: { label: "Queued", tone: "idle" },
  running: { label: "Rebuilding", tone: "warn" },
  completed: { label: "Completed", tone: "ok" },
  degraded: { label: "Degraded", tone: "warn" },
  blocked: { label: "Blocked", tone: "bad" },
  failed: { label: "Failed", tone: "bad" },
  cancelled: { label: "Cancelled", tone: "bad" },
};

function StatusPill({ status }: { status: ReplicaStatus }) {
  const pill = STATUS_PILL[status];
  const tone = PILL_TONE[pill.tone];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "3px 10px",
        borderRadius: 999,
        fontSize: 12.5,
        fontWeight: 700,
        background: tone.bg,
        color: tone.fg,
        whiteSpace: "nowrap",
      }}
    >
      <span style={{ width: 7, height: 7, borderRadius: 999, background: tone.fg }} />
      {pill.label}
    </span>
  );
}

// The three typed refusals workers/tasks/replica.py raises when the client's
// WordPress connection cannot publish. They are not failures - nothing is broken and
// nothing needs retrying; a connection has to be made first. Rendering them as
// errors would send an operator hunting for a bug that is not there.
//
// Each gets its own sentence rather than echoing the worker's `reason`, which is
// phrased for a log and points at a Settings path this card is not on.
const CONNECTION_REASONS: Record<string, { title: string; fix: string }> = {
  wp_connection_missing: {
    title: "This client’s WordPress site isn’t connected yet.",
    fix: "Connect it in the WordPress Connections card on this page, then run the replication again.",
  },
  wp_plugin_required: {
    title: "This client’s connection can’t write Elementor data.",
    fix: "Replication needs the AIOS Publisher plugin. Install it on the client’s site and reconnect with the plugin method, then run this again.",
  },
  wp_credentials_unreadable: {
    title: "This client’s stored WordPress credential couldn’t be opened.",
    fix: "Re-enter the connection in the WordPress Connections card on this page, then run the replication again.",
  },
};

function fmtWhen(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// --- one row of the ledger --------------------------------------------------- #
function RunRow({ run }: { run: JobRun }) {
  const status = run.status as ReplicaStatus;
  const active = isReplicaActive(status);
  const result = (run.result ?? {}) as {
    url?: string;
    preview_url?: string | null;
    sections?: number | null;
    widgets?: number | null;
    notes?: string[];
  };
  const notes = Array.isArray(result.notes) ? result.notes : [];
  const previewUrl = result.preview_url || null;
  const connectionFix = status === "blocked" ? CONNECTION_REASONS[run.reasonCode] : undefined;

  return (
    <div style={{ display: "grid", gap: 6, padding: "12px 0", borderTop: `1px solid ${LINE}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <StatusPill status={status} />
        <span
          style={{
            fontSize: 13.5,
            color: INK,
            fontWeight: 600,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            maxWidth: 320,
          }}
          title={result.url ?? ""}
        >
          {result.url ?? "—"}
        </span>
        {active && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--muted)" }}>
            <span
              className="material-symbols-rounded"
              style={{ fontSize: 16, animation: "bkspin 1s linear infinite" }}
            >
              progress_activity
            </span>
            {/* The LIVE stage, not a fixed sentence. The worker writes one human line
                per stage into the ledger's `detail` column (JobRun.detail), which this
                card was already receiving and throwing away — so a 12-60s rebuild
                showed the same eight words from start to finish and an operator could
                not tell progress from a hang. Falls back to the old wording only
                before the first stage lands. */}
            {run.detail ||
              (status === "queued"
                ? "Waiting for the worker…"
                : "Capturing the page and rebuilding it as Elementor…")}
          </span>
        )}
        {previewUrl && (status === "completed" || status === "degraded") && (
          <a
            href={previewUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontSize: 13.5, fontWeight: 700, color: ACCENT }}
          >
            {status === "degraded" ? "Open the preview (published with gaps) →" : "Open the preview →"}
          </a>
        )}
        {(result.sections != null || result.widgets != null) && (
          <span style={{ fontSize: 13, color: "var(--muted)" }}>
            {result.sections ?? 0} section{(result.sections ?? 0) === 1 ? "" : "s"} ·{" "}
            {result.widgets ?? 0} widget{(result.widgets ?? 0) === 1 ? "" : "s"}
          </span>
        )}
      </div>

      <div style={{ fontSize: 12, color: "var(--muted)" }}>
        Started {fmtWhen(run.createdAt) || "just now"}
        {run.finishedAt ? ` · finished ${fmtWhen(run.finishedAt)}` : ""}
        {run.attempt > 1 ? ` · attempt ${run.attempt} of ${run.maxAttempts}` : ""}
      </div>

      {connectionFix ? (
        <div
          style={{
            fontSize: 13,
            color: "var(--body)",
            background: "var(--well)",
            border: `1px solid ${LINE}`,
            borderRadius: 10,
            padding: "10px 12px",
            lineHeight: 1.55,
          }}
        >
          <b style={{ color: INK }}>{connectionFix.title}</b> {connectionFix.fix}
        </div>
      ) : (
        run.reason && (
          <div style={{ fontSize: 12.5, color: "var(--muted)", lineHeight: 1.5 }}>{run.reason}</div>
        )
      )}

      {run.status === "failed" && run.errorMessage && (
        <div style={{ fontSize: 12.5, color: "var(--crit)", lineHeight: 1.5 }}>
          {run.errorType}: {run.errorMessage}
        </div>
      )}

      {notes.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 3 }}>
          {notes.map((note, i) => (
            <li key={i} style={{ fontSize: 12.5, color: "var(--muted)", lineHeight: 1.5 }}>
              {note}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// --- the card ---------------------------------------------------------------- #
export default function DesignReplicator() {
  const qc = useQueryClient();
  const clientsQ = useClients();
  const clients = clientsQ.data ?? [];
  const replicate = useReplicate();

  const [clientId, setClientId] = useState("");
  const [url, setUrl] = useState("");
  const [ownerConfirmed, setOwnerConfirmed] = useState(false);

  const effectiveClientId = clientId || clients[0]?.id || "";
  const canSubmit =
    !!effectiveClientId && !!url.trim() && ownerConfirmed && !replicate.isPending;

  // The job list comes from the LEDGER, not from this component's memory, so it is
  // still here after a refresh, a navigation, or a new browser session.
  const runsQ = useReplicaRuns(effectiveClientId || null);
  const runs = runsQ.data ?? [];

  const onSubmit = () => {
    if (!canSubmit) return;
    replicate.mutate(
      {
        client_id: effectiveClientId,
        url: url.trim(),
        owner_confirmed_source: ownerConfirmed,
      },
      {
        // The run row exists as soon as the API accepts the job, so refetching is
        // enough to show it - there is no local handle to keep.
        onSuccess: () => {
          void qc.invalidateQueries({ queryKey: REPLICA_RUNS_KEY });
        },
      },
    );
  };

  // `fieldStyle` and `labelStyle` lived here - the 10th and 11th hand-rolled
  // input treatments in the product. components/ui/Field carries them now, so
  // this form gets the shared focus ring, spacing and label wiring for free.

  return (
    <div className="main-pad" style={{ padding: "0 26px 26px" }}>
      <div style={{ background: CARD, border: `1px solid ${LINE}`, borderRadius: 14, padding: 22 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: ACCENT, letterSpacing: 0.3 }}>
          Design Replicator
        </div>
        <h2 style={{ fontSize: 18, fontWeight: 800, color: INK, margin: "2px 0 0" }}>
          Rebuild a single page as native Elementor
        </h2>
        <p style={{ fontSize: 14, color: "var(--body)", lineHeight: 1.55, margin: "8px 0 0", maxWidth: 640 }}>
          Point it at a page the client owns and it rebuilds the design as an editable
          Elementor page on the client&rsquo;s connected WordPress site, then hands you
          a preview link.
        </p>
        {/* This card REBUILDS one page the client already has; it generates no new
            copy. Building several NEW pages on a replicated design is the content
            flow's job — the replicator now returns its measured design profile, so
            that flow starts from the same measurement rather than re-capturing. */}
        <p style={{ fontSize: 13.5, color: "var(--body)", lineHeight: 1.55, margin: "8px 0 0", maxWidth: 640 }}>
          Building several <b>new</b> pages on a design instead?{" "}
          <Link href="/admin/content/new" style={{ color: ACCENT, fontWeight: 700 }}>
            Start in Content
          </Link>{" "}
          — it replicates the design, writes the pages and publishes them in one run.
        </p>

        <div style={{ marginTop: 18, display: "grid", gap: 16, maxWidth: 560 }}>
          {/* Adopted from components/ui/Field: the label association, the
              required marker and the field-level error come with it, instead of
              being re-hand-rolled here for the 35th time. */}
          <SelectField
            label="Client"
            required
            value={effectiveClientId}
            onChange={(e) => setClientId(e.target.value)}
            disabled={clients.length === 0}
          >
            {clients.length === 0 ? (
              <option value="">
                {clientsQ.isError
                  ? "Couldn't load clients — try again"
                  : clientsQ.isLoading
                    ? "Loading clients…"
                    : "No clients yet"}
              </option>
            ) : (
              clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.cn}
                </option>
              ))
            )}
          </SelectField>

          <TextField
            label="Page URL"
            required
            hint="The page to rebuild, exactly as it is published."
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://clientsite.com/the-page-to-rebuild"
            autoComplete="off"
            inputMode="url"
          />

          <label style={{ display: "flex", alignItems: "flex-start", gap: 10, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={ownerConfirmed}
              onChange={(e) => setOwnerConfirmed(e.target.checked)}
              style={{ marginTop: 3, width: 16, height: 16, accentColor: ACCENT }}
            />
            <span style={{ fontSize: 13.5, color: INK, lineHeight: 1.5 }}>
              <b>The client owns this site.</b>{" "}
              <span style={{ color: "var(--muted)" }}>
                The rebuild carries the source page&rsquo;s own copy and imagery, so it
                must be the client&rsquo;s property.
              </span>
            </span>
          </label>

          {replicate.isError && (
            <div style={{ fontSize: 13, color: "var(--crit)", fontWeight: 600 }}>
              {replicate.error instanceof Error
                ? replicate.error.message
                : "Could not queue the replication. Check the URL and try again."}
            </div>
          )}

          <div>
            <button
              type="button"
              onClick={onSubmit}
              disabled={!canSubmit}
              title={ownerConfirmed ? undefined : "Confirm the client owns the site first"}
              style={{
                padding: "10px 18px",
                borderRadius: 10,
                border: "none",
                background: ACCENT,
                color: "#fff",
                fontSize: 14,
                fontWeight: 800,
                cursor: canSubmit ? "pointer" : "not-allowed",
                opacity: canSubmit ? 1 : 0.6,
              }}
            >
              {replicate.isPending ? "Queuing…" : "Replicate design"}
            </button>
          </div>

        </div>

        {/* Recent replications, straight from the job ledger. */}
        <div style={{ marginTop: 26 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <h3 style={{ fontSize: 14.5, fontWeight: 800, color: INK, margin: 0 }}>
              Recent replications
            </h3>
            <span style={{ fontSize: 12.5, color: "var(--muted)" }}>
              Kept server-side — safe to leave this page and come back.
            </span>
          </div>

          {runsQ.isLoading ? (
            <div style={{ fontSize: 13, color: "var(--muted)", paddingTop: 12 }}>
              Loading recent runs…
            </div>
          ) : runsQ.isError ? (
            <div style={{ fontSize: 13, color: "var(--crit)", fontWeight: 600, paddingTop: 12 }}>
              Couldn&rsquo;t load recent runs. Any job already queued is unaffected — it is
              recorded server-side.
            </div>
          ) : runs.length === 0 ? (
            <div style={{ fontSize: 13, color: "var(--muted)", paddingTop: 12 }}>
              No replications yet for this client.
            </div>
          ) : (
            <div style={{ marginTop: 6 }}>
              {runs.map((run) => (
                <RunRow key={run.id} run={run} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
