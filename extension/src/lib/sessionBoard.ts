/**
 * Session-mode state (0130), and why it lives in `chrome.storage.session`.
 *
 * Same reasoning as the single-claim state in `session.ts`: the MV3 worker is
 * terminated after ~30s idle, so the active session — which tasks exist, which tab
 * belongs to which task, how much time is banked — must survive worker restarts
 * without ever touching disk. `chrome.storage.session` is memory-backed and dies with
 * the browser, which is exactly the lifetime of a work session whose server half is
 * lease-reaped anyway.
 *
 * Everything stateful here is a PURE function over the stored object plus a thin
 * read/write pair, so the tab-attribution and telemetry-dedupe logic is unit-testable
 * without a browser.
 */

import type {
  QueueFieldValue,
  SessionKind,
  SessionTaskCard,
  SessionTaskState,
  Web2PlacementTaskCard,
} from "./messages";

const KEY = "aios.activeSession";

export type ActiveSession = {
  sessionId: string;
  client: string;
  /** 'citation' (default when absent - pre-0136 stored state) or 'web2_placement'. */
  kind?: SessionKind;
  currentBatch: number;
  totalBatches: number;
  batchSize: number;
  tasks: SessionTaskCard[];
  /** Web2 placement cards (0136). Filled only for kind='web2_placement'. */
  web2Tasks?: Web2PlacementTaskCard[];
  /** tabId -> taskId. How a tab's load-complete event becomes 'opened' telemetry for
   *  the right task, across worker restarts. */
  tabMap: Record<string, string>;
  /** taskId -> ui_states already reported, so the worker never re-sends a state the
   *  server would 409 as non-forward. */
  sentTelemetry: Record<string, string[]>;
  /** Wall-clock anchor for the session heartbeat's worked-seconds delta. */
  startedAtMs: number;
};

/** The kind-neutral view of one task - what tab orchestration and telemetry need,
 *  whichever lane the session works. `openUrl` is the citation add-form or the web2
 *  editor URL; "" means "nothing to open" and the panel says so honestly. */
export type TaskRef = { taskId: string; uiState: SessionTaskState; batchNo: number; openUrl: string };

export function sessionKind(state: ActiveSession): SessionKind {
  return state.kind ?? "citation";
}

/**
 * The injection plan for one card - ONLY fields that carry a selector, which is the
 * fail-closed rule in one place: a citation card without an earned spec and a web2
 * card without an ACTIVE placement spec both ship zero selectors, so the plan is
 * empty and the panel stays on copy-blocks. The filler never touches contenteditable
 * on a guess and never submits, whatever the plan says.
 */
export function fillPlanFor(
  fields: QueueFieldValue[],
): { selector: string; valueKey: string; value: string }[] {
  return fields
    .filter((f) => f.selector)
    .map((f) => ({ selector: f.selector, valueKey: f.key, value: f.value }));
}

export function taskRefs(state: ActiveSession): TaskRef[] {
  if (sessionKind(state) === "web2_placement") {
    return (state.web2Tasks ?? []).map((t) => ({
      taskId: t.taskId, uiState: t.uiState, batchNo: t.batchNo, openUrl: t.editorUrl,
    }));
  }
  return state.tasks.map((t) => ({
    taskId: t.taskId, uiState: t.uiState, batchNo: t.batchNo, openUrl: t.addUrl,
  }));
}

export async function readSession(): Promise<ActiveSession | null> {
  const got = await chrome.storage.session.get(KEY);
  return (got[KEY] as ActiveSession | undefined) ?? null;
}

export async function writeSession(state: ActiveSession): Promise<void> {
  await chrome.storage.session.set({ [KEY]: state });
}

export async function clearSession(): Promise<void> {
  await chrome.storage.session.remove(KEY);
}

// --------------------------------------------------------------------------- //
// Pure helpers.
// --------------------------------------------------------------------------- //

/** The task a tab belongs to, or null — how a load event is attributed. Kind-neutral:
 *  a web2 editor tab and a citation form tab attribute identically. */
export function taskForTab(state: ActiveSession, tabId: number): TaskRef | null {
  const taskId = state.tabMap[String(tabId)];
  if (!taskId) return null;
  return taskRefs(state).find((t) => t.taskId === taskId) ?? null;
}

/** Record a tab as belonging to a task (returns a NEW state — callers persist it). */
export function withTab(state: ActiveSession, tabId: number, taskId: string): ActiveSession {
  return { ...state, tabMap: { ...state.tabMap, [String(tabId)]: taskId } };
}

/** Forget a closed tab. */
export function withoutTab(state: ActiveSession, tabId: number): ActiveSession {
  const tabMap = { ...state.tabMap };
  delete tabMap[String(tabId)];
  return { ...state, tabMap };
}

/**
 * Whether a ui_state report should be SENT for this task — true only once per state,
 * so a re-fired tab event or a second fill click never produces the backwards/repeat
 * report the server would refuse. Marks it sent in the returned state.
 */
export function markTelemetrySent(
  state: ActiveSession, taskId: string, uiState: string,
): { state: ActiveSession; shouldSend: boolean } {
  const sent = state.sentTelemetry[taskId] ?? [];
  if (sent.includes(uiState)) return { state, shouldSend: false };
  return {
    state: {
      ...state,
      sentTelemetry: { ...state.sentTelemetry, [taskId]: [...sent, uiState] },
    },
    shouldSend: true,
  };
}

/** The tasks of the current batch that are live UI work (released or beyond, not
 *  terminal) — what the panel's batch view lists first. */
export function activeBatchTasks(state: ActiveSession): SessionTaskCard[] {
  return state.tasks.filter((t) => t.batchNo === state.currentBatch);
}

const RELEASED_STATES = new Set(["released", "opened", "form_detected", "filled", "awaiting_submit"]);

/** Released, non-terminal tasks that have NO tab yet — what the worker opens when a
 *  session starts or a batch releases. Kind-neutral: a citation task opens its
 *  add-form URL, a web2 task its (spec-pinned or homepage) editor URL; a task with
 *  no URL is never opened — the panel offers it by hand instead. */
export function tasksNeedingTabs(state: ActiveSession): TaskRef[] {
  const withTabs = new Set(Object.values(state.tabMap));
  return taskRefs(state).filter(
    (t) => RELEASED_STATES.has(t.uiState) && !withTabs.has(t.taskId) && t.openUrl !== "",
  );
}

/**
 * Merge a server refresh into local state, keeping the tab map and telemetry ledger
 * (the server knows nothing about tabs) while taking the server's word for every
 * task's ui_state and the batch counters — the server is the authority; local state
 * is orchestration bookkeeping.
 */
export function mergeServerSession(
  state: ActiveSession,
  server: {
    id: string;
    client: string;
    kind?: SessionKind;
    currentBatch: number;
    totalBatches: number;
    batchSize: number;
    tasks: SessionTaskCard[];
    web2Tasks?: Web2PlacementTaskCard[];
  },
): ActiveSession {
  return {
    ...state,
    sessionId: server.id,
    client: server.client,
    kind: server.kind ?? state.kind ?? "citation",
    currentBatch: server.currentBatch,
    totalBatches: server.totalBatches,
    batchSize: server.batchSize,
    tasks: server.tasks,
    web2Tasks: server.web2Tasks ?? [],
  };
}
