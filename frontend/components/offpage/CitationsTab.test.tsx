/**
 * Starting a citation audit must not hide the thing that says it is running.
 *
 * THE DEFECT. §6 asks that an admin "immediately understand: the audit is running,
 * and later: the audit completed". A progress panel was built for exactly that — and
 * then rendered INSIDE the expanded branch of the Step-1 collapse, while the audit's
 * own onSuccess calls setAuditCollapsed(true). So pressing "Run citation audit"
 * unmounted the panel at the precise moment it had something to say. The feature
 * worked; it was invisible on the only path anyone takes.
 *
 * The collapse itself is deliberate — it folds the client picker away so "build the
 * missing listings" becomes the next step — so the fix is to hoist the panel out of
 * the ternary, not to stop collapsing.
 *
 * The second half is less obvious. The panel reads the run list, whose poll only
 * speeds up once it can SEE a non-terminal run. Without invalidating that query on
 * the POST, a freshly-started audit sits behind a 30s staleTime showing nothing —
 * which is the same silence, just briefer. Both halves are asserted below, so
 * shipping either one alone fails.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CitationsTab from "./CitationsTab";

const get = vi.fn();
const post = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      get: (path: string) => get(path),
      post: (path: string, body: unknown) => post(path, body),
      patch: vi.fn(),
      del: vi.fn(),
    },
  };
});

function run(over: Record<string, unknown> = {}) {
  return {
    id: "run-1",
    jobName: "offpage.monitor",
    task: "monitor_offpage",
    queue: "long",
    status: "queued",
    succeeded: false,
    needsAttention: false,
    clientId: "cl-1",
    clientName: "Leeds Drainage",
    scopeType: "client",
    scopeId: "cl-1",
    attempt: 0,
    maxAttempts: 1,
    detail: "",
    reason: "",
    reasonCode: "",
    errorType: "",
    errorMessage: "",
    costUsd: 0,
    correlationId: "corr-1",
    parentRunId: null,
    idempotencyKey: "offpage.monitor:cl-1:2026-09-01T10:00",
    createdAt: "2026-09-01T10:00:00Z",
    startedAt: null,
    finishedAt: null,
    heartbeatAt: null,
    scheduledFor: null,
    cancelRequested: false,
    durationSeconds: null,
    result: null,
    ...over,
  };
}

/** The run list the panel reads. Swapped mid-test to simulate the sweep progressing. */
let runs: unknown[] = [];

function mockApi() {
  runs = [];
  get.mockImplementation(async (path: string) => {
    if (path.startsWith("/jobs/runs")) return runs;
    if (path.startsWith("/clients")) return [{ id: "cl-1", cn: "Leeds Drainage" }];
    if (path.includes("gap-analysis")) {
      return {
        existingCount: 4, coveredCount: 4, missing: [], liveUrls: [],
        bySubmitStatus: {}, byNapStatus: {}, skipped: [], hasNap: true, napSource: "profile",
      };
    }
    if (path.includes("audit-plan")) {
      return {
        client: "Leeds Drainage", resolvedVertical: null, market: "US",
        generic: [], country: [], niche: [],
      };
    }
    return [];
  });
  post.mockResolvedValue({
    status: "queued",
    clientId: "cl-1",
    business: "Leeds Drainage",
    jobRunId: "run-1",
    jobName: "offpage.monitor",
    detail: "Citation audit queued — discovering existing vs missing.",
  });
}

function renderTab() {
  // The APP's defaults (staleTime 30s), not a test client that refetches freely —
  // a permissive client would silently mask the missing invalidation.
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CitationsTab />
    </QueryClientProvider>,
  );
}

/** Buttons here carry a Material icon ligature inside them ("search_checkRun
 *  citation audit"), so the accessible name is not the visible label - match on
 *  text content instead of role+name. */
async function findButton(label: RegExp): Promise<HTMLElement> {
  return waitFor(() => {
    const hit = screen
      .queryAllByRole("button")
      .find((b) => label.test(b.textContent || ""));
    if (!hit) throw new Error(`no button matching ${label}`);
    return hit;
  });
}

async function chooseClient() {
  // The <select> renders immediately with only its placeholder; the options arrive
  // with the clients query. Selecting before then is a silent no-op, so wait for
  // the option itself rather than for the select.
  await screen.findByRole("option", { name: "Leeds Drainage" });
  const [clientSelect] = screen.getAllByRole("combobox") as HTMLSelectElement[];
  fireEvent.change(clientSelect, { target: { value: "cl-1" } });
}

async function startAnAudit() {
  await chooseClient();
  const btn = await findButton(/run citation audit/i);
  runs = [run()]; // the backend accepted it; the ledger now has a queued row
  fireEvent.click(btn);
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  mockApi();
});

describe("CitationsTab — the audit says it is running", () => {
  it("keeps the progress panel visible after Step 1 folds away", async () => {
    renderTab();
    await startAnAudit();

    // The collapse still happens — that is deliberate and must not be undone.
    expect(await screen.findByText(/change client \/ re-audit/i)).toBeInTheDocument();
    // And the panel survives it, which is the whole point.
    expect(await screen.findByText("Queued")).toBeInTheDocument();
    expect(screen.getByText(/waiting for a worker/i)).toBeInTheDocument();
  });

  it("refetches the run list when the audit starts, rather than waiting out staleTime", async () => {
    renderTab();
    const before = get.mock.calls.filter((c) => String(c[0]).startsWith("/jobs/runs")).length;
    await startAnAudit();

    await waitFor(() => {
      const after = get.mock.calls.filter((c) => String(c[0]).startsWith("/jobs/runs")).length;
      expect(after).toBeGreaterThan(before);
    });
  });

  it("says so when the sweep completes", async () => {
    renderTab();
    await startAnAudit();
    await screen.findByText("Queued");

    runs = [
      run({
        status: "completed",
        succeeded: true,
        attempt: 1,
        startedAt: "2026-09-01T10:00:02Z",
        finishedAt: "2026-09-01T10:01:00Z",
        detail: "4 new and 1 changed listings",
        result: { citations_new: 4, citations_changed: 1 },
      }),
    ];

    expect(await screen.findByText("Completed", {}, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.getByText(/4 new and 1 changed listings recorded/)).toBeInTheDocument();
  });

  it("does not pretend to follow a run the backend could not record", async () => {
    // jobRunId is null only when the ledger could not be read back. The sweep is
    // queued, but nothing can report on it — and an empty panel must not be the
    // only signal, because it reads as "nothing happened".
    post.mockResolvedValue({
      status: "queued", clientId: "cl-1", business: "Leeds Drainage",
      jobRunId: null, jobName: "offpage.monitor", detail: "Citation audit queued.",
    });
    renderTab();

    await chooseClient();
    fireEvent.click(await findButton(/run citation audit/i));

    expect(await screen.findByText(/could not be recorded/i)).toBeInTheDocument();
  });
});
