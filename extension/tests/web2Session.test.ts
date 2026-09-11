import { describe, expect, it } from "vitest";

import type { SessionTaskCard, Web2PlacementTaskCard } from "../src/lib/messages";
import {
  type ActiveSession,
  fillPlanFor,
  mergeServerSession,
  sessionKind,
  taskForTab,
  taskRefs,
  tasksNeedingTabs,
} from "../src/lib/sessionBoard";

/**
 * Web 2.0 placement mode (0136) over the SAME session-board module the citation lane
 * uses — kind-neutral tab orchestration, and the fail-closed rule that matters most:
 * without an ACTIVE placement spec there are no selectors, so the fill plan is EMPTY
 * and the panel stays on copy-blocks. Pure-function tests, no browser.
 */

function web2Task(over: Partial<Web2PlacementTaskCard> = {}): Web2PlacementTaskCard {
  return {
    taskId: "t-1",
    web2Id: "w2-1",
    batchNo: 1,
    position: 0,
    uiState: "released",
    platform: "Medium",
    title: "A grounded article",
    editorUrl: "https://medium.com/new-story",
    anchor: "plumber in leeds",
    targetUrl: "https://client.example/services",
    hasSpec: false,
    copyBlocks: [
      { key: "title", label: "Title", value: "A grounded article" },
      { key: "body", label: "Body (Markdown)", value: "## body" },
    ],
    fields: [],
    ...over,
  };
}

function citationTask(over: Partial<SessionTaskCard> = {}): SessionTaskCard {
  return {
    taskId: "c-t-1",
    citationId: "ct-1",
    batchNo: 1,
    position: 0,
    uiState: "released",
    directory: "Brownbook",
    directoryId: "d-1",
    directoryUrl: "https://brownbook.net",
    addUrl: "https://brownbook.net/add",
    hasSpec: false,
    fields: [],
    queuedBecause: "",
    prohibitedWarning: "",
    priceNote: "",
    ...over,
  };
}

function web2Session(tasks: Web2PlacementTaskCard[], over: Partial<ActiveSession> = {}): ActiveSession {
  return {
    sessionId: "s-1",
    client: "Acme",
    kind: "web2_placement",
    currentBatch: 1,
    totalBatches: 1,
    batchSize: 10,
    tasks: [],
    web2Tasks: tasks,
    tabMap: {},
    sentTelemetry: {},
    startedAtMs: 0,
    ...over,
  };
}

describe("kind-neutral task refs", () => {
  it("a web2 session's open URL is the EDITOR url, a citation session's the add-form", () => {
    const w = web2Session([web2Task()]);
    expect(taskRefs(w).map((t) => t.openUrl)).toEqual(["https://medium.com/new-story"]);

    const c = web2Session([], { kind: "citation", tasks: [citationTask()] });
    expect(taskRefs(c).map((t) => t.openUrl)).toEqual(["https://brownbook.net/add"]);
  });

  it("a stored session WITHOUT a kind reads as a citation session (pre-0136 state)", () => {
    const legacy = web2Session([], { tasks: [citationTask()] });
    delete (legacy as { kind?: string }).kind;
    expect(sessionKind(legacy)).toBe("citation");
    expect(taskRefs(legacy)).toHaveLength(1);
  });
});

describe("tab orchestration for placement tasks", () => {
  it("released web2 tasks with an editor URL get tabs; ones without are left for the human", () => {
    const state = web2Session([
      web2Task({ taskId: "t-1" }),
      web2Task({ taskId: "t-2", editorUrl: "" }), // no active spec AND no homepage on file
      web2Task({ taskId: "t-3", uiState: "pending" }), // not released yet
    ]);
    expect(tasksNeedingTabs(state).map((t) => t.taskId)).toEqual(["t-1"]);
  });

  it("a task that already owns a tab is not opened twice", () => {
    const state = web2Session([web2Task({ taskId: "t-1" })], { tabMap: { "7": "t-1" } });
    expect(tasksNeedingTabs(state)).toEqual([]);
  });

  it("a web2 editor tab attributes its load event to the right task", () => {
    const state = web2Session([web2Task({ taskId: "t-1" })], { tabMap: { "7": "t-1" } });
    expect(taskForTab(state, 7)?.taskId).toBe("t-1");
    expect(taskForTab(state, 8)).toBeNull();
  });

  it("terminal web2 tasks never get tabs", () => {
    for (const uiState of ["submitted", "skipped", "deferred", "blocked"] as const) {
      const state = web2Session([web2Task({ uiState })]);
      expect(tasksNeedingTabs(state)).toEqual([]);
    }
  });
});

describe("copy-block fail-closed", () => {
  it("without an active placement spec there are NO selectors, so the fill plan is empty", () => {
    // hasSpec=false <=> fields carry no selectors (server-enforced); the extension's
    // own plan builder must then produce nothing to inject — copy-blocks only.
    const task = web2Task({ hasSpec: false, fields: [] });
    expect(fillPlanFor(task.fields)).toEqual([]);
  });

  it("selector-less fields contribute nothing even if the server ever shipped them", () => {
    const plan = fillPlanFor([
      { key: "title", label: "Title", value: "A grounded article", selector: "" },
      { key: "body", label: "Body", value: "## body", selector: "" },
    ]);
    expect(plan).toEqual([]);
  });

  it("an ACTIVE spec's plain selectors DO produce a plan (and only those fields)", () => {
    const plan = fillPlanFor([
      { key: "title", label: "Title", value: "A grounded article", selector: "input[name=title]" },
      { key: "body", label: "Body", value: "## body", selector: "" },
    ]);
    expect(plan).toEqual([
      { selector: "input[name=title]", valueKey: "title", value: "A grounded article" },
    ]);
  });
});

describe("server refresh merge", () => {
  it("takes the server's word for web2 tasks and batch counters, keeps the tab map", () => {
    const state = web2Session([web2Task({ taskId: "t-1" })], {
      tabMap: { "7": "t-1" },
      sentTelemetry: { "t-1": ["opened"] },
    });
    const merged = mergeServerSession(state, {
      id: "s-1",
      client: "Acme",
      kind: "web2_placement",
      currentBatch: 2,
      totalBatches: 2,
      batchSize: 10,
      tasks: [],
      web2Tasks: [web2Task({ taskId: "t-1", uiState: "submitted" }), web2Task({ taskId: "t-9", batchNo: 2 })],
    });
    expect(merged.currentBatch).toBe(2);
    expect((merged.web2Tasks ?? []).map((t) => t.taskId)).toEqual(["t-1", "t-9"]);
    expect(merged.tabMap).toEqual({ "7": "t-1" });
    expect(merged.sentTelemetry).toEqual({ "t-1": ["opened"] });
  });

  it("a server payload without web2Tasks empties the list rather than keeping stale cards", () => {
    const state = web2Session([web2Task()]);
    const merged = mergeServerSession(state, {
      id: "s-1", client: "Acme", currentBatch: 1, totalBatches: 1, batchSize: 10, tasks: [],
    });
    expect(merged.web2Tasks).toEqual([]);
  });
});
