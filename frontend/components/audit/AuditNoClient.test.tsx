// An audit does not need a client.
//
// The Run New Audit form used to require one: `canRun` tested `!!effectiveClientId`
// and the client <select> disabled itself when the list came back empty. The
// combined effect was that a workspace with no clients on the books could not
// audit ANYTHING - including the prospect site it was trying to win, which is
// exactly when an agency most wants a report.
//
// Nothing below the form ever required it. `audits.client_id` is nullable,
// `GateContext.client_id` is `str | None` (an untenanted run skips the per-client
// budget cap and still answers to the agency-global spend halt), and the public
// free-audit funnel has run this shape since P6C.
//
// Two properties are pinned here:
//
//   1. A run with no client is POSSIBLE - with an empty client list, and by
//      explicit choice when clients do exist.
//   2. A run with no client is PRIVATE, and does not claim otherwise. The portal
//      view selects `client_id = current_client_id()`, which NULL never matches,
//      so the row is unreachable to every client by construction. The sharing
//      controls say so rather than offering a toggle that silently does nothing.

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const createMutate = vi.fn();
const visibilityMutate = vi.fn();

// Swapped per test: the empty list is the case the old gate made unusable.
let clientList: { id: string; name: string }[] = [];
let clientsLoading = false;

const row = (over: Record<string, unknown> = {}) => ({
  id: "aud-1",
  client: "Verde Cafe",
  url: "verdecafe.co",
  types: [],
  tier: "Free",
  status: "done",
  depth: "free",
  maxPages: 15,
  estimatedCost: 0,
  cost: 0,
  score: 74,
  runtime: "4m 48s",
  when: "Today",
  pdf: true,
  json: true,
  visibleToClient: false,
  hasClient: true,
  ...over,
});

// One tenanted row and one internal run, so the table shows both controls.
const rows = [
  row(),
  row({ id: "aud-solo", client: "", hasClient: false }),
];

vi.mock("@/lib/hooks/audits", () => ({
  AUDITS_PAGE: 200,
  useAudits: () => ({ data: rows, isLoading: false, isError: false, isFetching: false, error: null }),
  useAuditStats: () => ({ data: undefined, isLoading: false, isError: false }),
  useCreateAudit: () => ({ mutate: createMutate, isPending: false }),
  useAuditEstimate: () => ({ mutate: vi.fn(), isPending: false }),
  useSetAuditVisibility: () => ({ mutate: visibilityMutate, isPending: false }),
}));
vi.mock("@/lib/hooks/clients", () => ({
  useClients: () => ({ data: clientList, isLoading: clientsLoading }),
}));
vi.mock("@/lib/hooks/cost", () => ({ useSpendHalted: () => ({ halted: false }) }));
vi.mock("@/lib/api", () => ({ downloadFile: vi.fn(), getReportHtml: vi.fn() }));
vi.mock("@/components/report/ReportViewer", () => ({ default: () => null }));

import AuditWorkspace from "./AuditWorkspace";

const runButton = () => screen.getByRole("button", { name: /Run .* audit/i });
const shareCheckbox = () =>
  screen.getByRole("checkbox", { name: /Show this audit in the client/i });

// `fireEvent.change` rather than `userEvent.type`: these tests assert on what is
// SUBMITTED, not on typing behaviour, and 18 real keystrokes per test was enough
// to push the file past the 5s timeout when the suite runs in parallel.
function fillUrl(url = "alligatorpools.com") {
  fireEvent.change(screen.getByPlaceholderText(/northpeakdental/i), {
    target: { value: url },
  });
}

describe("an audit can run with no client", () => {
  beforeEach(() => {
    createMutate.mockClear();
    visibilityMutate.mockClear();
    clientList = [];
    clientsLoading = false;
  });
  afterEach(cleanup);

  it("will not submit while the client list is still loading", () => {
    // Mid-load the form reads as client-less, because `clients[0]` is not there
    // yet. Submitting in that window would produce an INTERNAL audit where the
    // operator would have got their first client a moment later - a silent
    // mis-attribution, not a refusal. Running untenanted must be a CHOICE.
    clientsLoading = true;
    render(<AuditWorkspace />);
    fillUrl();
    expect(runButton()).toBeDisabled();
  });

  it("enables the run button with an empty client list", async () => {
    render(<AuditWorkspace />);
    // The gate before this change: no clients -> no id -> button dead, with
    // nothing on screen explaining which of the four conditions had failed.
    expect(runButton()).toBeDisabled();
    fillUrl();
    expect(runButton()).toBeEnabled();
  });

  it("sends a null client_id when there is no client", async () => {
    render(<AuditWorkspace />);
    fillUrl();
    await userEvent.click(runButton());
    const payload = createMutate.mock.calls.at(-1)?.[0];
    expect(payload).toBeDefined();
    // null, not "" and not omitted: the server distinguishes "no client" from a
    // client that does not resolve, and only the first is allowed through.
    expect(payload.client_id).toBeNull();
    expect(payload.url).toBe("alligatorpools.com");
  });

  it("still offers the no-client option when clients DO exist", async () => {
    clientList = [{ id: "c-1", name: "Verde Cafe" }];
    render(<AuditWorkspace />);
    const select = screen.getByLabelText("Client");
    // Defaults to the first real client, so the common case is unchanged...
    expect(select).toHaveValue("c-1");
    // ...but running untenanted stays one choice away.
    await userEvent.selectOptions(select, "__no_client__");
    fillUrl();
    await userEvent.click(runButton());
    expect(createMutate.mock.calls.at(-1)?.[0].client_id).toBeNull();
  });

  it("does not fall back to the first client after no-client is chosen", async () => {
    // The bug this guards: `clientId || clients[0]?.id` collapses "" and "chosen
    // none" into the same value, so selecting no-client would silently re-pick
    // Verde Cafe on the very next render and bill the audit to them.
    clientList = [{ id: "c-1", name: "Verde Cafe" }];
    render(<AuditWorkspace />);
    await userEvent.selectOptions(screen.getByLabelText("Client"), "__no_client__");
    fillUrl();
    expect(screen.getByLabelText("Client")).toHaveValue("__no_client__");
    await userEvent.click(runButton());
    expect(createMutate.mock.calls.at(-1)?.[0].client_id).toBeNull();
  });
});

describe("an audit with no client cannot claim to be shared", () => {
  beforeEach(() => {
    createMutate.mockClear();
    visibilityMutate.mockClear();
    clientList = [];
    clientsLoading = false;
  });
  afterEach(cleanup);

  it("disables the share-at-creation checkbox with no client", () => {
    render(<AuditWorkspace />);
    expect(shareCheckbox()).toBeDisabled();
    expect(shareCheckbox()).not.toBeChecked();
  });

  it("never sends visible_to_client true for a client-less run", async () => {
    render(<AuditWorkspace />);
    fillUrl();
    await userEvent.click(runButton());
    expect(createMutate.mock.calls.at(-1)?.[0].visible_to_client).toBe(false);
  });

  it("re-enables the checkbox once a client is chosen", async () => {
    clientList = [{ id: "c-1", name: "Verde Cafe" }];
    render(<AuditWorkspace />);
    expect(shareCheckbox()).toBeEnabled();
    await userEvent.selectOptions(screen.getByLabelText("Client"), "__no_client__");
    expect(shareCheckbox()).toBeDisabled();
  });

  it("makes the row's share control inert for an internal audit", () => {
    render(<AuditWorkspace />);
    const inert = screen.getByTitle(/no client, so there is no portal/i);
    expect(inert).toBeDisabled();
    // Inert AND silent: a disabled control that still fired would be worse than
    // an enabled one, because nothing on screen would report the write.
    expect(visibilityMutate).not.toHaveBeenCalled();
  });

  it("names a client-less row instead of rendering a blank link", () => {
    render(<AuditWorkspace />);
    // `client_name` is "" for these, and the client cell is the row's ONLY link
    // into the audit - an empty string would leave the row unreachable.
    expect(screen.getByRole("link", { name: "Internal audit" })).toBeInTheDocument();
  });
});
