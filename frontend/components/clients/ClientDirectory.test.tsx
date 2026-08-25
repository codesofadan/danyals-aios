// Report access — the control that decides what a client sees when they sign in.
//
// It existed and was wired to nothing. `ClientAccessEditor` was imported by no file,
// `useReportGrants`/`useSaveGrants` had zero call sites, and `AddClientWizard`
// hard-coded `reports: []` behind a `length > 0` guard that could never be true. So
// PUT /clients/{id}/report-grants was never called by anything, every client was
// created with an empty grant set, and no screen could add one.
//
// The visible result was a client dashboard of thirteen padlocks, permanently, for
// every client — each one reading "Not included in your plan". Nothing was broken in
// a way that threw; the feature simply had no entry point.

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ClientDirectory from "./ClientDirectory";
import type { ClientRecord } from "@/lib/data";

const CLIENT = {
  id: "c1", cn: "Bellevue Dental", industry: "Dental", sites: 1, since: "2024",
  contact: { name: "Rae Lindqvist", role: "Owner", email: "rae@example.com", init: "RL", c: "#C6FF3C" },
  tier: "Growth", status: "active", renews: "Mar 2027", mrr: 2400,
} as unknown as ClientRecord;

const saveMutate = vi.fn();
let grants: Record<string, string[]> = { c1: [] };
let grantsLoading = false;

vi.mock("@/lib/hooks/clients", () => ({
  useClients: () => ({ data: [CLIENT], isLoading: false, isError: false }),
  useCreateClient: () => ({ mutate: vi.fn(), isPending: false, error: null }),
  useUpdateClient: () => ({ mutate: vi.fn(), isPending: false, error: null }),
  useDeleteClient: () => ({ mutate: vi.fn(), isPending: false, error: null }),
  useAllReportGrants: () => ({ grants, isLoading: grantsLoading, isError: false }),
  useSaveGrants: () => ({ mutate: saveMutate, isPending: false, error: null }),
}));

beforeEach(() => {
  saveMutate.mockClear();
  grants = { c1: [] };
  grantsLoading = false;
});

describe("client report access", () => {
  it("shows how many reports each client can actually see", () => {
    grants = { c1: ["audit_scores", "milestones"] };
    render(<ClientDirectory />);
    const action = screen.getByTitle(/Choose which reports/i);
    expect(within(action).getByText("2")).toBeInTheDocument();
  });

  it("surfaces a client that can see nothing", () => {
    render(<ClientDirectory />);
    const action = screen.getByTitle(/Choose which reports/i);
    // The state every client was silently in: a dashboard of padlocks.
    expect(within(action).getByText("0")).toBeInTheDocument();
  });

  it("opens the editor and writes the chosen grants back", async () => {
    const user = userEvent.setup();
    render(<ClientDirectory />);

    await user.click(screen.getByTitle(/Choose which reports/i));
    expect(screen.getByText(/Report access · Bellevue Dental/)).toBeInTheDocument();

    // Grant one report, then save.
    await user.click(screen.getByTitle(/^Audit Scores/));
    await user.click(screen.getByRole("button", { name: /Save access/i }));

    expect(saveMutate).toHaveBeenCalledTimes(1);
    const [payload] = saveMutate.mock.calls[0];
    expect(payload.clientId).toBe("c1");
    expect(payload.reports).toContain("audit_scores");
  });

  it("will not open the editor before the current grants are known", () => {
    // Opening early would present an empty set as the client's CURRENT access, and
    // saving would silently revoke everything they had.
    grantsLoading = true;
    render(<ClientDirectory />);
    expect(screen.getByTitle(/Choose which reports/i)).toBeDisabled();
  });
});
