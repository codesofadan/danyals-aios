/** The message contract between the side panel, the service worker and the page. */

export type QueueFieldValue = {
  key: string;
  label: string;
  value: string;
  /** Where this value goes on the live form, from the directory's ACTIVE spec. Empty
   *  when no spec has been earned — the panel then offers copy-buttons, not a Fill. */
  selector: string;
};

export type QueueItem = {
  citationId: string;
  client: string;
  directory: string;
  directoryUrl: string;
  addUrl: string;
  fields: QueueFieldValue[];
  queuedBecause: string;
  claimExpiresAt: string | null;
  humanAttempts: number;
  workedSeconds: number;
  prohibitedWarning: string;
};

export type QueueBoard = {
  waiting: number;
  inProgress: number;
  medianSeconds: number | null;
};

export type CompleteResult = {
  accepted: boolean;
  submitStatus: string;
  liveUrl: string;
  reason: string;
  matchedFields: string[];
  /** A refusal the operator may override (we could not READ the page — JS-render, a
   *  block, or a moderation hold). The panel offers "I checked — it's live" only then. */
  canConfirm?: boolean;
  /** An ACCEPTED operator-confirmed completion (submitted, not probe-verified live). */
  operatorConfirmed?: boolean;
};

export type FillOutcome = {
  filled: string[];
  failed: { key: string; reason: string }[];
};

import type { Diagnosis } from "./diagnose";

// --- operator sessions (0130). Wire shapes mirror the backend's session schemas
// (camelCase serialization aliases) 1:1 — server-authoritative; move them together. ---

export type SessionClientCount = {
  clientId: string;
  client: string;
  readyForHuman: number;
  verifyFirst: number;
  candidateGaps: number;
  /** 0136: parked extension-lane web2 placements awaiting a placement session. */
  web2Placements: number;
};

export type SessionKind = "citation" | "web2_placement";

/** The full ui_state vocabulary (0130). The extension only ever REPORTS the forward
 *  non-terminal half; terminal values arrive from the server's own handlers. */
export type SessionTaskState =
  | "pending" | "released" | "opened" | "form_detected" | "filled"
  | "awaiting_submit" | "submitted" | "skipped" | "deferred" | "blocked";

export type SessionTaskCard = {
  taskId: string;
  citationId: string;
  batchNo: number;
  position: number;
  uiState: SessionTaskState;
  directory: string;
  directoryId: string;
  directoryUrl: string;
  addUrl: string;
  /** Fail-closed: false whenever no ACTIVE earned spec exists — every field then
   *  carries an empty selector and the panel offers click-to-copy, never a Fill. */
  hasSpec: boolean;
  fields: QueueFieldValue[];
  queuedBecause: string;
  prohibitedWarning: string;
  /** Catalogue cost note ("Free", "Free; paid upsells", "Paid $2.50") — shown so the
   *  operator sees whether submission costs money before working the directory. */
  priceNote: string;
};

/** One paste-ready value from an approved web2 draft (0136). Copy-blocks are the
 *  placement lane's default and its fail-closed fallback. */
export type Web2CopyBlock = {
  key: string;
  label: string;
  value: string;
};

/** One web2_placement task (0136). `hasSpec` is fail-closed exactly like the
 *  citation card's: no ACTIVE earned placement spec means false, `fields` is empty,
 *  and the panel offers copy-blocks only - the extension never fills on a guess and
 *  NEVER submits (the operator publishes in their own logged-in session). */
export type Web2PlacementTaskCard = {
  taskId: string;
  web2Id: string;
  batchNo: number;
  position: number;
  uiState: SessionTaskState;
  platform: string;
  title: string;
  /** Spec editor_url when an active spec exists (host-pinned server-side), else the
   *  platform homepage, else "" - shown honestly as "no URL on file". */
  editorUrl: string;
  anchor: string;
  targetUrl: string;
  hasSpec: boolean;
  copyBlocks: Web2CopyBlock[];
  fields: QueueFieldValue[];
};

export type OperatorSession = {
  id: string;
  client: string;
  clientId: string;
  status: "active" | "paused" | "completed" | "abandoned";
  kind: SessionKind;
  batchSize: number;
  currentBatch: number;
  totalBatches: number;
  taskCount: number;
  byUiState: Record<string, number>;
  createdAt: string;
  updatedAt: string;
  closedAt: string | null;
};

/** Kind-split task lists: a citation session fills `tasks`, a web2_placement
 *  session fills `web2Tasks`. */
export type SessionDetail = OperatorSession & {
  tasks: SessionTaskCard[];
  web2Tasks: Web2PlacementTaskCard[];
};

/** The placement completion verdict - the server's own fetch, never our claim. A
 *  refusal (`accepted:false`) is a normal answer and advances nothing. */
export type PlacementCompleteResult = {
  accepted: boolean;
  status: string;
  postUrl: string;
  reason: string;
  linkFound: boolean | null;
  linkRel: string;
};

/** A diagnosis plus the one fact only the extension knows: its own identity, which is
 *  exactly what the server's EXTENSION_ORIGINS allow-list needs. */
export type ConnectionReport = Diagnosis & { extensionId: string };

/** Panel → worker. The panel never calls the API and never sees the token. */
export type PanelRequest =
  | { type: "pair"; token: string; apiBase: string }
  | { type: "unpair" }
  | { type: "session" }
  | { type: "board" }
  | { type: "claim" }
  | { type: "fill" }
  | { type: "complete"; liveUrl: string; note: string }
  | { type: "blocked"; reason: string; detail: string }
  | { type: "release" }
  | { type: "diagnose"; apiBase?: string; token?: string }
  // --- operator sessions (0130; kind 'web2_placement' since 0136) ---
  | { type: "sessionClients" }
  | { type: "startSession"; clientId: string; limit?: number; batchSize?: number; kind?: SessionKind }
  | { type: "sessionState" }
  | { type: "refreshSession" }
  | { type: "openTask"; taskId: string }
  | { type: "fillTask"; taskId: string }
  // Best-effort autofill when the directory has no earned spec: match business values
  // to the page's own fields by their attributes. Honest read-back; never submits.
  | { type: "fillTaskAuto"; taskId: string }
  // AI-assisted fill: the keyword heuristic FIRST (free, instant), then the model for
  // the fields it could not match - an abbreviation nobody listed, a box whose only
  // clue is the text beside it, a honeypot the heuristic would happily fill. Sends
  // field STRUCTURE only; still never submits.
  | { type: "fillTaskAi"; taskId: string }
  // One-click: open the add-form tab, wait for it to load, then autofill it.
  | { type: "openAndAutofill"; taskId: string }
  | { type: "markSubmitted"; taskId: string; liveUrl: string; note: string; operatorConfirmed?: boolean }
  // Web2 placement completion (0136): the operator published in their own session
  // and pastes the public URL; the SERVER verifies host + link before anything moves.
  | { type: "markPlaced"; taskId: string; url: string }
  | { type: "skipTask"; taskId: string; reason: string }
  | { type: "deferTask"; taskId: string }
  | { type: "blockTask"; taskId: string; reason: string; detail: string }
  | { type: "closeSession" };

export type PanelResponse =
  | { ok: true; data: unknown }
  | { ok: false; error: string; needsPairing?: boolean; diagnosis?: ConnectionReport };
