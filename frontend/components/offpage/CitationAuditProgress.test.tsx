/**
 * "Is the citation audit actually running?"
 *
 * Before this there was no way to answer that. POST returned a bare
 * {"status":"queued"} with no id, the task behind it was a plain Celery task that
 * produced no ledger row at all, and the only feedback was a flash that faded after
 * 4.2 seconds. After that, a sweep still working, a sweep that died, and a sweep
 * that never started because nothing was consuming its queue all looked identical:
 * an unchanged board.
 *
 * The properties pinned here are the distinctions that were missing - and the one
 * that matters most is that a DEGRADED sweep does not read as a successful one.
 * With no provider key the old code returned {"state":"degraded"} to a caller that
 * discarded it, wrote zero rows, and left a board showing no citations - which is
 * indistinguishable from a business that genuinely has none.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CitationAuditProgress from "./CitationAuditProgress";

const get = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, get: (path: string) => get(path) } };
});

function run(over: Record<string, unknown> = {}) {
  return {
    id: "run-1",
    jobName: "offpage.monitor",
    task: "monitor_offpage",
    queue: "long",
    status: "running",
    succeeded: false,
    needsAttention: false,
    clientId: "cl-1",
    clientName: "Leeds Drainage",
    scopeType: "client",
    scopeId: "cl-1",
    attempt: 1,
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
    startedAt: "2026-09-01T10:00:02Z",
    finishedAt: null,
    heartbeatAt: "2026-09-01T10:00:30Z",
    scheduledFor: null,
    cancelRequested: false,
    durationSeconds: null,
    result: null,
    ...over,
  };
}

function renderPanel(rows: unknown[]) {
  get.mockImplementation(async () => rows);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CitationAuditProgress clientId="cl-1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => get.mockReset());

describe("CitationAuditProgress", () => {
  it("shows the worker's own stage line while the sweep runs", async () => {
    renderPanel([run({ detail: "found 37 listings; recording 4 new, 1 changed" })]);

    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.getByText(/found 37 listings/)).toBeInTheDocument();
  });

  it("says a queued sweep is waiting for a worker, which is a real state", async () => {
    // The state the whole platform was in: accepted, recorded, and nothing consuming
    // the queue. It has to be nameable rather than looking like activity.
    renderPanel([run({ status: "queued", startedAt: null, heartbeatAt: null })]);

    expect(await screen.findByText("Queued")).toBeInTheDocument();
    expect(screen.getByText(/waiting for a worker/i)).toBeInTheDocument();
  });

  it("reports a keyless provider as PARTIAL, never as a clean finish", async () => {
    renderPanel([
      run({
        status: "degraded",
        needsAttention: true,
        finishedAt: "2026-09-01T10:01:00Z",
        reasonCode: "offpage_provider_unavailable",
        detail: "citations could not be checked: provider unconfigured or no business.",
        reason:
          "citations could not be checked: provider unconfigured or no business. " +
          "The counts below cover only what did run.",
        result: { citations_new: 0, citations_changed: 0 },
      }),
    ]);

    expect(await screen.findByText("Partial")).toBeInTheDocument();
    expect(screen.getAllByText(/could not be checked/i).length).toBeGreaterThan(0);
    expect(screen.queryByText("Completed")).toBeNull();
  });

  it("reports what a completed sweep actually recorded", async () => {
    renderPanel([
      run({
        status: "completed",
        succeeded: true,
        finishedAt: "2026-09-01T10:01:00Z",
        detail: "4 new and 1 changed listings",
        result: { citations_new: 4, citations_changed: 1 },
      }),
    ]);

    expect(await screen.findByText("Completed")).toBeInTheDocument();
    expect(screen.getByText(/4 new and 1 changed listings recorded/)).toBeInTheDocument();
  });

  it("surfaces a failure with its error rather than falling silent", async () => {
    renderPanel([
      run({
        status: "failed",
        needsAttention: true,
        finishedAt: "2026-09-01T10:01:00Z",
        detail: "the sweep did not finish",
        errorType: "TimeoutError",
        errorMessage: "the provider did not respond",
      }),
    ]);

    expect(await screen.findByText("Failed")).toBeInTheDocument();
    expect(screen.getByText(/TimeoutError: the provider did not respond/)).toBeInTheDocument();
  });

  it("renders nothing at all when this client has never been audited", async () => {
    const { container } = renderPanel([]);
    expect(container.textContent).toBe("");
  });
});
