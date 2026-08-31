// The client's engagement timeline.
//
// The property that matters here is a THREE-WAY distinction, not a two-way one:
//
//   loading      we are still asking
//   404          there genuinely is no project yet - true, and expected during
//                onboarding
//   failed       we do not know, and must not pretend otherwise
//
// Before this, the component collapsed the last two: `!project` rendered "No
// milestones yet" for BOTH. So a 500 or a dropped connection told a paying client,
// in plain language, that their onboarding had not started.
//
// The FIRST fix drew the distinction in the component and left the transport
// alone - which inverted the bug instead of removing it. `apiFetch` throws on any
// non-ok status and the query client treats a 4xx as terminal, so the 404 arrived
// as `isError` and the client with no project yet was told the SERVER had failed.
// The empty branch was unreachable in production.
//
// The old version of this file could not see that, because it mocked the hook and
// asserted against `{ data: undefined, isError: false }` - a state the real
// transport can never produce for a 404. So the test passed on both the bug and
// the fix, which is the same as not testing it.
//
// This file therefore mocks the TRANSPORT (`@/lib/api`) and drives the real hook
// through a real QueryClient, so the three cases are the ones the server can
// actually send.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ClientMilestones from "./ClientMilestones";
import { ApiError } from "@/lib/api";
import type { ClientProject } from "@/lib/milestones";

const get = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, get: (path: string) => get(path) } };
});

vi.mock("./ClientHeader", () => ({
  default: ({ focus }: { focus: React.ReactNode }) => <div>{focus}</div>,
}));

const PROJECT: ClientProject = {
  id: "pr-1",
  client: "Leeds Drainage",
  site: "leedsdrainage.example",
  init: "LD",
  c: "c1",
  health: "on_track",
  stages: [
    { key: "onboarding", status: "completed", auto_source: "Client created", updated_at: "2 Aug 2026" },
    { key: "baseline", status: "in_progress", auto_source: "Baseline audit running", updated_at: "3 Aug 2026" },
    { key: "content", status: "upcoming", auto_source: "Waiting on the baseline", updated_at: "3 Aug 2026" },
    { key: "authority", status: "upcoming", auto_source: "Waiting on content", updated_at: "3 Aug 2026" },
    { key: "reporting", status: "upcoming", auto_source: "Waiting on delivery", updated_at: "3 Aug 2026" },
  ],
};

// The real retry predicate: 4xx terminal, 5xx retried. Retries are switched off so
// a deliberate 500 fails once instead of stalling the test.
function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ClientMilestones />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
});

describe("ClientMilestones - loading vs empty vs failed", () => {
  it("says it is still loading while it is", () => {
    get.mockImplementation(() => new Promise(() => {}));
    renderPage();

    expect(screen.getByText(/loading your timeline/i)).toBeInTheDocument();
    expect(screen.queryByText(/no milestones yet/i)).toBeNull();
  });

  it("renders the timeline when the server returns a project", async () => {
    get.mockResolvedValue(PROJECT);
    renderPage();

    expect(await screen.findByText(/delivery timeline/i)).toBeInTheDocument();
    expect(screen.queryByText(/no milestones yet/i)).toBeNull();
    expect(screen.queryByText(/couldn't load your timeline/i)).toBeNull();
  });

  it("says there is no project yet on a 404, and does NOT call it a failure", async () => {
    // The case the previous test could not express: a real 404 off the real
    // transport. This fails on the pre-fix hook, which let the 404 become isError.
    get.mockRejectedValue(new ApiError(404, "not_found", "no project", "req-1"));
    renderPage();

    expect(await screen.findByText(/no milestones yet/i)).toBeInTheDocument();
    expect(screen.getByText(/once onboarding begins/i)).toBeInTheDocument();
    expect(screen.queryByText(/couldn't load your timeline/i)).toBeNull();
    expect(screen.getByText(/no active project/i)).toBeInTheDocument();
  });

  it("NEVER tells the client onboarding has not begun when the fetch failed", async () => {
    // The defect this file exists for. "We could not load it" and "you have not
    // started" are entirely different statements, and only one of them is true.
    get.mockRejectedValue(new ApiError(500, "server_error", "boom", "req-2"));
    renderPage();

    expect(await screen.findByText(/couldn't load your timeline/i)).toBeInTheDocument();
    expect(screen.queryByText(/no milestones yet/i)).toBeNull();
    expect(screen.queryByText(/once onboarding begins/i)).toBeNull();
  });

  it("does not claim 'No active project' in the header on a failure either", async () => {
    // The header asserts project health independently of the body, so fixing only
    // the body would leave the same false claim in a second place.
    get.mockRejectedValue(new ApiError(500, "server_error", "boom", "req-3"));
    renderPage();

    // Exact, not a regex: the body also says "Couldn't load your timeline", and a
    // loose match would pass on the body alone while the header still lied.
    expect(await screen.findByText("Couldn't load")).toBeInTheDocument();
    expect(screen.queryByText(/no active project/i)).toBeNull();
  });

  it("offers a retry that actually refetches", async () => {
    get.mockRejectedValue(new ApiError(500, "server_error", "boom", "req-4"));
    renderPage();

    await screen.findByText(/couldn't load your timeline/i);
    const calls = get.mock.calls.length;

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(get.mock.calls.length).toBeGreaterThan(calls));
  });

  it("recovers to the timeline when a retry succeeds", async () => {
    // The retry has to be able to end the error state, not just re-ask.
    get.mockRejectedValueOnce(new ApiError(500, "server_error", "boom", "req-5"));
    renderPage();

    await screen.findByText(/couldn't load your timeline/i);
    get.mockResolvedValue(PROJECT);

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText(/delivery timeline/i)).toBeInTheDocument();
  });
});
