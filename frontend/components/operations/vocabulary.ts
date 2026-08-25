// ============================================================
// AIOS · Operations — the vocabulary, rendered
//
// `lib/jobs.ts` owns the wire contract and the tone/label/icon for each status.
// This module owns the two presentation facts that are the board's own:
//
//   1. TONE → PILL CLASS. The dashboard's shared `.status-pill` has five variants
//      (ok / info / warn / mut / crit). `bad` maps to `crit` and `idle` to `mut`;
//      `warn` (degraded, blocked) NEVER borrows `ok`. That mapping is the whole
//      point of the vocabulary made visible: a degraded run must not be able to
//      share a colour with a completed one.
//
//   2. MEANING. A status word on its own is jargon. The rule on this screen is
//      that a status is never shown without what it means, so every pill, chip and
//      verdict line pulls its sentence from here — one definition, seven places.
//      The wording mirrors `backend/app/jobs/status.py`'s module docstring, which
//      is where these distinctions are defined.
// ============================================================

import { statusMeta, type JobStatus, type JobStatusMeta, type JobTone } from "@/lib/jobs";

/** `.status-pill` / `.pill-tag` variant for a job tone. */
const TONE_CLASS: Record<JobTone, string> = {
  ok: "ok",
  warn: "warn",
  bad: "crit",
  idle: "mut",
};

export function toneClass(tone: JobTone): string {
  return TONE_CLASS[tone] ?? "mut";
}

const MEANING: Record<JobStatus, string> = {
  queued: "Accepted and waiting for a worker — nothing has run yet.",
  running: "A worker is executing it right now.",
  completed: "The promise was kept. This is the only success.",
  degraded: "It finished, but part of the promise was NOT kept.",
  blocked: "It deliberately did not spend — a gate, a missing credential or a cap stopped it.",
  failed: "It hit an error it could not recover from.",
  cancelled: "A person stopped it.",
};

/** The one-line definition behind a status word. Tolerant like `statusMeta`: an
 *  unrecognized status says so rather than inventing a meaning for it. */
export function statusMeaning(status: JobStatus | string): string {
  return (
    (MEANING as Record<string, string | undefined>)[String(status)] ??
    "This build does not recognise that status — it carries no verdict."
  );
}

/** label + icon + the `.status-pill` class + the sentence, in one lookup. */
export function statusChip(status: JobStatus | string): JobStatusMeta & {
  cls: string;
  meaning: string;
} {
  const meta = statusMeta(status);
  return { ...meta, cls: toneClass(meta.tone), meaning: statusMeaning(status) };
}
