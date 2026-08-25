// The reporting page.
//
// It had been cut to a single panel — Scheduled Jobs — which left eight `/reports/*`
// endpoints with no caller: no way to see a produced report, a client workbook, the
// sync history, or whether Google Sheets was connected at all. Six built, live-wired
// components sat unreachable.
//
// Two properties are pinned here because both were wrong before, and both are about
// telling an operator the truth rather than about layout:
//
//   1. An EMPTY scheduled-jobs list must say the schedule is deliberately paused.
//      Celery's `beat_schedule` is `{}` on purpose while the job-retry contract is
//      finished. "No scheduled jobs are configured" reads as a broken deployment, and
//      an operator who believes that will go looking for a fault that is not there.
//
//   2. The "open in Sheets" affordances must not be `href="#"`. Both were: a link that
//      looked live, went nowhere, and sat beside a real sheet id.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import ReportsWorkspace from "./ReportsWorkspace";
import { sheetUrl } from "@/lib/reports";

const empty = { data: [], isLoading: false, isError: false, error: null };

// ReportsLibrary also reads the audit ledger (an audit with a stored PDF is a real
// downloadable report, so the library shows both sources).
vi.mock("@/lib/hooks/audits", () => ({ useAudits: () => empty }));

vi.mock("@/lib/hooks/reports", () => ({
  useScheduledJobs: () => empty,
  useWorkbooks: () => empty,
  useSyncEvents: () => empty,
  useGeneratedReports: () => empty,
  useReportTypes: () => empty,
  useConnection: () => ({ data: undefined, isLoading: false, isError: false, error: null }),
  useSyncWorkbook: () => ({ mutate: vi.fn(), isPending: false, error: null, variables: undefined }),
  useSyncAllWorkbooks: () => ({ mutate: vi.fn(), isPending: false, error: null }),
}));

describe("ReportsWorkspace", () => {
  it("explains that the cron schedule is paused rather than implying a fault", () => {
    render(<ReportsWorkspace />);
    expect(screen.getByTestId("jobs-parked")).toBeInTheDocument();
    expect(screen.getByText(/Background jobs are paused/i)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/No scheduled jobs are configured/i);
  });

  it("reaches the report library and the Sheets plumbing, not just the job list", async () => {
    const user = userEvent.setup();
    render(<ReportsWorkspace />);

    await user.click(screen.getByRole("tab", { name: /Report library/i }));
    expect(screen.getByText("Reports library")).toBeInTheDocument();
    expect(screen.getByText("Client workbooks")).toBeInTheDocument();  // the KPI row

    await user.click(screen.getByRole("tab", { name: /Sheets sync/i }));
    // Exact strings: these titles also appear as sub-captions elsewhere in the tab.
    expect(screen.getByText("Sheets connection")).toBeInTheDocument();
    expect(screen.getAllByText("Sync activity").length).toBeGreaterThan(0);
    expect(screen.getByText("Per-client workbooks")).toBeInTheDocument();
  });

  it("never renders a link to nowhere", async () => {
    const user = userEvent.setup();
    const { container } = render(<ReportsWorkspace />);
    await user.click(screen.getByRole("tab", { name: /Sheets sync/i }));

    const deadLinks = [...container.querySelectorAll('a[href="#"]')];
    expect(deadLinks, 'an href="#" is back — build the real Sheets URL, or render a non-interactive state').toEqual([]);
  });
});

describe("sheetUrl", () => {
  it("builds a real Google Sheets URL from an id", () => {
    expect(sheetUrl("1M4stRollupX")).toBe("https://docs.google.com/spreadsheets/d/1M4stRollupX");
  });

  it("returns null when there is no sheet, so callers cannot link to nowhere", () => {
    for (const empty of ["", "   ", null, undefined]) {
      expect(sheetUrl(empty)).toBeNull();
    }
  });
});
