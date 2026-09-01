/**
 * The client's Reports library must tell "you have none" apart from "we couldn't ask".
 *
 * THE DEFECT. `const available = deliverablesQ.data ?? []` followed by a render that
 * branched only on isLoading then `available.length === 0`. A 500 or a dropped
 * connection therefore rendered "No reports yet — your first report will appear here
 * once it's generated" to a client who may have a dozen. The same defect class already
 * fixed in ClientMilestones, sitting one file over.
 *
 * THE FIX HAD ITS OWN TRAP, which is why the last test here exists. Branching on
 * `isError` alone would have been worse than the bug: react-query keeps the last good
 * data across a failed BACKGROUND refetch, so a single failed poll would blank out a
 * working report list — breaking the reports library the brief explicitly lists as
 * working, in the name of fixing an empty state. The failure branch is therefore
 * data-aware: it replaces the list only when there is nothing to show.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ClientReports from "./ClientReports";
import { ApiError } from "@/lib/api";

const get = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, get: (path: string) => get(path) } };
});

vi.mock("@/components/client/ClientHeader", () => ({
  default: ({ focus }: { focus: React.ReactNode }) => <div>{focus}</div>,
}));

const REPORT = {
  id: "d-1",
  title: "Technical SEO Audit",
  kind: "Audit",
  icon: "fact_check",
  period: "August 2026",
  issuedAt: "2026-08-29T19:08:02Z",
  sizeLabel: "1.2 MB",
  status: "ready",
};

function renderPage(client?: QueryClient) {
  const qc =
    client ??
    new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } });
  return render(
    <QueryClientProvider client={qc}>
      <ClientReports />
    </QueryClientProvider>,
  );
}

beforeEach(() => { get.mockReset(); get.mockResolvedValue([]); });

describe("ClientReports — empty is not the same as failed", () => {
  it("lists the reports a client actually has", async () => {
    get.mockResolvedValue([REPORT]);
    renderPage();

    expect(await screen.findByText("Technical SEO Audit")).toBeInTheDocument();
    expect(screen.getByText(/1 report ready/)).toBeInTheDocument();
  });

  it("says there are none yet when the server genuinely returns none", async () => {
    get.mockResolvedValue([]);
    renderPage();

    expect(await screen.findByText(/no reports yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/couldn't load your reports/i)).toBeNull();
  });

  it("NEVER tells a client they have no reports when the request failed", async () => {
    // The defect this file exists for.
    get.mockImplementation(async () => { throw new ApiError(500, "server_error", "boom", "req-1"); });
    renderPage();

    expect(await screen.findByText(/couldn't load your reports/i)).toBeInTheDocument();
    expect(screen.queryByText(/no reports yet/i)).toBeNull();
    expect(screen.queryByText(/once it's generated/i)).toBeNull();
  });

  it("does not claim a ready-count in the header on a failure either", async () => {
    // The header asserts independently of the body, so fixing only the body would
    // leave "0 reports ready" beside the error — the same lie in a second place.
    get.mockImplementation(async () => { throw new ApiError(500, "server_error", "boom", "req-2"); });
    renderPage();

    await screen.findByText(/couldn't load your reports/i);
    expect(screen.queryByText(/reports? ready/i)).toBeNull();
  });

  it("offers a retry that recovers", async () => {
    get.mockImplementationOnce(async () => { throw new ApiError(500, "server_error", "boom", "req-3"); });
    renderPage();

    await screen.findByText(/couldn't load your reports/i);
    get.mockResolvedValue([REPORT]);

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText("Technical SEO Audit")).toBeInTheDocument();
  });

  it("keeps showing a working list when a background REFETCH fails", async () => {
    // The trap in the fix. react-query holds the last good data through a failed
    // refetch, so an isError-only branch would blank out a list the client can
    // still legitimately read — turning an empty-state bug into a data-loss bug.
    get.mockResolvedValue([REPORT]);
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 0 } },
    });
    renderPage(qc);
    await screen.findByText("Technical SEO Audit");

    get.mockImplementation(async () => { throw new ApiError(500, "server_error", "boom", "req-4"); });
    await qc.refetchQueries({ queryKey: ["portal", "deliverables"] });

    await waitFor(() => {
      expect(screen.getByText("Technical SEO Audit")).toBeInTheDocument();
    });
    expect(screen.queryByText(/couldn't load your reports/i)).toBeNull();
    expect(screen.getByText(/1 report ready/)).toBeInTheDocument();
  });
});
