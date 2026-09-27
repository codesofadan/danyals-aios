/**
 * "Write once, publish everywhere" — and the three things it must never quietly do.
 *
 *   • An EMPTY selection must not travel as "everywhere". The server refuses a blank
 *     list on purpose: "none chosen" and "all of them" are different intentions, and
 *     the composer sends the explicit `__all__` sentinel rather than letting a blank
 *     mean the expensive one.
 *   • Excluded platforms are RENDERED, with reasons. A selection silently shrunk from
 *     twenty to six is a lie an operator finds weeks later in a client report.
 *   • The commit sends ONE DISTINCT TOPIC PER PLACEMENT. This is the whole reason the
 *     plan step exists: the same subject sent verbatim to thirty platforms produced
 *     thirty byte-identical articles when it was measured (body r = 1.000), and the
 *     similarity gate blocked all thirty AFTER thirty drafting runs had been billed.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Web2BroadcastComposer from "./Web2BroadcastComposer";

const post = vi.fn(async (path: string, _body: unknown) => {
  if (path.includes("/broadcast/plan")) {
    return {
      clientId: "cl-1",
      subject: "Emergency drain unblocking",
      summary: "2 placement(s) planned across 2 platform(s); 1 platform excluded.",
      posts: [
        {
          platform: "Ghost", shape: "article", topic: "What a blocked drain costs",
          angle: "cost", framework: "problem-agitate-solve", wordTarget: 900,
          anchor: "Leeds Drainage Co",
        },
        {
          platform: "Bluesky", shape: "note", topic: "The 2am callout",
          angle: "urgency", framework: "story", wordTarget: 29,
          anchor: "Leeds Drainage Co",
        },
      ],
      excluded: [
        { platform: "Medium", reason: "Medium has no usable publishing API." },
      ],
      notes: ["Anchor 'emergency drains leeds' was not used: exact-match commercial."],
    };
  }
  return { id: "camp-1", title: "Emergency drain unblocking", client: "Leeds Drainage Co" };
});

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(async (path: string) => {
      if (path.startsWith("/clients")) return [{ id: "cl-1", cn: "Leeds Drainage Co" }];
      if (path.includes("/connection-plan")) {
        return {
          clientId: "cl-1", summary: "23 publish now, 30 need one step.",
          readyCount: 23, oneStepCount: 30, blockedCount: 0, platforms: [], notes: [],
        };
      }
      if (path.startsWith("/offpage/web2/platform-board")) {
        return [
          { name: "Ghost", platform: "Ghost", status: "eligible", reason: "", authorityTier: "high" },
          { name: "Bluesky", platform: "Bluesky", status: "eligible", reason: "", authorityTier: "medium" },
        ];
      }
      return [];
    }),
    post: (...args: unknown[]) => post(...(args as [string, unknown])),
    put: vi.fn(async () => ({})),
  },
}));

async function openAtPlatforms() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <Web2BroadcastComposer onClose={vi.fn()} />
    </QueryClientProvider>,
  );
  // Await the OPTION, not the select. Setting a value an option list does not yet
  // contain is a silent no-op, and every later step then fails for the wrong reason.
  await screen.findByRole("option", { name: "Leeds Drainage Co" });
  fireEvent.change(screen.getByLabelText(/Client/i), { target: { value: "cl-1" } });
  fireEvent.change(screen.getByLabelText(/What is this broadcast about/i), {
    target: { value: "Emergency drain unblocking" },
  });
  fireEvent.change(screen.getByLabelText(/The page every placement links to/i), {
    target: { value: "https://leedsdrainage.co.uk/emergency" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Choose platforms/i }));
}

async function planIt() {
  await openAtPlatforms();
  fireEvent.click(await screen.findByRole("button", { name: /Show me what goes where/i }));
  return screen.findByText(/2 placement\(s\) planned/i);
}

describe("choosing where it goes", () => {
  it("sends the explicit All sentinel rather than an empty list", async () => {
    await openAtPlatforms();
    post.mockClear();
    fireEvent.click(await screen.findByRole("button", { name: /Show me what goes where/i }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    const body = post.mock.calls[0][1] as { platforms: string[] };
    // An empty array would be REFUSED by the server — which is the correct design, and
    // exactly why the composer must state "everywhere" rather than imply it.
    expect(body.platforms).toEqual(["__all__"]);
  });

  it("releases All the moment a platform is ticked by hand", async () => {
    await openAtPlatforms();
    fireEvent.click(await screen.findByRole("button", { name: /Ghost/i }));
    post.mockClear();
    fireEvent.click(screen.getByRole("button", { name: /Show me what goes where/i }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    const body = post.mock.calls[0][1] as { platforms: string[] };
    // Ticking one platform is a NARROWER intention than All. Letting All survive the
    // click would publish to fifty platforms on a gesture that meant one.
    expect(body.platforms).toEqual(["Ghost"]);
  });
});

describe("the fan-out, before anything is paid for", () => {
  it("shows each platform's SHAPE, because a note is not a shortened article", async () => {
    await planIt();
    expect(screen.getByText("Article")).toBeInTheDocument();
    expect(screen.getByText("Note")).toBeInTheDocument();
    // The number that makes the difference concrete: 900 words versus 29.
    expect(screen.getByText(/~900 words/)).toBeInTheDocument();
    expect(screen.getByText(/~29 words/)).toBeInTheDocument();
  });

  it("renders excluded platforms with their reasons instead of dropping them", async () => {
    await planIt();
    expect(screen.getByText(/1 selected platform\(s\) will receive nothing/i)).toBeInTheDocument();
    expect(screen.getByText(/Medium has no usable publishing API/i)).toBeInTheDocument();
  });

  it("reports an anchor it refused, so the operator learns the rule", async () => {
    await planIt();
    expect(screen.getByText(/exact-match commercial/i)).toBeInTheDocument();
  });

  it("does not claim the commit publishes anything unread", async () => {
    await planIt();
    // Committing queues drafting runs; every property still stops at the review gate.
    // A button that said "Publish everywhere" would be describing something the
    // pipeline deliberately does not do.
    expect(screen.getByText(/held at the review gate/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Queue 2 placement\(s\)/i })).toBeInTheDocument();
  });
});

describe("committing", () => {
  it("sends one distinct topic per placement", async () => {
    await planIt();
    post.mockClear();
    fireEvent.click(screen.getByRole("button", { name: /Queue 2 placement\(s\)/i }));

    await waitFor(() => expect(post).toHaveBeenCalled());
    const [path, body] = post.mock.calls[0] as [string, Record<string, unknown>];
    expect(path).toBe("/offpage/web2/campaigns");
    // DISTINCT topics, in step with the platforms they were planned for. Reusing one
    // topic is what the campaign route refuses, and what produced identical articles.
    expect(body.topics).toEqual(["What a blocked drain costs", "The 2am callout"]);
    expect(body.platforms).toEqual(["Ghost", "Bluesky"]);
    expect(body.articleCount).toBe(2);
  });
});
