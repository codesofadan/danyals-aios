"use client";

import Link from "next/link";

// ============================================================
// AIOS · Design Replicator
// Rebuild a page the client already owns as a native Elementor page on the
// client's connected WordPress site (POST /replica → poll GET /replica/{job_id}).
// Lives on the WordPress screen because the output IS a WordPress publish.
// The ownership checkbox is a hard gate: the rebuild carries the source's own
// copy and imagery, so the operator must assert the client owns the site —
// the submit stays disabled (and the server 400s) without it.
// ============================================================

import { useState } from "react";
import { useClients } from "@/lib/hooks/clients";
import { useReplicate, useReplicaJob } from "@/lib/hooks/replica";
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

// --- the live job status line ------------------------------------------------ #
function JobStatus({ jobId }: { jobId: string }) {
  const { data: job, isError } = useReplicaJob(jobId);

  if (isError) {
    return (
      <div style={{ fontSize: 13, color: "var(--crit)", fontWeight: 600 }}>
        Could not read the job status. It may still be running — check back shortly.
      </div>
    );
  }
  if (!job) {
    return <div style={{ fontSize: 13, color: "var(--muted)" }}>Checking the job…</div>;
  }

  const active = isReplicaActive(job.status);

  return (
    <div style={{ display: "grid", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <StatusPill status={job.status} />
        {active && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--muted)" }}>
            <span
              className="material-symbols-rounded"
              style={{ fontSize: 16, animation: "bkspin 1s linear infinite" }}
            >
              progress_activity
            </span>
            {job.status === "queued"
              ? "Waiting for the worker…"
              : "Capturing the page and rebuilding it as Elementor…"}
          </span>
        )}
        {job.status === "completed" && job.preview_url && (
          <a
            href={job.preview_url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontSize: 13.5, fontWeight: 700, color: ACCENT }}
          >
            Open the preview →
          </a>
        )}
        {(job.sections !== null || job.widgets !== null) && (
          <span style={{ fontSize: 13, color: "var(--muted)" }}>
            {job.sections ?? 0} section{(job.sections ?? 0) === 1 ? "" : "s"} ·{" "}
            {job.widgets ?? 0} widget{(job.widgets ?? 0) === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {/* degraded still publishes — surface the preview alongside the honest notes */}
      {job.status === "degraded" && job.preview_url && (
        <a
          href={job.preview_url}
          target="_blank"
          rel="noopener noreferrer"
          style={{ fontSize: 13.5, fontWeight: 700, color: ACCENT }}
        >
          Open the preview (published with gaps) →
        </a>
      )}

      {job.notes.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 3 }}>
          {job.notes.map((note, i) => (
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
  const clientsQ = useClients();
  const clients = clientsQ.data ?? [];
  const replicate = useReplicate();

  const [clientId, setClientId] = useState("");
  const [url, setUrl] = useState("");
  const [ownerConfirmed, setOwnerConfirmed] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);

  const effectiveClientId = clientId || clients[0]?.id || "";
  const canSubmit =
    !!effectiveClientId && !!url.trim() && ownerConfirmed && !replicate.isPending;

  const onSubmit = () => {
    if (!canSubmit) return;
    setJobId(null);
    replicate.mutate(
      {
        client_id: effectiveClientId,
        url: url.trim(),
        owner_confirmed_source: ownerConfirmed,
      },
      { onSuccess: (res) => setJobId(res.job_id) },
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

          {jobId && (
            <div style={{ borderTop: `1px solid ${LINE}`, paddingTop: 14 }}>
              <JobStatus jobId={jobId} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
