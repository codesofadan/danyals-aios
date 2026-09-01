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
};

export type FillOutcome = {
  filled: string[];
  failed: { key: string; reason: string }[];
};

import type { Diagnosis } from "./diagnose";

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
  | { type: "diagnose"; apiBase?: string; token?: string };

export type PanelResponse =
  | { ok: true; data: unknown }
  | { ok: false; error: string; needsPairing?: boolean; diagnosis?: ConnectionReport };
