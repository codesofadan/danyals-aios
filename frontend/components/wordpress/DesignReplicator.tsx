"use client";

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

const CARD = "var(--card, #fff)";
const LINE = "var(--line, #E8D2D7)";
const INK = "var(--ink, #241015)";
const MAROON = "var(--maroon, #6E1423)";

const PILL_TONE: Record<string, { bg: string; fg: string }> = {
  ok: { bg: "#E7F6EC", fg: "#137333" },
  warn: { bg: "#FEF3E0", fg: "#8A5B00" },
  bad: { bg: "#FDE7E9", fg: "#B01B2E" },
  idle: { bg: "#EEE9EA", fg: "#6B5860" },
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
      <div style={{ fontSize: 13, color: "#B01B2E", fontWeight: 600 }}>
        Could not read the job status. It may still be running — check back shortly.
      </div>
    );
  }
  if (!job) {
    return <div style={{ fontSize: 13, color: "#6B5860" }}>Checking the job…</div>;
  }

  const active = isReplicaActive(job.status);

  return (
    <div style={{ display: "grid", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <StatusPill status={job.status} />
        {active && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, color: "#6B5860" }}>
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
            style={{ fontSize: 13.5, fontWeight: 700, color: MAROON }}
          >
            Open the preview →
          </a>
        )}
        {(job.sections !== null || job.widgets !== null) && (
          <span style={{ fontSize: 13, color: "#6B5860" }}>
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
          style={{ fontSize: 13.5, fontWeight: 700, color: MAROON }}
        >
          Open the preview (published with gaps) →
        </a>
      )}

      {job.notes.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 3 }}>
          {job.notes.map((note, i) => (
            <li key={i} style={{ fontSize: 12.5, color: "#6B5860", lineHeight: 1.5 }}>
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

  const fieldStyle: React.CSSProperties = {
    width: "100%",
    padding: "10px 12px",
    borderRadius: 10,
    border: `1px solid ${LINE}`,
    fontSize: 14,
    color: INK,
    background: CARD,
    marginTop: 6,
  };
  const labelStyle: React.CSSProperties = { fontSize: 13, fontWeight: 700, color: INK };

  return (
    <div className="main-pad" style={{ padding: "0 26px 26px" }}>
      <div style={{ background: CARD, border: `1px solid ${LINE}`, borderRadius: 14, padding: 22 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: MAROON, letterSpacing: 0.3 }}>
          Design Replicator
        </div>
        <h2 style={{ fontSize: 18, fontWeight: 800, color: INK, margin: "2px 0 0" }}>
          Rebuild a page as native Elementor
        </h2>
        <p style={{ fontSize: 14, color: "#5B4A4F", lineHeight: 1.55, margin: "8px 0 0", maxWidth: 640 }}>
          Point it at a page the client owns and it rebuilds the design as an editable
          Elementor page on the client&rsquo;s connected WordPress site, then hands you
          a preview link.
        </p>

        <div style={{ marginTop: 18, display: "grid", gap: 16, maxWidth: 560 }}>
          <label style={{ display: "block" }}>
            <span style={labelStyle}>Client</span>
            <select
              style={fieldStyle}
              value={effectiveClientId}
              onChange={(e) => setClientId(e.target.value)}
              disabled={clients.length === 0}
            >
              {clients.length === 0 ? (
                <option value="">{clientsQ.isLoading ? "Loading clients…" : "No clients yet"}</option>
              ) : (
                clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.cn}
                  </option>
                ))
              )}
            </select>
          </label>

          <label style={{ display: "block" }}>
            <span style={labelStyle}>Page URL</span>
            <input
              style={fieldStyle}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://clientsite.com/the-page-to-rebuild"
              autoComplete="off"
              inputMode="url"
            />
          </label>

          <label style={{ display: "flex", alignItems: "flex-start", gap: 10, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={ownerConfirmed}
              onChange={(e) => setOwnerConfirmed(e.target.checked)}
              style={{ marginTop: 3, width: 16, height: 16, accentColor: MAROON }}
            />
            <span style={{ fontSize: 13.5, color: INK, lineHeight: 1.5 }}>
              <b>The client owns this site.</b>{" "}
              <span style={{ color: "#6B5860" }}>
                The rebuild carries the source page&rsquo;s own copy and imagery, so it
                must be the client&rsquo;s property.
              </span>
            </span>
          </label>

          {replicate.isError && (
            <div style={{ fontSize: 13, color: "#B01B2E", fontWeight: 600 }}>
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
                background: MAROON,
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
