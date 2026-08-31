// Announcing a newly-arrived notification (QA 4).
//
// "Assigning a task should trigger an instant notification in the team member
// dashboard ... plus a toast notification when a new task is assigned, so a team
// member with the portal open sees it immediately."
//
// The delivery layer already worked end to end — `assign_task` writes a
// `task_assigned` row and the bell renders it. What was missing was a reason to LOOK.
// So the interesting behaviour is not "does it toast" but the ways an arrival toast
// goes wrong, each pinned below.
//
// The unread count is written straight into the query cache rather than waiting out a
// real 15s poll: the hook reacts to the VALUE changing, and a test that sleeps for a
// poll interval is both slow and the kind of thing that makes a suite flaky.

import { act, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { makeQueryClient } from "@/lib/query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { UNREAD_KEY, resetNotificationToasts, useNotificationToasts, useUnreadCount } from "./notifications";

const get = vi.fn();
vi.mock("@/lib/api", () => ({ api: { get: (...a: unknown[]) => get(...a) } }));

function notif(id: string, title: string, read = false) {
  return { id, kind: "task_assigned", title, body: "Harbor Dental", read, createdAt: new Date().toISOString() };
}

let inbox: ReturnType<typeof notif>[] = [];
let unreadValue = 0;

// Renders the observed count so a test can WAIT for the hook to have seen it. The
// hook compares against the previous OBSERVED value, so a test that changes the count
// twice before React has rendered the first one never produces a rise at all.
function Harness({ enabled = true, userId }: { enabled?: boolean; userId?: string }) {
  const q = useUnreadCount();
  useNotificationToasts(enabled, userId);
  return <div data-testid="seen">{String(q.data?.unread)}</div>;
}

function setup(enabled = true, userId = "user-a") {
  // The REAL app client, not a bare one. `makeQueryClient` sets `staleTime: 30_000`,
  // and a hand-rolled client defaults it to 0 — which silently hides the worst bug
  // this hook can have: `fetchQuery` serving the pre-arrival list from cache.
  const qc = makeQueryClient();
  const view = render(
    <QueryClientProvider client={qc}>
      <ToastProvider><Harness enabled={enabled} userId={userId} /></ToastProvider>
    </QueryClientProvider>,
  );
  /** Simulate a poll landing with this unread count, and let the hook observe it.
   *  Moves the value the endpoint returns and refetches, rather than writing the
   *  cache — a cache write is overwritten by the query's own next result.
   *  Awaited per call on purpose: the hook compares against the PREVIOUS observed
   *  value, so two counts applied in one render collapse into a single baseline and
   *  no rise is ever seen. */
  const poll = async (n: number) => {
    unreadValue = n;
    await act(async () => { await qc.refetchQueries({ queryKey: UNREAD_KEY }); });
    await waitFor(() =>
      expect(screen.getAllByTestId("seen").at(-1)).toHaveTextContent(String(n)),
    );
  };
  return { ...view, poll, qc };
}

beforeEach(() => {
  inbox = [notif("n1", "New task assigned")];
  unreadValue = 0;
  // The announced-id memory is module state (it has to outlive a page navigation),
  // so it must be cleared between tests or they leak into each other.
  resetNotificationToasts();
  get.mockReset();
  get.mockImplementation((path: string) => {
    if (path === "/notifications/unread-count") return Promise.resolve({ unread: unreadValue });
    if (path === "/notifications") return Promise.resolve(inbox);
    return Promise.resolve([]);
  });
});

describe("arrival toasts", () => {
  it("does not announce the backlog on mount", async () => {
    // Signing in with unread mail must not fire a burst of toasts for things that
    // arrived while you were away. The first observation is only a baseline.
    // The count is already 12 before the first render, so the hook's very first
    // observation IS the backlog — exactly the sign-in case.
    unreadValue = 12;
    setup();
    await waitFor(() => expect(screen.getByTestId("seen")).toHaveTextContent("12"));
    expect(screen.queryByText("New task assigned")).not.toBeInTheDocument();
    // ...and it must not have fetched the inbox to work that out.
    expect(get).not.toHaveBeenCalledWith("/notifications");
  });

  it("announces a notification that arrives while the portal is open", async () => {
    const { poll } = setup();
    await poll(0);           // baseline
    await poll(1);           // something arrived
    expect(await screen.findByText("New task assigned")).toBeInTheDocument();
  });

  it("announces the same notification only once", async () => {
    const { poll } = setup();
    await poll(0);
    await poll(1);
    expect(await screen.findByText("New task assigned")).toBeInTheDocument();
    // Read it somewhere else, then have another arrive. The already-announced row must
    // not be re-toasted just because the count crossed the same boundary again.
    await poll(0);
    inbox = [notif("n1", "New task assigned"), notif("n2", "Deadline decided")];
    await poll(1);
    expect(await screen.findByText("Deadline decided")).toBeInTheDocument();
    expect(screen.getAllByText("New task assigned")).toHaveLength(1);
  });

  it("caps a burst and summarises the rest", async () => {
    inbox = [
      notif("a", "One"), notif("b", "Two"), notif("c", "Three"),
      notif("d", "Four"), notif("e", "Five"),
    ];
    const { poll } = setup();
    await poll(0);
    await poll(5);
    expect(await screen.findByText("One")).toBeInTheDocument();
    expect(screen.getByText("Three")).toBeInTheDocument();
    // Five arrivals must not bury the screen in five toasts.
    expect(screen.queryByText("Four")).not.toBeInTheDocument();
    expect(screen.getByText("2 more notifications")).toBeInTheDocument();
  });

  it("never announces an already-read notification", async () => {
    inbox = [notif("n1", "Already seen", true)];
    const { poll } = setup();
    await poll(0);
    await poll(1);
    await waitFor(() => expect(get).toHaveBeenCalledWith("/notifications"));
    expect(screen.queryByText("Already seen")).not.toBeInTheDocument();
  });

  it("does nothing at all while disabled", async () => {
    const { poll } = setup(false);
    await poll(0);
    await poll(3);
    await screen.findByTestId("seen");
    await waitFor(() => expect(get).not.toHaveBeenCalledWith("/notifications"));
  });
  it("reads the LIVE inbox on arrival, never a cached one", async () => {
    // The defect this pins, found by adversarial review and invisible to a test that
    // builds its own QueryClient: `fetchQuery` inherits the app-wide staleTime of 30s.
    // Open the bell (the list is cached), close it, and have a task assigned within
    // 30s — without `staleTime: 0` the cached PRE-arrival list comes back, so the row
    // the operator was just looking at gets toasted and the task that actually
    // arrived does not.
    // The operator opened the bell moments ago and read what was there, so the
    // PRE-arrival list is in cache and its rows are read.
    inbox = [notif("old", "Already on screen", true)];
    const { poll, qc } = setup();
    await qc.fetchQuery({ queryKey: ["notifications"], queryFn: () => api.get("/notifications") });
    await poll(0);
    // ...and only now does the task actually arrive.
    inbox = [notif("new", "Task just assigned"), notif("old", "Already on screen", true)];
    await poll(1);
    // Serving the 30s-stale cached list would return the PRE-arrival rows — all read,
    // so nothing would be announced and the arrival would be silently dropped.
    expect(await screen.findByText("Task just assigned")).toBeInTheDocument();
  });

  it("keeps its memory across a page navigation", async () => {
    // TopBar (and so the bell) is mounted per PAGE, not by a layout, so every
    // client-side navigation remounts this hook. Per-mount refs meant "already
    // announced" was forgotten on every route change and the whole unread list was
    // re-toasted on the next arrival.
    const { poll, unmount } = setup();
    await poll(0);
    await poll(1);
    expect(await screen.findByText("New task assigned")).toBeInTheDocument();

    unmount();                       // navigate away
    const second = setup();          // ...and land on the next page
    inbox = [notif("n1", "New task assigned"), notif("n2", "Deadline decided")];
    await second.poll(1);
    await second.poll(2);
    expect(await screen.findByText("Deadline decided")).toBeInTheDocument();
    expect(screen.queryByText("New task assigned")).not.toBeInTheDocument();
  });

  it("does not inherit the previous user's baseline", async () => {
    // The QueryClient outlives a sign-out, so without an owner stamp the next person
    // to sign in is baselined on the last person's count and has their own backlog
    // announced as if it had just arrived.
    const first = setup(true, "user-a");
    await first.poll(0);
    await first.poll(1);
    expect(await screen.findByText("New task assigned")).toBeInTheDocument();
    first.unmount();

    inbox = [notif("x1", "User B backlog")];
    unreadValue = 7;                 // B already has 7 unread when they sign in
    setup(true, "user-b");
    await waitFor(() =>
      expect(screen.getAllByTestId("seen").at(-1)).toHaveTextContent("7"),
    );
    // B's own backlog is B's FIRST observation, so it is a baseline — not an arrival.
    expect(screen.queryByText("User B backlog")).not.toBeInTheDocument();
  });
});
