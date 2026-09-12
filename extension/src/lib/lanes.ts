/**
 * The two lanes the extension works, and the tab state that chooses between them.
 *
 * WHY A LANE AND NOT A DROPDOWN. Session *kinds* have existed server-side since `0136`
 * and the panel already rendered two entirely different task surfaces for them — but
 * the operator chose between them with a `<select>` buried under the citation queue's
 * numbers, so the panel read as "the citation tool, which can also do Web 2.0". The
 * work is two jobs with different rhythms (fill a directory form vs paste an approved
 * draft into your own logged-in account), so each gets a tab and its own board.
 *
 * WHY `storage.local` AND NOT `storage.session`. Unlike the active session — which is
 * deliberately memory-backed so it dies with the browser (see `sessionBoard.ts`) — the
 * chosen lane is a PREFERENCE. An operator who works Web 2.0 all afternoon should not
 * land back on the citation board every time the panel is reopened, and a lane is not
 * a secret: it is one of two literal strings.
 *
 * THE HONESTY RULE THIS FILE CARRIES. `laneWorkCount` returns `null`, never `0`, when
 * the server did not report a lane's backlog. Zero means "we asked and there is no
 * work"; null means "we do not know". Rendering an unreported backlog as "0 waiting"
 * is the same defect as a grid point that was never probed being drawn as a bad rank —
 * the operator would stop looking at a lane that might be full.
 */

import type { SessionClientCount, SessionKind } from "./messages";

export type Lane = "citation" | "web2";

export const LANES: readonly Lane[] = ["citation", "web2"] as const;

export const LANE_LABEL: Record<Lane, string> = {
  citation: "Citations",
  web2: "Web 2.0",
};

/** What the operator is told the lane does, on its own board. */
export const LANE_BLURB: Record<Lane, string> = {
  citation:
    "Directory listings. Each task opens its own tab and autofills what it can — " +
    "an earned spec first, then the page's own field attributes, then the model for " +
    "what is left. You review and submit; nothing is ever submitted for you.",
  web2:
    "Approved Web 2.0 drafts, handed over as copy-blocks. You publish in your own " +
    "logged-in account and paste the public URL back — the server checks the host " +
    "and the link before anything moves.",
};

const KEY = "aios.activeLane";

/** The lane's server-side session kind. The two vocabularies are deliberately
 *  separate: `web2` is a tab, `web2_placement` is what `0136` called the session. */
export function laneToSessionKind(lane: Lane): SessionKind {
  return lane === "web2" ? "web2_placement" : "citation";
}

/** The tab an active session belongs to, so the panel can mark it and refuse to
 *  switch away mid-session. */
export function sessionKindToLane(kind: SessionKind | undefined): Lane {
  return kind === "web2_placement" ? "web2" : "citation";
}

export function isLane(value: unknown): value is Lane {
  return value === "citation" || value === "web2";
}

/**
 * A lane's total outstanding work across clients, or `null` when the server reported
 * nothing for it.
 *
 * The citation lane counts the three states a citation session can pick up
 * (`ready_for_human`, `verify_first`, candidate gaps). The web2 lane counts parked
 * extension-lane placements. A client row that omits a lane's field contributes
 * nothing AND is remembered as unreported — so a mixed response (one old row, one
 * new) still reports a number, and an entirely silent response reports `null`.
 */
export function laneWorkCount(lane: Lane, clients: readonly SessionClientCount[]): number | null {
  if (clients.length === 0) return null;
  let total = 0;
  let reported = false;
  for (const c of clients) {
    const parts: Array<number | undefined> =
      lane === "web2"
        ? [c.web2Placements]
        : [c.readyForHuman, c.verifyFirst, c.candidateGaps];
    for (const p of parts) {
      if (typeof p === "number" && Number.isFinite(p)) {
        total += p;
        reported = true;
      }
    }
  }
  return reported ? total : null;
}

/** Clients with work in this lane — the only ones worth offering in its picker.
 *  A client whose count is UNREPORTED is kept, not hidden: refusing to offer a
 *  client because the server went quiet would look like the client has no work. */
export function clientsForLane(
  lane: Lane, clients: readonly SessionClientCount[],
): SessionClientCount[] {
  return clients.filter((c) => {
    const n = laneWorkCount(lane, [c]);
    return n === null || n > 0;
  });
}

/** One client's summary line, in the vocabulary of the lane being worked. */
export function clientSummary(lane: Lane, c: SessionClientCount): string {
  if (lane === "web2") {
    const n = laneWorkCount("web2", [c]);
    return `${c.client} — ${n === null ? "count not reported" : `${n} placement(s)`}`;
  }
  return (
    `${c.client} — ${c.readyForHuman} ready · ${c.verifyFirst} verify · ` +
    `${c.candidateGaps} gaps`
  );
}

export async function readLane(): Promise<Lane> {
  try {
    const got = await chrome.storage.local.get(KEY);
    const stored = got[KEY];
    return isLane(stored) ? stored : "citation";
  } catch {
    // Storage can be unavailable (a profile with site data blocked). A lane is a
    // preference; losing it costs one click, so it must never break the panel.
    return "citation";
  }
}

export async function writeLane(lane: Lane): Promise<void> {
  try {
    await chrome.storage.local.set({ [KEY]: lane });
  } catch {
    /* see readLane */
  }
}
