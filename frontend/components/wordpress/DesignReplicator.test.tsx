/**
 * The replication queue must survive a refresh.
 *
 * THE DEFECT. The card held the job handle in React state alone:
 *
 *     const [jobId, setJobId] = useState<string | null>(null);   // set in onSuccess
 *     {jobId && <JobStatus jobId={jobId} />}
 *
 * Nothing was read on mount. So navigating away or reloading threw away the only
 * reference to a running job - the work continued server-side, invisibly, and the
 * operator had no way back to it. QA reported it as "the queue disappears".
 *
 * It compounded with two backend defects (the deployed worker consumed only the
 * default queue; the job_runs row was not written until a worker claimed it), which
 * is why the same job also never left "Queued". Those are fixed separately; this
 * file pins the UI half: the list is read from the ledger on mount, so it is a
 * property of the server's state and not of this component's memory.
 *
 * The second thing pinned here is the BLOCKED rendering. The live wp_connections
 * table is empty, so the first real replication anyone runs will come back
 * `blocked / wp_connection_missing`. Nothing is broken and retrying cannot help -
 * a connection has to be made - so it must read as an instruction, not an error.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DesignReplicator from "./DesignReplicator";

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
    },
  };
});

vi.mock("next/link", () => ({
  default: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

const CLIENT = { id: "cl-1", cn: "Leeds Drainage" };

function run(over: Record<string, unknown> = {}) {
  return {
    id: "run-1",
    jobName: "replica.publish",
    task: "aios.replica.run",
    queue: "browser",
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
    idempotencyKey: "replica:cl-1:x",
    createdAt: "2026-08-31T10:00:00Z",
    startedAt: null,
    finishedAt: null,
    heartbeatAt: null,
    scheduledFor: null,
    cancelRequested: false,
    durationSeconds: null,
    result: { url: "https://clientsite.com/services" },
    ...over,
  };
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DesignReplicator />
    </QueryClientProvider>,
  );
}

/** Every path the component has fetched so far. */
const paths = (): string[] => get.mock.calls.map((c) => String(c[0]));

beforeEach(() => {
  get.mockReset();
  post.mockReset();
});

describe("DesignReplicator - the queue is server state", () => {
  it("asks the job ledger for existing runs on mount, before anything is submitted", async () => {
    // The load-bearing assertion. On the old component NOTHING was fetched until a
    // submit succeeded, so this fails there: no /jobs/runs call is ever made.
    get.mockImplementation(async (path: string) => {
      if (path.startsWith("/clients")) return [CLIENT];
      if (path.startsWith("/jobs/runs")) return [];
      return [];
    });

    renderCard();

    await waitFor(() =>
      expect(paths().some((p) => p.startsWith("/jobs/runs"))).toBe(true),
    );
    const call = paths().find((p) => p.startsWith("/jobs/runs"))!;
    expect(call).toContain("jobName=replica.publish");
  });

  it("shows a job that was queued before this page was ever opened", async () => {
    // i.e. exactly the state after a refresh: no local handle, job still queued.
    get.mockImplementation(async (path: string) => {
      if (path.startsWith("/clients")) return [CLIENT];
      if (path.startsWith("/jobs/runs")) return [run()];
      return [];
    });

    renderCard();

    expect(await screen.findByText("Queued")).toBeInTheDocument();
    expect(screen.getByText("https://clientsite.com/services")).toBeInTheDocument();
  });

  it("scopes the run list to the selected client", async () => {
    get.mockImplementation(async (path: string) => {
      if (path.startsWith("/clients")) return [CLIENT];
      if (path.startsWith("/jobs/runs")) return [];
      return [];
    });

    renderCard();

    await waitFor(() =>
      expect(paths().some((p) => p.includes("clientId=cl-1"))).toBe(true),
    );
  });

  it("says so plainly when there is nothing yet, rather than showing nothing at all", async () => {
    get.mockImplementation(async (path: string) => {
      if (path.startsWith("/clients")) return [CLIENT];
      if (path.startsWith("/jobs/runs")) return [];
      return [];
    });

    renderCard();

    expect(await screen.findByText(/no replications yet for this client/i)).toBeInTheDocument();
  });
});

describe("DesignReplicator - a blocked run reads as an instruction", () => {
  it("tells the operator to connect WordPress instead of reporting a failure", async () => {
    get.mockImplementation(async (path: string) => {
      if (path.startsWith("/clients")) return [CLIENT];
      if (path.startsWith("/jobs/runs"))
        return [
          run({
            status: "blocked",
            needsAttention: true,
            reasonCode: "wp_connection_missing",
            reason:
              "the client has no WordPress connection; connect the site " +
              "(Settings -> WordPress Connections) before replicating",
            finishedAt: "2026-08-31T10:00:05Z",
          }),
        ];
      return [];
    });

    renderCard();

    expect(await screen.findByText(/isn.t connected yet/i)).toBeInTheDocument();
    expect(screen.getByText(/Connect it in the WordPress Connections card/i)).toBeInTheDocument();
    expect(screen.getByText("Blocked")).toBeInTheDocument();
  });

  it("still surfaces a genuine failure as an error", async () => {
    // The distinction has to cut both ways, or "blocked" becomes a place to hide
    // real breakage.
    get.mockImplementation(async (path: string) => {
      if (path.startsWith("/clients")) return [CLIENT];
      if (path.startsWith("/jobs/runs"))
        return [
          run({
            status: "failed",
            needsAttention: true,
            errorType: "TimeoutError",
            errorMessage: "the capture timed out after 120s",
            finishedAt: "2026-08-31T10:02:00Z",
          }),
        ];
      return [];
    });

    renderCard();

    expect(await screen.findByText(/TimeoutError: the capture timed out/i)).toBeInTheDocument();
    expect(screen.queryByText(/isn.t connected yet/i)).toBeNull();
  });

  it("links the preview of a completed run", async () => {
    get.mockImplementation(async (path: string) => {
      if (path.startsWith("/clients")) return [CLIENT];
      if (path.startsWith("/jobs/runs"))
        return [
          run({
            status: "completed",
            succeeded: true,
            startedAt: "2026-08-31T10:00:02Z",
            finishedAt: "2026-08-31T10:04:00Z",
            result: {
              url: "https://clientsite.com/services",
              preview_url: "https://clientsite.com/?p=42&preview=true",
              sections: 7,
              widgets: 31,
              notes: [],
            },
          }),
        ];
      return [];
    });

    renderCard();

    const link = await screen.findByRole("link", { name: /open the preview/i });
    expect(link).toHaveAttribute("href", "https://clientsite.com/?p=42&preview=true");
    expect(screen.getByText(/7 sections · 31 widgets/)).toBeInTheDocument();
  });
});
