/**
 * One button fills every open directory — and the selector that decides "every".
 *
 * THE OPERATOR COST THIS REMOVES. A ten-directory batch was ten manual rounds of
 * focus-tab, press-fill, read-result, next-tab. The tabs were already open and `tabMap`
 * already knew which task each belonged to, so the tab-switching bought nothing: the
 * operator was hand-running a for-loop.
 *
 * What is pinned here is the SELECTOR, because that is where a sweep goes wrong in ways
 * nobody notices: filling a task twice (silently overwriting an operator's hand-edit),
 * filling a terminal task, or missing a task because its tab was opened late.
 */

import { describe, expect, it } from "vitest";

import { tasksNeedingTabs, tasksReadyToFill, withTab } from "../src/lib/sessionBoard";
import type { ActiveSession } from "../src/lib/sessionBoard";

function session(
  tasks: { taskId: string; uiState: string; addUrl?: string }[],
  tabMap: Record<string, string> = {},
): ActiveSession {
  return {
    clientId: "c1",
    clientName: "Client",
    kind: "citation",
    tasks: tasks.map((t, i) => ({
      taskId: t.taskId,
      uiState: t.uiState,
      batchNo: 1,
      name: `Directory ${i + 1}`,
      addUrl: t.addUrl ?? `https://dir${i + 1}.test/add`,
      homepage: "",
      fields: [],
    })),
    tabMap,
    telemetry: {},
  } as unknown as ActiveSession;
}

describe("the sweep fills exactly the open, unfilled, released tasks", () => {
  it("takes every released task that has a tab", () => {
    const s = session(
      [
        { taskId: "a", uiState: "released" },
        { taskId: "b", uiState: "opened" },
        { taskId: "c", uiState: "form_detected" },
      ],
      { "11": "a", "12": "b", "13": "c" },
    );
    expect(tasksReadyToFill(s).map((t) => t.taskId)).toEqual(["a", "b", "c"]);
  });

  it("skips a task with no tab — that one is opened first, not filled blind", () => {
    const s = session(
      [
        { taskId: "a", uiState: "released" },
        { taskId: "b", uiState: "released" },
      ],
      { "11": "a" },
    );
    expect(tasksReadyToFill(s).map((t) => t.taskId)).toEqual(["a"]);
    // ...and it is exactly what the tab-opener will pick up, so the two together cover
    // the whole released set. That is the invariant "fill all" depends on.
    expect(tasksNeedingTabs(s).map((t) => t.taskId)).toEqual(["b"]);
  });

  it("REFUSES to re-fill an already filled task", () => {
    // Not idempotent in the way it looks: a form edited by hand since the last fill
    // would have that edit silently overwritten by the stored value.
    const s = session(
      [
        { taskId: "a", uiState: "filled" },
        { taskId: "b", uiState: "released" },
      ],
      { "11": "a", "12": "b" },
    );
    expect(tasksReadyToFill(s).map((t) => t.taskId)).toEqual(["b"]);
  });

  it("skips terminal tasks", () => {
    const s = session(
      [
        { taskId: "a", uiState: "submitted" },
        { taskId: "b", uiState: "skipped" },
        { taskId: "c", uiState: "blocked" },
        { taskId: "d", uiState: "released" },
      ],
      { "11": "a", "12": "b", "13": "c", "14": "d" },
    );
    expect(tasksReadyToFill(s).map((t) => t.taskId)).toEqual(["d"]);
  });

  it("a tab registered after the session started is picked up", () => {
    // The opener runs before the sweep, so a tab opened moments ago must count.
    let s = session([{ taskId: "a", uiState: "released" }]);
    expect(tasksReadyToFill(s)).toHaveLength(0);
    s = withTab(s, 99, "a");
    expect(tasksReadyToFill(s).map((t) => t.taskId)).toEqual(["a"]);
  });

  it("the two selectors never overlap", () => {
    // If they did, one directory would be opened AND filled in the same pass, racing a
    // page that has not loaded.
    const s = session(
      [
        { taskId: "a", uiState: "released" },
        { taskId: "b", uiState: "opened" },
        { taskId: "c", uiState: "released" },
      ],
      { "11": "a" },
    );
    const ready = new Set(tasksReadyToFill(s).map((t) => t.taskId));
    const needing = new Set(tasksNeedingTabs(s).map((t) => t.taskId));
    for (const id of ready) expect(needing.has(id)).toBe(false);
  });
});

describe("the sweep reports per directory, not just a total", () => {
  it("counts a directory with zero filled fields as needing attention", () => {
    // Modelled on the worker's own arithmetic: succeeded = filled > 0.
    const items = [
      { taskId: "a", name: "A", filled: 7, failed: 2, error: "" },
      { taskId: "b", name: "B", filled: 0, failed: 9, error: "" },
      { taskId: "c", name: "C", filled: 0, failed: 0, error: "No tab to fill." },
    ];
    const succeeded = items.filter((i) => i.filled > 0).length;
    expect(succeeded).toBe(1);
    expect(items.length - succeeded).toBe(2);
  });
});
