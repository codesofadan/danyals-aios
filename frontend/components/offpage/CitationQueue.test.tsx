/**
 * The operator's in-hand queue item has to survive a reload.
 *
 * THE DEFECT. The claimed item lived in `useState` alone, set only by the claim
 * mutation's onSuccess. Reload the page - or open the queue on a second screen -
 * and the board came back empty while the row stayed claimed server-side for the
 * rest of its twenty-minute lease. "Take the next item" then handed over a
 * DIFFERENT row while the first sat locked, and re-taking the original later
 * incremented `human_attempts`, which reads to whoever picks it up next as
 * "someone has tried this before and failed".
 *
 * The server always knew the answer - `claimed_by` is how the lease works - and the
 * response model has carried a `mine` field since the queue shipped. Nothing
 * populated it and nothing read it. Both halves now exist.
 *
 * The second property here is the timer. Resuming has to seed the elapsed clock
 * from the server's banked total; starting it at zero would make the next heartbeat
 * bank the same seconds a second time, and the median-minutes-per-item figure the
 * whole board is judged on would inflate every time anyone refreshed.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CitationQueue from "./CitationQueue";
import type { QueueItem } from "@/lib/offpage";

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

function heldItem(over: Partial<QueueItem> = {}): QueueItem {
  return {
    citationId: "cit-1",
    client: "Leeds Drainage",
    directory: "Hotfrog",
    directoryUrl: "https://hotfrog.example",
    addUrl: "https://hotfrog.example/add",
    fields: [{ key: "business_name", label: "Business name", value: "Leeds Drainage" }],
    queuedBecause: "captcha on submit",
    claimExpiresAt: new Date(Date.now() + 900_000).toISOString(),
    humanAttempts: 1,
    workedSeconds: 0,
    prohibitedWarning: "",
    ...over,
  };
}

function mockBoard(mine: QueueItem[]) {
  get.mockImplementation(async (path: string) => {
    if (path.includes("/citation-builder/queue")) {
      return { waiting: 3, inProgress: mine.length, medianSeconds: 240, mine };
    }
    return [];
  });
}

function renderQueue() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CitationQueue />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
});

describe("CitationQueue - the claim survives a reload", () => {
  it("resumes the item this operator is already holding, without claiming again", async () => {
    // This is the reload: fresh mount, no local state, a claim already held.
    mockBoard([heldItem()]);
    renderQueue();

    expect(await screen.findByText(/Hotfrog/)).toBeInTheDocument();
    // Crucially it did NOT take a new item - that is what stranded the first one.
    expect(post).not.toHaveBeenCalled();
  });

  it("seeds the timer from the server's banked total rather than restarting it", async () => {
    // Restarting at zero makes the next heartbeat bank the same seconds twice, which
    // inflates the median-minutes figure every time anyone refreshes.
    mockBoard([heldItem({ workedSeconds: 185 })]);
    renderQueue();

    // 185s = 3:05, rendered by the component's own mmss().
    expect(await screen.findByText(/3:05/)).toBeInTheDocument();
  });

  it("shows the empty board when this operator holds nothing", async () => {
    mockBoard([]);
    renderQueue();

    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(screen.queryByText(/Hotfrog/)).toBeNull();
    expect(post).not.toHaveBeenCalled();
  });

  it("carries the attempt count over, so a resumed item is not re-reported as retried", async () => {
    mockBoard([heldItem({ humanAttempts: 3 })]);
    renderQueue();

    expect(await screen.findByText(/Hotfrog/)).toBeInTheDocument();
    // The count is the SERVER's, not one this component invented by re-claiming.
    expect(post).not.toHaveBeenCalled();
  });
});
