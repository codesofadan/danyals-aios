/**
 * The campaign wizard's two load-bearing promises.
 *
 * 1. THE QUOTE THE OPERATOR APPROVES IS THE THING THAT GETS CREATED. The Create button
 *    reads live form state, so without invalidation an operator could price three
 *    articles, add seven more topics, and press Create — getting ten, while the screen
 *    still showed the three-article price and finish date. That is the tool misleading
 *    the person using it about what they just authorised and what it will cost.
 *
 * 2. ASKING FOR N COPIES OF ONE ARTICLE IS UNREPRESENTABLE. The article count is DERIVED
 *    from the topic list rather than typed, because one topic across N platforms
 *    produces N byte-identical articles (measured: resemblance 1.000).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Web2CampaignWizard from "./Web2CampaignWizard";

const posts: Array<{ path: string; body: Record<string, unknown> }> = [];

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(async (path: string) => {
      if (path.startsWith("/offpage/web2/platform-board")) {
        return [
          { name: "Blogger", platform: "Blogger", status: "eligible", reason: "", authorityTier: "high" },
          { name: "Tumblr", platform: "Tumblr", status: "eligible", reason: "", authorityTier: "high" },
          {
            name: "dev.to", platform: "dev.to", status: "not_eligible",
            reason: "Restricted to developer clients.", authorityTier: "medium",
          },
        ];
      }
      if (path.startsWith("/clients")) return [{ id: "cl-1", cn: "Leeds Drainage" }];
      return [];
    }),
    post: vi.fn(async (path: string, body: Record<string, unknown>) => {
      posts.push({ path, body });
      if (path.endsWith("/estimate")) {
        const topics = (body.topics as string[]) ?? [];
        return {
          count: topics.length,
          estimatedCostUsd: topics.length * 0.15,
          projectedCompletion: "2026-10-01T09:00:00Z",
          properties: topics.map((t) => ({
            platform: "Blogger", topic: t, anchor: "Leeds Drainage",
            framework: "PAS", scheduledFor: "2026-09-02T09:00:00Z",
          })),
          notes: [],
        };
      }
      return { id: "cmp-1", total: ((body.topics as string[]) ?? []).length };
    }),
  },
}));

vi.mock("@/lib/hooks/clients", () => ({
  useClients: () => ({ data: [{ id: "cl-1", cn: "Leeds Drainage" }] }),
}));

function renderWizard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Web2CampaignWizard onClose={() => {}} />
    </QueryClientProvider>,
  );
}

async function fillMinimum(topics: string) {
  // Two selects exist (client, pacing); the client one is first.
  const [clientSelect] = screen.getAllByRole("combobox") as HTMLSelectElement[];
  fireEvent.change(clientSelect, { target: { value: "cl-1" } });
  fireEvent.change(screen.getByPlaceholderText(/emergency drain unblocking/i), {
    target: { value: topics },
  });
  fireEvent.change(screen.getByPlaceholderText(/https:\/\/client.example/i), {
    target: { value: "https://leedsdrainage.co.uk/drains" },
  });
  await waitFor(() => expect(screen.getByText("Blogger")).toBeTruthy());
  fireEvent.click(screen.getByText("Blogger"));
}

describe("Web2CampaignWizard", () => {
  beforeEach(() => {
    posts.length = 0;
  });

  it("will not create anything until a quote has been taken", async () => {
    renderWizard();
    await fillMinimum("one\ntwo");
    const create = screen.getByRole("button", { name: /Create/i }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);
    expect(posts.filter((p) => !p.path.endsWith("/estimate"))).toHaveLength(0);
  });

  it("invalidates the quote when the topic list changes, so the price shown always matches what is created", async () => {
    renderWizard();
    await fillMinimum("one\ntwo");

    fireEvent.click(screen.getByRole("button", { name: /Get quote/i }));
    await waitFor(() =>
      expect((screen.getByRole("button", { name: /Create/i }) as HTMLButtonElement).disabled).toBe(false),
    );

    // The operator adds three more topics AFTER pricing two.
    fireEvent.change(screen.getByPlaceholderText(/emergency drain unblocking/i), {
      target: { value: "one\ntwo\nthree\nfour\nfive" },
    });

    const create = screen.getByRole("button", { name: /Create/i }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);
    expect(screen.getByText(/campaign changed since that quote/i)).toBeTruthy();
    // And nothing was created behind the stale quote.
    expect(posts.filter((p) => !p.path.endsWith("/estimate"))).toHaveLength(0);
  });

  it("creates exactly what the current quote priced", async () => {
    renderWizard();
    await fillMinimum("one\ntwo\nthree");
    fireEvent.click(screen.getByRole("button", { name: /Get quote/i }));
    await waitFor(() =>
      expect((screen.getByRole("button", { name: /Create/i }) as HTMLButtonElement).disabled).toBe(false),
    );
    fireEvent.click(screen.getByRole("button", { name: /Create/i }));

    await waitFor(() => {
      const created = posts.filter((p) => !p.path.endsWith("/estimate"));
      expect(created).toHaveLength(1);
      expect((created[0].body.topics as string[])).toHaveLength(3);
      expect(created[0].body.articleCount).toBe(3);
    });
  });

  it("derives the article count from the topics, so N copies of one article cannot be requested", async () => {
    renderWizard();
    await fillMinimum("only one topic");
    fireEvent.click(screen.getByRole("button", { name: /Get quote/i }));
    await waitFor(() => {
      const estimates = posts.filter((p) => p.path.endsWith("/estimate"));
      expect(estimates[0].body.articleCount).toBe(1);
    });
    // There is no separate "how many articles" input to disagree with the topic list.
    expect(screen.queryByPlaceholderText(/how many/i)).toBeNull();
  });

  it("shows why an ineligible platform is not offered instead of hiding it", async () => {
    renderWizard();
    await fillMinimum("one");
    expect(screen.getByText(/1 platform\(s\) not available/i)).toBeTruthy();
    fireEvent.click(screen.getByText(/not available for this client/i));
    expect(screen.getByText(/Restricted to developer clients/i)).toBeTruthy();
  });
});
