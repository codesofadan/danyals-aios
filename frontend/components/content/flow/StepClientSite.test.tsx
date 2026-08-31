/**
 * Screen 1 of the content flow: choosing the client, and optionally a site.
 *
 * THE DEFECT. A client with no `sites` row could not leave this screen. The Next
 * button's blocker was:
 *
 *     if (!state.siteDomain) return "Choose which of their sites these pages go on.";
 *
 * and the screen offered nothing to satisfy it but an empty state reading "Add one
 * on the client's page". No such control existed anywhere in the product -
 * POST /clients/{id}/sites had zero frontend callers - so the instruction named a
 * place that did not exist and the flow was simply unexitable for that client.
 *
 * The requirement was NOT to hide the message. It was to establish whether the
 * dependency is real, and remove it if it is not. It is not: `site_domain` is
 * optional on both content creation schemas, `_chosen_site` tolerates None, and
 * generation completes without one (verified against the live API - a client with
 * zero sites produced content job CJ-4251, which reached the pipeline's experience
 * gate normally).
 *
 * So the three states below are all legitimate, and each has to keep working:
 * a registered site, a domain derived from the client's business profile, and no
 * site at all.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import StepClientSite from "./StepClientSite";
import { EMPTY_FLOW, type FlowState } from "./types";

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

const CLIENT = { id: "cl-1", cn: "Leeds Drainage" };

/** sites: what GET /clients/cl-1/sites returns. profile: the business profile. */
function mockApi({
  sites = [] as Array<{ id: string; clientId: string; domain: string; cms: string }>,
  websiteUrl = "",
  profile404 = false,
}) {
  get.mockImplementation(async (path: string) => {
    if (path.includes("/sites")) return sites;
    if (path.includes("/business-profile")) {
      if (profile404) {
        const { ApiError } = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
        throw new ApiError(404, "not_found", "no profile", "req-1");
      }
      return { websiteUrl };
    }
    if (path.startsWith("/clients")) return [CLIENT];
    return [];
  });
}

function renderStep(over: Partial<FlowState> = {}) {
  const patch = vi.fn();
  const state: FlowState = { ...EMPTY_FLOW, clientId: "cl-1", clientName: "Leeds Drainage", ...over };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <StepClientSite state={state} patch={patch} />
    </QueryClientProvider>,
  );
  return patch;
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
});

describe("StepClientSite - a client with no registered site", () => {
  it("does not tell the operator to use a control that does not exist", async () => {
    mockApi({ sites: [], websiteUrl: "" });
    renderStep();

    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(screen.queryByText(/add one on the client's page/i)).toBeNull();
    expect(screen.queryByText(/this client has no site registered/i)).toBeNull();
  });

  it("says what will happen instead of refusing to continue", async () => {
    mockApi({ sites: [], websiteUrl: "" });
    renderStep();

    expect(
      await screen.findByText(/you can still write the pages now/i),
    ).toBeInTheDocument();
  });

  it("offers the website already on the client's business profile", async () => {
    mockApi({ sites: [], websiteUrl: "https://www.leedsdrainage.co.uk/contact" });
    renderStep();

    // Normalised to a bare domain, matching what the backend compares against.
    expect(await screen.findByText("leedsdrainage.co.uk")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /use this site/i })).toBeInTheDocument();
  });

  it("registers the derived site and marks it registered, so it may be published to", async () => {
    mockApi({ sites: [], websiteUrl: "https://leedsdrainage.co.uk" });
    post.mockResolvedValue({ id: "s-1", clientId: "cl-1", domain: "leedsdrainage.co.uk", cms: "wordpress" });
    const patch = renderStep();

    await userEvent.click(await screen.findByRole("button", { name: /use this site/i }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/clients/cl-1/sites", {
        domain: "leedsdrainage.co.uk",
        cms_type: "wordpress",
      }),
    );
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith(
        expect.objectContaining({ siteDomain: "leedsdrainage.co.uk", siteRegistered: true }),
      ),
    );
  });

  it("falls back to research-only when the caller may not register a site", async () => {
    // Registering is lead-only (ManageClients). A member must not be stranded: the
    // domain is still usable for research, it just cannot be the publish target -
    // and siteRegistered must stay false so StepLaunch omits it (the backend 400s
    // on a domain that is not registered to the client).
    mockApi({ sites: [], websiteUrl: "https://leedsdrainage.co.uk" });
    const { ApiError } = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
    post.mockRejectedValue(new ApiError(403, "forbidden", "nope", "req-2"));
    const patch = renderStep();

    await userEvent.click(await screen.findByRole("button", { name: /use this site/i }));

    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith(
        expect.objectContaining({ siteDomain: "leedsdrainage.co.uk", siteRegistered: false }),
      ),
    );
    expect(await screen.findByText(/research only/i)).toBeInTheDocument();
  });

  it("survives a client whose business profile does not exist at all", async () => {
    mockApi({ sites: [], profile404: true });
    renderStep();

    expect(await screen.findByText(/you can still write the pages now/i)).toBeInTheDocument();
  });
});

describe("StepClientSite - a client that does have sites", () => {
  const SITES = [
    { id: "s-1", clientId: "cl-1", domain: "leedsdrainage.co.uk", cms: "wordpress" },
    { id: "s-2", clientId: "cl-1", domain: "leeds-drains.com", cms: "wordpress" },
  ];

  it("still lists them and still marks a pick as registered", async () => {
    mockApi({ sites: SITES, websiteUrl: "" });
    const patch = renderStep();

    const select = await screen.findByLabelText("Site");
    await userEvent.selectOptions(select, "leeds-drains.com");

    expect(patch).toHaveBeenCalledWith(
      expect.objectContaining({ siteDomain: "leeds-drains.com", siteRegistered: true }),
    );
  });

  it("does not offer to register a profile site that is already registered", async () => {
    // Otherwise the operator is invited to create a duplicate row for a site the
    // client already has, differing only by scheme or a www prefix.
    mockApi({ sites: SITES, websiteUrl: "https://www.leedsdrainage.co.uk" });
    renderStep();

    await screen.findByLabelText("Site");
    expect(screen.queryByRole("button", { name: /use this site/i })).toBeNull();
  });
});
