/**
 * THE citation status vocabulary — the only file allowed to turn the backend's
 * 11-value `citation_submit_status` enum, or a `blocked_reason` code, into words.
 *
 * Why one file: the 2026-09-01 audit found FIVE competing vocabularies for the same
 * row — the table's Submission column, a "State/action" column that could say "Done ✓"
 * in the same row whose next cell said "Sent — unconfirmed", gap tiles, the audit
 * plan's Built/Missing, and the queue board's own words. An operator reading two
 * adjacent cells that argue with each other concludes the module is fake. Components
 * import from here; none may invent a label, a color, or a rollup of its own.
 *
 * The color law: GREEN IS RESERVED for `live` and `verified` — the two states that
 * exist only after this platform fetched the listing's URL and found the business's
 * name plus its phone or address on the page. Everything else is at best blue.
 */

/** Mirrors `public.citation_submit_status` (0045 + 0064 + 0106). */
export type CitationSubmitStatus =
  | "not_started"
  | "queued"
  | "submitting"
  | "submitted"
  | "verified"
  | "failed"
  | "blocked"
  | "ready_for_human"
  | "live"
  | "drifted"
  | "delisted";

/** The five operator-facing groups every rollup strip uses, in display order. */
export const ROLLUP_GROUPS = ["To do", "Your team", "Sent", "Live", "Needs attention"] as const;
export type RollupGroup = (typeof ROLLUP_GROUPS)[number];

/** `.status-pill` tone classes that exist in globals.css. */
export type PillTone = "ok" | "info" | "warn" | "crit" | "mut";

export type StatusMeta = {
  /** Short label — safe for `.status-pill` (≤3 words, no sentences). */
  label: string;
  tone: PillTone;
  group: RollupGroup;
  /** One honest sentence, for tooltips/legends. */
  meaning: string;
};

export const CITATION_STATUS: Record<CitationSubmitStatus, StatusMeta> = {
  not_started: {
    label: "Not started",
    tone: "mut",
    group: "To do",
    meaning: "Nothing has been attempted yet.",
  },
  queued: {
    label: "Waiting to attempt",
    tone: "info",
    group: "To do",
    meaning: "In line for the next attempt.",
  },
  submitting: {
    label: "Attempting now",
    tone: "info",
    group: "To do",
    meaning: "An attempt is running right now.",
  },
  submitted: {
    label: "Sent — unconfirmed",
    tone: "info",
    group: "Sent",
    meaning: "A form went out; nothing has confirmed a listing exists. Not a success yet.",
  },
  ready_for_human: {
    label: "In your work queue",
    tone: "info",
    group: "Your team",
    meaning: "A person finishes this — every field pre-filled on the Citation queue page.",
  },
  live: {
    label: "Live",
    tone: "ok",
    group: "Live",
    meaning: "We fetched the URL and found the business's name and its phone or address.",
  },
  verified: {
    label: "Live — re-checked",
    tone: "ok",
    group: "Live",
    meaning: "The listing was fetched again and the business is still on the page.",
  },
  failed: {
    label: "Failed",
    tone: "crit",
    group: "Needs attention",
    meaning: "The attempt errored. See the reason on the row.",
  },
  blocked: {
    label: "On hold",
    tone: "warn",
    group: "Needs attention",
    meaning: "Deliberately not attempted — the reason says who unblocks it.",
  },
  drifted: {
    label: "Live, details wrong",
    tone: "warn",
    group: "Needs attention",
    meaning: "The listing exists but its name/address/phone no longer match. Correct it, don't rebuild.",
  },
  delisted: {
    label: "Was live, now gone",
    tone: "crit",
    group: "Needs attention",
    meaning: "It was verified live and has since disappeared from the directory.",
  },
};

/** Meta for a status string of unknown provenance. Never throws; an unknown value is
 *  rendered as itself in the warn tone so a new enum member is visible, not invisible. */
export function citationStatusMeta(status: string): StatusMeta {
  return (
    CITATION_STATUS[status as CitationSubmitStatus] ?? {
      label: status.replace(/_/g, " ") || "Unknown",
      tone: "warn",
      group: "Needs attention",
      meaning: "This status is not in the vocabulary — the mapping needs updating.",
    }
  );
}

/**
 * `blocked_reason` codes → the sentence an operator (or a client report) reads.
 * Codes verified against backend/app/modules/citations/{tasks,service}.py — do not
 * add a code here that the backend cannot write.
 */
export const BLOCKED_REASON_LABEL: Record<string, string> = {
  no_verified_spec:
    "No earned form spec yet — routed to your team's queue. Finishing it by hand once is how it becomes automatic.",
  no_engine: "No machine can submit here — routed to your team's queue.",
  captcha: "A CAPTCHA needs a person — routed to your team's queue.",
  waf_403: "The site refuses robots — a person with a real browser does this one.",
  account_gated: "Needs a login only a person holds — routed to your team's queue.",
  tos_prohibits: "This directory's terms forbid automated submission. We will not submit — by policy.",
  fed_by_aggregator:
    "Covered by an aggregator feed we already push to — a separate listing would be a duplicate.",
  no_nap: "No business profile on file. Add the client's NAP (Clients → Edit), then re-run.",
  price_unknown: "This directory charges an unlisted price — a lead must approve the spend first.",
  spend_blocked: "The cost gate refused the spend — check the money dial, client cap, and spend halt.",
};

/** The sentence for a reason code; honest about the empty/unknown cases. */
export function blockedReasonLabel(code: string): string {
  if (!code) {
    return "On hold with no recorded reason — this is a bug; tell whoever maintains the platform.";
  }
  return BLOCKED_REASON_LABEL[code] ?? `On hold: ${code.replace(/_/g, " ")}.`;
}
