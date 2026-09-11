import { beforeEach, describe, expect, it } from "vitest";

import type { SessionTaskCard } from "../src/lib/messages";
import {
  type ActiveSession,
  clearSession,
  markTelemetrySent,
  mergeServerSession,
  readSession,
  taskForTab,
  tasksNeedingTabs,
  withoutTab,
  withTab,
  writeSession,
} from "../src/lib/sessionBoard";

/**
 * The session-mode state (0130), tested the way the other lib tests are: real module
 * code over a fake `chrome.storage.session`.
 *
 * The property that matters most: the tab map and the telemetry ledger live in
 * STORAGE, not in a worker variable — an MV3 worker is terminated after ~30s idle, so
 * "survives a worker restart" here means "survives every module-level variable being
 * lost", which the fake reproduces by round-tripping through storage on every access.
 */

type Store = Record<string, unknown>;

function installFakeChrome(): Store {
  const data: Store = {};
  const session = {
    get: async (key: string): Promise<Store> => (key in data ? { [key]: data[key] } : {}),
    set: async (obj: Store): Promise<void> => {
      Object.assign(data, obj);
    },
    remove: async (key: string): Promise<void> => {
      delete data[key];
    },
  };
  (globalThis as { chrome?: unknown }).chrome = { storage: { session } };
  return data;
}

const card = (over: Partial<SessionTaskCard> = {}): SessionTaskCard => ({
  taskId: "t1",
  citationId: "c1",
  batchNo: 1,
  position: 0,
  uiState: "released",
  directory: "Brownbook",
  directoryId: "d1",
  directoryUrl: "brownbook.net",
  addUrl: "https://brownbook.net/add",
  hasSpec: false,
  fields: [],
  queuedBecause: "prepared for a human to finish",
  prohibitedWarning: "",
  priceNote: "",
  ...over,
});

const state = (over: Partial<ActiveSession> = {}): ActiveSession => ({
  sessionId: "s1",
  client: "Acme Dental",
  currentBatch: 1,
  totalBatches: 2,
  batchSize: 10,
  tasks: [card()],
  tabMap: {},
  sentTelemetry: {},
  startedAtMs: 0,
  ...over,
});

beforeEach(() => {
  installFakeChrome();
});

describe("storage round-trip (worker restart survival)", () => {
  it("what one worker incarnation writes, the next reads back", async () => {
    await writeSession(state({ tabMap: { "42": "t1" } }));
    // A worker restart = every module variable gone; only storage remains. Re-reading
    // from the fake store IS the restart.
    const restored = await readSession();
    expect(restored).not.toBeNull();
    expect(restored!.sessionId).toBe("s1");
    expect(restored!.tabMap["42"]).toBe("t1");
  });

  it("clearSession leaves nothing to resume", async () => {
    await writeSession(state());
    await clearSession();
    expect(await readSession()).toBeNull();
  });
});

describe("tab attribution", () => {
  it("maps a tab back to its task", () => {
    const s = withTab(state(), 42, "t1");
    expect(taskForTab(s, 42)?.taskId).toBe("t1");
    expect(taskForTab(s, 43)).toBeNull();
  });

  it("a closed tab is forgotten, others kept", () => {
    let s = withTab(state({ tasks: [card(), card({ taskId: "t2", citationId: "c2" })] }), 42, "t1");
    s = withTab(s, 43, "t2");
    s = withoutTab(s, 42);
    expect(taskForTab(s, 42)).toBeNull();
    expect(taskForTab(s, 43)?.taskId).toBe("t2");
  });

  it("a tab pointing at a task that no longer exists resolves to null, not a crash", () => {
    const s = withTab(state({ tasks: [] }), 42, "ghost");
    expect(taskForTab(s, 42)).toBeNull();
  });
});

describe("telemetry dedupe (forward-only support)", () => {
  it("each state is sendable exactly once per task", () => {
    const first = markTelemetrySent(state(), "t1", "opened");
    expect(first.shouldSend).toBe(true);
    const second = markTelemetrySent(first.state, "t1", "opened");
    // The server would 409 a repeat as non-forward; the ledger means we never ask.
    expect(second.shouldSend).toBe(false);
  });

  it("different states and different tasks do not block each other", () => {
    let s = state();
    const a = markTelemetrySent(s, "t1", "opened");
    s = a.state;
    expect(markTelemetrySent(s, "t1", "filled").shouldSend).toBe(true);
    expect(markTelemetrySent(s, "t2", "opened").shouldSend).toBe(true);
  });
});

describe("tasksNeedingTabs (what the worker opens on start / batch release)", () => {
  it("released tasks without tabs and with an addUrl are opened", () => {
    const s = state({
      tasks: [
        card(),                                                     // released, no tab -> open
        card({ taskId: "t2", citationId: "c2", uiState: "pending" }),   // not released yet
        card({ taskId: "t3", citationId: "c3", uiState: "submitted" }), // terminal
        card({ taskId: "t4", citationId: "c4", addUrl: "" }),           // nowhere to go
      ],
    });
    expect(tasksNeedingTabs(s).map((t) => t.taskId)).toEqual(["t1"]);
  });

  it("a task that already has a tab is never opened twice", () => {
    const s = withTab(state(), 42, "t1");
    expect(tasksNeedingTabs(s)).toEqual([]);
  });

  it("a task mid-work (opened/filled) that lost its tab gets one again", () => {
    const s = state({ tasks: [card({ uiState: "filled" })] });
    expect(tasksNeedingTabs(s).map((t) => t.taskId)).toEqual(["t1"]);
  });
});

describe("mergeServerSession (the server is the authority on states and batches)", () => {
  it("takes the server's tasks and batch counters, keeps local orchestration", () => {
    const local = withTab(
      state({ sentTelemetry: { t1: ["opened"] } }), 42, "t1",
    );
    const merged = mergeServerSession(local, {
      id: "s1",
      client: "Acme Dental",
      currentBatch: 2,
      totalBatches: 3,
      batchSize: 10,
      tasks: [card({ uiState: "submitted" }), card({ taskId: "t9", citationId: "c9", batchNo: 2 })],
    });
    expect(merged.currentBatch).toBe(2);
    expect(merged.tasks.map((t) => t.taskId)).toEqual(["t1", "t9"]);
    expect(merged.tasks[0]!.uiState).toBe("submitted"); // the server's word wins
    expect(merged.tabMap["42"]).toBe("t1");             // tabs are local knowledge
    expect(merged.sentTelemetry["t1"]).toEqual(["opened"]); // so is the ledger
  });
});
