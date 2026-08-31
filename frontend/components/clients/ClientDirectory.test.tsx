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
import { ToastProvider } from "@/components/ui/Toast";

import ClientDirectory from "./ClientDirectory";
import type { ClientRecord } from "@/lib/data";

const CLIENT = {
  id: "c1", cn: "Bellevue Dental", industry: "Dental", sites: 1, since: "2024",
  contact: { name: "Rae Lindqvist", role: "Owner", email: "rae@example.com", init: "RL", c: "#C6FF3C" },
  tier: "Growth", status: "active", renews: "Mar 2027", mrr: 2400,
} as unknown as ClientRecord;

const saveMutate = vi.fn();
const revealMutate = vi.fn();
let grants: Record<string, string[]> = { c1: [] };
let grantsLoading = false;

vi.mock("@/lib/hooks/clients", () => ({
  useClients: () => ({ data: [CLIENT], isLoading: false, isError: false }),
  useCreateClient: () => ({ mutate: vi.fn(), isPending: false, error: null }),
  useUpdateClient: () => ({ mutate: vi.fn(), isPending: false, error: null }),
  useDeleteClient: () => ({ mutate: vi.fn(), isPending: false, error: null }),
  useAllReportGrants: () => ({ grants, isLoading: grantsLoading, isError: false }),
  useSaveGrants: () => ({ mutate: saveMutate, isPending: false, error: null }),
  // The "Show login" cell's hooks. Nothing here fires until the operator clicks,
  // so an inert mutate is enough for the directory's own tests.
  useRevealPortalCredentials: () => ({ mutate: revealMutate, isPending: false, error: null }),
  useSetPortalPassword: () => ({ mutate: vi.fn(), isPending: false, error: null }),
  useProvisionPortalLogin: () => ({ mutate: vi.fn(), isPending: false, error: null }),
}));

beforeEach(() => {
  saveMutate.mockClear();
  revealMutate.mockClear();
  grants = { c1: [] };
  grantsLoading = false;
});

describe("client report access", () => {
  it("shows how many reports each client can actually see", () => {
    grants = { c1: ["audit_scores", "milestones"] };
    render(<ToastProvider><ClientDirectory /></ToastProvider>);
    const action = screen.getByTitle(/Choose which reports/i);
    expect(within(action).getByText("2")).toBeInTheDocument();
  });

  it("surfaces a client that can see nothing", () => {
    render(<ToastProvider><ClientDirectory /></ToastProvider>);
    const action = screen.getByTitle(/Choose which reports/i);
    // The state every client was silently in: a dashboard of padlocks.
    expect(within(action).getByText("0")).toBeInTheDocument();
  });

  it("opens the editor and writes the chosen grants back", async () => {
    const user = userEvent.setup();
    render(<ToastProvider><ClientDirectory /></ToastProvider>);

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
    render(<ToastProvider><ClientDirectory /></ToastProvider>);
    expect(screen.getByTitle(/Choose which reports/i)).toBeDisabled();
  });
});

// --- Portal logins ---------------------------------------------------------
// QA: clients could not sign in, and there was no way for an admin to look up
// an existing client's credentials. Both defects were invisible from this screen:
// a failed provision produced a dismissible warning naming a repair screen that
// does not exist, and the password was believed unrecoverable when it was not.

describe("client portal logins", () => {
  it("offers Show login on every client row", () => {
    render(<ToastProvider><ClientDirectory /></ToastProvider>);
    expect(screen.getByTitle(/Show Bellevue Dental's portal login/i)).toBeInTheDocument();
  });

  it("does not reveal anything until the operator asks", () => {
    render(<ToastProvider><ClientDirectory /></ToastProvider>);
    // The reveal is a click-per-row, never a page-load fetch: the directory must
    // not hold a table of plaintext passwords nobody asked for.
    expect(revealMutate).not.toHaveBeenCalled();
  });

  it("fetches the credentials only once Show login is clicked", async () => {
    render(<ToastProvider><ClientDirectory /></ToastProvider>);
    await userEvent.click(screen.getByTitle(/Show Bellevue Dental's portal login/i));
    expect(revealMutate).toHaveBeenCalledWith("c1", expect.anything());
  });
});
