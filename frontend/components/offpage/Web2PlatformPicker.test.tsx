/**
 * The platform picker's refusal rules.
 *
 * THESE TESTS MOVED HERE from `Web2PlanModal.test.tsx` on 2026-09-12, when the single-
 * property modal stopped asking for a platform at all (the server now picks one, and
 * the publish route is chosen at the review gate). The modal was where these rules
 * happened to be exercised; the picker is where they LIVE, and it is still mounted by
 * the campaign wizard. Deleting them with the modal's picker would have silently
 * dropped the guard on the defect they exist for:
 *
 *   IT OFFERED PLATFORMS THE SERVER REFUSES, from a static client-side list, while the
 *   backend decides eligibility per client from real credentials. Almost every
 *   selection then 422'd - after the drafting spend, and invisibly.
 *
 * The distinction the picker must keep is between a FACT about the machine (no
 * credential, no publisher - unpickable, because no acknowledgement conjures either)
 * and a JUDGEMENT about fit (a topical mismatch, unread terms - pickable behind one
 * informed acknowledgement). Collapsing them sends an operator hunting for a token
 * that would not have helped.
 *
 * The extension lane is a THIRD thing, added 2026-09-12: pickable, and NOT an
 * advisory - nothing about it needs acknowledging, it simply publishes by a different
 * hand. Lumping it in with the reviewed-exclusion warning would train an operator to
 * tick the box that does matter without reading it.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Web2PlatformPicker from "./Web2PlatformPicker";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(async (path: string) => {
      if (path.startsWith("/offpage/web2/platform-board")) {
        return [
          { name: "Blogger", platform: "Blogger", status: "eligible", reason: "", authorityTier: "high" },
          {
            name: "Tumblr", platform: "Tumblr", status: "not_connected",
            reason: "Eligible for this client, but no account is connected yet.",
            authorityTier: "high",
            setupSteps: "Create an app and save the token.", setupUrl: "https://tumblr.example",
          },
          {
            name: "dev.to", platform: "dev.to", status: "not_eligible",
            reason: "Restricted to developer clients.", authorityTier: "medium",
            termsCheckedOn: "2026-08-23",
          },
          {
            name: "Plurk", platform: "Plurk", status: "not_reviewed",
            reason: "Not yet reviewed: nobody has read this platform's terms.",
            authorityTier: "low",
          },
          {
            name: "Telegra.ph", platform: "Telegra.ph", status: "eligible_extension",
            reason: "Extension-assisted: an operator publishes here in their own session.",
            authorityTier: "low",
          },
          {
            name: "Wix", platform: null, status: "not_supported",
            reason: "No publisher exists for this platform yet.", authorityTier: "low",
          },
        ];
      }
      return [];
    }),
    post: vi.fn(async () => ({})),
  },
}));

function renderPicker(selected = new Set<string>(), onToggle = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <Web2PlatformPicker clientId="cl-1" selected={selected} onToggle={onToggle} />
    </QueryClientProvider>,
  );
  return onToggle;
}

describe("which platforms the picker offers", () => {
  it("offers what the server says is usable, and never what it refuses", async () => {
    renderPicker();
    expect(await screen.findByRole("button", { name: /Blogger/i })).toBeInTheDocument();

    // JUDGEMENT states are the operator's call, so they are PICKABLE - this is what
    // makes every platform the pipeline can drive reachable for every client.
    expect(screen.getByRole("button", { name: /dev\.to/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Plurk/i })).toBeInTheDocument();

    // FACTS about the machine stay unpickable: no credential, no publisher. Offering
    // them would queue work that can only fail, after the drafting spend.
    expect(screen.queryByRole("button", { name: /^Tumblr/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Wix/i })).not.toBeInTheDocument();
    expect(screen.getByText(/connect an account/i)).toBeInTheDocument();
    expect(screen.getByText(/no publisher built yet/i)).toBeInTheDocument();
  });

  it("asks for an acknowledgement, quoting the platform's own rule, before using it", async () => {
    renderPicker(new Set(["dev.to"]));
    // The rule itself is quoted - an operator who reads "restricted to developer
    // clients" learns the rule; one who reads "are you sure?" learns nothing.
    expect(await screen.findByText(/Restricted to developer clients/i)).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: /choosing them for this client anyway/i }),
    ).not.toBeChecked();
  });

  it("offers the extension lane, and does NOT treat it as an advisory", async () => {
    // The lane was previously displayed inside a collapsed <details> as "not through
    // this pipeline", which left 15 real, usable platforms visible but unreachable -
    // and left the build button permanently disabled for any client whose only open
    // platforms were extension-lane.
    renderPicker(new Set(["Telegra.ph"]));
    const tab = await screen.findByRole("button", { name: /Telegra\.ph/i });
    expect(tab).toBeInTheDocument();
    expect(tab).toHaveTextContent(/EXT/);
    // Choosing it must NOT raise the reviewed-exclusion acknowledgement: there is no
    // risk to accept, and a habitual tick here would devalue the real one.
    expect(
      screen.queryByRole("checkbox", { name: /choosing them for this client anyway/i }),
    ).not.toBeInTheDocument();
  });

  it("reports a choice by the platform key the server uses", async () => {
    const onToggle = renderPicker();
    fireEvent.click(await screen.findByRole("button", { name: /Blogger/i }));
    expect(onToggle).toHaveBeenCalledWith("Blogger");
  });
});
