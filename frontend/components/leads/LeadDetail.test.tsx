/**
 * §3 — a free-audit lead opens by its token, and "not found" is not "broken".
 *
 * THE DEFECT. LeadDetail found its lead by scanning `useLeads()` — the newest page
 * of the funnel inbox — so a link to any lead past that page rendered "No lead for
 * this token" while its report sat on disk. The link did not break; it rotted, as
 * the funnel filled up behind it.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import LeadDetail from "./LeadDetail";
import { ApiError } from "@/lib/api";

// DetailShell reaches for the app router (back navigation); jsdom has none.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  usePathname: () => "/admin/leads/tok-old",
  useSearchParams: () => new URLSearchParams(),
}));

const get = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: { ...actual.api, get: (p: string) => get(p) },
    getReportHtml: vi.fn(async () => "<html></html>"),
  };
});

const LEAD = {
  id: "pa-1",
  email: "lead@example.com",
  url: "https://lead.example",
  status: "done",
  score: 71,
  source: "landing",
  report_token: "tok-old",
  has_pdf: true,
  has_report: true,
  run_uuid: "run-1",
  error: null,
  created_at: "2026-09-01T00:00:00Z",
  updated_at: null,
};

function renderDetail(token = "tok-old") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <LeadDetail token={token} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  get.mockResolvedValue(LEAD);
});

describe("LeadDetail", () => {
  it("reads the lead by its token rather than scanning the inbox", async () => {
    renderDetail();

    expect(await screen.findByText("lead@example.com")).toBeInTheDocument();
    // The defect was structural: it asked for the LIST and searched it.
    const paths = get.mock.calls.map((c) => String(c[0]));
    expect(paths.some((p) => p.includes("/admin/public-audits/tok-old"))).toBe(true);
    expect(paths.some((p) => p === "/admin/public-audits")).toBe(false);
  });

  it("opens a lead that is nowhere near the first page of the funnel", async () => {
    // The whole point: page position is no longer part of reachability.
    renderDetail("tok-2000");

    expect(await screen.findByText("lead@example.com")).toBeInTheDocument();
  });

  it("says a token has no lead when the server says so", async () => {
    get.mockImplementation(async () => {
      throw new ApiError(404, "not_found", "Lead not found", "r1");
    });

    renderDetail("tok-missing");

    expect(await screen.findByText(/no lead for this token/i)).toBeInTheDocument();
    expect(screen.queryByText(/couldn't load the lead/i)).toBeNull();
  });

  it("keeps a real failure looking like a failure", async () => {
    get.mockImplementation(async () => {
      throw new ApiError(500, "server_error", "boom", "r2");
    });

    renderDetail();

    expect(await screen.findByText(/couldn't load the lead/i)).toBeInTheDocument();
    expect(screen.queryByText(/no lead for this token/i)).toBeNull();
  });
});
