// Depth is the only scope control.
//
// The Run New Audit form used to carry an audit-TYPE picker beside depth, and it
// could not do what its labels said. The engine has no per-dimension flag: the
// deterministic crawl always runs in full, so a run scoped to "on-page +
// technical" came back with GEO and strategy findings too. All the picker ever
// changed was which paid providers fired, under labels that promised something
// else entirely.
//
// Worse, TIER was derived from it as `types.some(isPaid)` - false for an EMPTY
// selection, which meant the full comprehensive run. So the most expensive audit
// the platform can launch was submitted as "Free" and skipped both server-side
// cost gates. Deriving tier from depth makes that unrepresentable rather than
// merely refused: the value that names the run is the value that prices it.

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createMutate = vi.fn();

const row = (over: Record<string, unknown> = {}) => ({
  id: "aud-1",
  client: "Verde Cafe",
  url: "verdecafe.co",
  types: [],
  tier: "Paid",
  status: "done",
  depth: "standard",
  maxPages: 60,
  estimatedCost: 0.4,
  cost: 0.4,
  score: 74,
  runtime: "4m 48s",
  when: "Today",
  pdf: true,
  json: true,
  visibleToClient: false,
  ...over,
});

const rows = [row(), row({ id: "aud-2", client: "NorthPeak", depth: "deep" })];

vi.mock("@/lib/hooks/audits", () => ({
  AUDITS_PAGE: 200,
  useAudits: () => ({ data: rows, isLoading: false, isError: false, isFetching: false, error: null }),
  useAuditStats: () => ({ data: undefined, isLoading: false, isError: false }),
  useCreateAudit: () => ({ mutate: createMutate, isPending: false }),
  useAuditEstimate: () => ({ mutate: vi.fn(), isPending: false }),
  useSetAuditVisibility: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/lib/hooks/clients", () => ({
  useClients: () => ({ data: [{ id: "c-1", name: "Verde Cafe" }], isLoading: false }),
}));
vi.mock("@/lib/hooks/cost", () => ({ useSpendHalted: () => ({ halted: false }) }));
vi.mock("@/lib/api", () => ({ downloadFile: vi.fn(), getReportHtml: vi.fn() }));
vi.mock("@/components/report/ReportViewer", () => ({ default: () => null }));

import AuditWorkspace from "./AuditWorkspace";

async function submit(depthLabel: RegExp) {
  // Fresh DOM per submission: two renders in one test give every query two hits.
  cleanup();
  render(<AuditWorkspace />);
  await userEvent.type(screen.getByPlaceholderText(/northpeakdental/i), "example.com");
  await userEvent.click(screen.getByRole("button", { name: depthLabel }));
  await userEvent.click(screen.getByRole("button", { name: /Run .* audit/i }));
  return createMutate.mock.calls.at(-1)?.[0];
}

describe("depth is the only scope control", () => {
  beforeEach(() => createMutate.mockClear());

  it("offers no audit-type picker at all", () => {
    render(<AuditWorkspace />);
    expect(screen.queryByText("Audit types")).toBeNull();
    expect(screen.queryByRole("button", { name: "Select all" })).toBeNull();
  });

  it("sends no type selection with a new audit", async () => {
    const payload = await submit(/^Standard$/);
    expect(payload).toBeDefined();
    expect(payload).not.toHaveProperty("types");
  });

  it("prices Basic as Free and Standard as Paid", async () => {
    expect((await submit(/^Basic$/)).tier).toBe("Free");
    createMutate.mockClear();
    expect((await submit(/^Standard$/)).tier).toBe("Paid");
  });

  it("sends the depth that was clicked", async () => {
    expect((await submit(/^Basic$/)).depth).toBe("free");
    createMutate.mockClear();
    expect((await submit(/^Standard$/)).depth).toBe("standard");
  });

  it("leaves every depth selectable", () => {
    render(<AuditWorkspace />);
    // "Advanced" carries a "!" confirm marker, so its accessible name is not a
    // bare string match.
    for (const label of [/^Basic$/, /^Standard$/, /^Advanced/]) {
      expect(screen.getByRole("button", { name: label })).not.toBeDisabled();
    }
  });

  it("filters the queue by depth rather than by type", async () => {
    render(<AuditWorkspace />);
    expect(screen.queryByRole("button", { name: "All types" })).toBeNull();
    const select = screen.getByLabelText("Filter audits by depth");
    expect(screen.getByText("NorthPeak")).toBeInTheDocument();
    await userEvent.selectOptions(select, "standard");
    // The Advanced run drops out; the Standard one stays.
    expect(screen.queryByText("NorthPeak")).toBeNull();
    expect(screen.getByText("Verde Cafe")).toBeInTheDocument();
  });
});
