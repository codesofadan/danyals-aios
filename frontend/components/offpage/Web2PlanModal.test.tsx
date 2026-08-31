/**
 * Building ONE Web 2.0 property.
 *
 * QA reported "Single Property option is not working". It was three defects wearing
 * one symptom, and each is pinned below:
 *
 *  1. IT REPORTED SUCCESS FOR TOTAL FAILURE. A per-platform `Promise.allSettled`
 *     fan-out counted only fulfilled results and then showed the success panel
 *     unconditionally — so every request could 422 and the operator still read
 *     "Queued 0 properties — the write worker is drafting now."
 *  2. IT OFFERED PLATFORMS THE SERVER REFUSES, from a static client-side list, while
 *     the backend decides eligibility per client from real credentials.
 *  3. IT NEVER SENT A TOPIC, so `plan_web2` fell back to `topic = anchor` and every
 *     article was written about its own link text.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Web2PlanModal from "./Web2PlanModal";

const posts: Array<{ path: string; body: Record<string, unknown> }> = [];
let planFails = false;
let anchorAllowed = true;

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(async (path: string) => {
      if (path.startsWith("/offpage/web2/platform-board")) {
        return [
          { name: "Blogger", platform: "Blogger", status: "eligible", reason: "", authorityTier: "high" },
          {
            name: "Tumblr", platform: "Tumblr", status: "not_connected",
            reason: "", authorityTier: "high",
            setupSteps: "Create an app and save the token.", setupUrl: "https://tumblr.example",
          },
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
      if (path.endsWith("/anchor-check")) {
        return anchorAllowed
          ? { allowed: true, verdict: "ok", reason: "", suggestion: "" }
          : {
              allowed: false, verdict: "exact_match",
              reason: "an exact-match commercial anchor has no editorial justification",
              suggestion: "Leeds Drainage",
            };
      }
      if (path.endsWith("/plan")) {
        if (planFails) throw new Error("Blogger cannot be used for this client.");
        return { id: "w2-1", platform: String(body.platform ?? "Blogger") };
      }
      return {};
    }),
  },
}));

function renderModal() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Web2PlanModal onClose={vi.fn()} />
    </QueryClientProvider>,
  );
}

/** Pick the client once its options have actually loaded (changing a select to a
 *  value whose <option> is not rendered yet is a silent no-op). */
async function chooseClient() {
  await screen.findByRole("option", { name: /Leeds Drainage/i });
  fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "cl-1" } });
}

async function fillForm() {
  await chooseClient();
  const platform = await screen.findByRole("button", { name: /Blogger/i });
  fireEvent.click(platform);
  fireEvent.change(screen.getByPlaceholderText(/CCTV drain survey/i), {
    target: { value: "what a drain survey shows" },
  });
  fireEvent.change(screen.getByPlaceholderText(/gentle dental cleanings/i), {
    target: { value: "the drainage team" },
  });
  fireEvent.change(screen.getByPlaceholderText(/client.example/i), {
    target: { value: "https://client.example/services" },
  });
}

beforeEach(() => {
  posts.length = 0;
  planFails = false;
  anchorAllowed = true;
});

describe("building one property", () => {
  it("offers only platforms the server says are eligible", async () => {
    renderModal();
    await chooseClient();
    expect(await screen.findByRole("button", { name: /Blogger/i })).toBeInTheDocument();
    // Not selectable: one needs a credential, the other is refused for this client.
    expect(screen.queryByRole("button", { name: /^Tumblr/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^dev\.to/i })).not.toBeInTheDocument();
    // ...but both are still explained rather than silently dropped.
    expect(screen.getByText(/connect an account/i)).toBeInTheDocument();
    expect(screen.getByText(/not available for this client/i)).toBeInTheDocument();
  });

  it("never shows success when the server refused", async () => {
    // The regression test for the reported defect: this fails against the old fan-out,
    // which showed "Queued 0 properties — the write worker is drafting now."
    planFails = true;
    renderModal();
    await fillForm();
    fireEvent.click(screen.getByRole("button", { name: /Build this property/i }));
    expect(await screen.findByText(/Nothing was queued/i)).toBeInTheDocument();
    expect(screen.queryByText(/write worker is drafting/i)).not.toBeInTheDocument();
    // Still on the form, so the operator can correct and retry.
    expect(screen.getByRole("button", { name: /Build this property/i })).toBeInTheDocument();
  });

  it("sends exactly one plan request, with a topic distinct from the anchor", async () => {
    renderModal();
    await fillForm();
    fireEvent.click(screen.getByRole("button", { name: /Build this property/i }));
    await waitFor(() => expect(posts.filter((p) => p.path.endsWith("/plan"))).toHaveLength(1));
    const body = posts.find((p) => p.path.endsWith("/plan"))!.body;
    expect(body.platform).toBe("Blogger");
    expect(body.topic).toBe("what a drain survey shows");
    expect(body.anchor).toBe("the drainage team");
    // The whole point: the article is no longer written about its own link text.
    expect(body.topic).not.toBe(body.anchor);
  });

  it("blocks a refused anchor before anything is spent", async () => {
    anchorAllowed = false;
    renderModal();
    await fillForm();
    fireEvent.blur(screen.getByPlaceholderText(/gentle dental cleanings/i));
    expect(await screen.findByText(/no editorial justification/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Build this property/i })).toBeDisabled();
    // The refusal is free — the plan route was never called.
    expect(posts.filter((p) => p.path.endsWith("/plan"))).toHaveLength(0);
  });

  it("reports the property it actually created", async () => {
    renderModal();
    await fillForm();
    fireEvent.click(screen.getByRole("button", { name: /Build this property/i }));
    expect(await screen.findByText(/write worker is drafting/i)).toBeInTheDocument();
    expect(screen.getByText("Blogger")).toBeInTheDocument();
  });
});
