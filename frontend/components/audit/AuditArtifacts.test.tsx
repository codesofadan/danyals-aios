// The artifact column, in the audit queue.
//
// The in-dashboard report viewer was mounted but unreachable: a cleanup removed
// the control that opened it, and `setViewId` was left with exactly one call site
// passing `null`. The component rendered `{viewId && <ReportViewer .../>}` over a
// state nothing could ever set, so the report page an operator remembered simply
// stopped existing - with no error, no empty state, and a green test suite.
//
// Two properties are pinned here:
//
//   1. The viewer is REACHABLE. A control exists that opens it.
//   2. It is gated on STATUS, not on `pdf`. report.html is resolved by convention
//      and survives a failed PDF render, so a run whose PDF backend was
//      unavailable must still be readable.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const row = (over: Record<string, unknown> = {}) => ({
  id: "aud-1",
  client: "Verde Cafe",
  url: "verdecafe.co",
  types: ["technical"],
  tier: "Free",
  status: "done",
  depth: "free",
  maxPages: 15,
  estimatedCost: 0,
  cost: 0,
  score: 74,
  runtime: "4m 48s",
  when: "Today · 09:14",
  pdf: true,
  json: true,
  visibleToClient: false,
  ...over,
});

const rows = [
  row(),
  // A finished run whose PDF never rendered. Still readable.
  row({ id: "aud-2", client: "NorthPeak", pdf: false }),
  row({ id: "aud-3", client: "Halewood", status: "running" }),
];

vi.mock("@/lib/hooks/audits", () => ({
  AUDITS_PAGE: 200,
  useAudits: () => ({ data: rows, isLoading: false, isError: false, isFetching: false, error: null }),
  useAuditStats: () => ({ data: undefined, isLoading: false, isError: false }),
  useCreateAudit: () => ({ mutate: vi.fn(), isPending: false }),
  useAuditEstimate: () => ({ mutate: vi.fn(), isPending: false }),
  useSetAuditVisibility: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/lib/hooks/clients", () => ({
  useClients: () => ({ data: [{ id: "c-1", name: "Verde Cafe" }], isLoading: false }),
}));
vi.mock("@/lib/hooks/cost", () => ({ useSpendHalted: () => ({ halted: false }) }));
vi.mock("@/lib/api", () => ({
  downloadFile: vi.fn(),
  getReportHtml: vi.fn(async () => "<h1>report</h1>"),
}));
vi.mock("@/components/report/ReportViewer", () => ({
  default: ({ label }: { label: string }) => <div data-testid="viewer">{label}</div>,
}));

import AuditWorkspace from "./AuditWorkspace";

const openers = () =>
  screen.getAllByTitle("Read the full report in the page viewer") as HTMLButtonElement[];

describe("the artifact column", () => {
  it("links to the audit workspace - the page with the tabs", () => {
    // `/admin/audit/<id>`: Overview, Strategy, Issues, Pages, Downloads. It was
    // reachable only by clicking the client's name, which does not read as a link.
    render(<AuditWorkspace />);
    const open = screen.getByLabelText("Open the Verde Cafe audit");
    expect(open).toHaveAttribute("href", "/admin/audits/aud-1");
  });

  it("gives every row its own way in", () => {
    render(<AuditWorkspace />);
    expect(
      screen.getAllByTitle("Open this audit - overview, issues, pages, downloads"),
    ).toHaveLength(rows.length);
  });

  it("offers a control that opens the report viewer", () => {
    render(<AuditWorkspace />);
    expect(openers()).toHaveLength(rows.length);
  });

  it("opens the viewer for the audit whose row was clicked", async () => {
    render(<AuditWorkspace />);
    expect(screen.queryByTestId("viewer")).toBeNull();
    await userEvent.click(openers()[1]);
    // The SECOND row, not the first: a viewer keyed to the wrong row is the same
    // bug wearing a different hat.
    expect(screen.getByTestId("viewer")).toHaveTextContent("NorthPeak");
  });

  it("stays enabled when the PDF never rendered", () => {
    render(<AuditWorkspace />);
    // report.html is a sibling resolved by convention, so it outlives the PDF.
    expect(openers()[1].disabled).toBe(false);
  });

  it("is disabled while the audit is still running", () => {
    render(<AuditWorkspace />);
    expect(openers()[2].disabled).toBe(true);
  });
});
