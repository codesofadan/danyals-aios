// Client-portal exposure, in the audit queue.
//
// Sharing an audit with a client was write-once: chosen at creation, absent from
// every API response, and impossible to change afterwards. An operator could put
// a run in front of a client and then had no way to see that they had. Migration
// 0096 additionally backfilled `true` for every audit that already had a client,
// so what is exposed today is historical rather than chosen.
//
// Two properties are pinned here, both about telling an operator the truth:
//
//   1. Exposure is VISIBLE on every row. Exposure a reviewer cannot see is
//      exposure nobody reviews.
//   2. Exposure is REVERSIBLE, and the control reports the state it is in rather
//      than the action it would take.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mutate = vi.fn();

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

const rows = [row(), row({ id: "aud-2", client: "NorthPeak", visibleToClient: true })];

vi.mock("@/lib/hooks/audits", () => ({
  useAudits: () => ({ data: rows, isLoading: false, isError: false, error: null }),
  useAuditStats: () => ({ data: undefined, isLoading: false, isError: false }),
  useCreateAudit: () => ({ mutate: vi.fn(), isPending: false }),
  useAuditEstimate: () => ({ mutate: vi.fn(), isPending: false }),
  useSetAuditVisibility: () => ({ mutate, isPending: false }),
}));
vi.mock("@/lib/hooks/clients", () => ({
  useClients: () => ({ data: [{ id: "c-1", name: "Verde Cafe" }], isLoading: false }),
}));
vi.mock("@/lib/hooks/cost", () => ({ useSpendHalted: () => ({ halted: false }) }));

import AuditWorkspace from "./AuditWorkspace";

describe("client-portal exposure in the audit queue", () => {
  beforeEach(() => mutate.mockClear());

  it("shows the exposure state of every audit", () => {
    render(<AuditWorkspace />);
    // One internal, one shared — an operator can see which is which at a glance.
    expect(screen.getByText("Internal")).toBeInTheDocument();
    expect(screen.getByText("Shared")).toBeInTheDocument();
  });

  it("reports state rather than the action it would take", () => {
    render(<AuditWorkspace />);
    // The label says what IS true. A button reading "Share" on an already-shared
    // row would be read as its state by anyone scanning the column.
    const shared = screen.getByText("Shared").closest("button")!;
    expect(shared).toHaveAttribute("aria-pressed", "true");
    const internal = screen.getByText("Internal").closest("button")!;
    expect(internal).toHaveAttribute("aria-pressed", "false");
  });

  it("lets an operator revoke a shared audit", async () => {
    render(<AuditWorkspace />);
    await userEvent.click(screen.getByText("Shared").closest("button")!);
    expect(mutate).toHaveBeenCalledWith({ id: "aud-2", visible: false });
  });

  it("lets an operator share an internal audit", async () => {
    render(<AuditWorkspace />);
    await userEvent.click(screen.getByText("Internal").closest("button")!);
    expect(mutate).toHaveBeenCalledWith({ id: "aud-1", visible: true });
  });

  it("explains what sharing means in the control's own title", () => {
    render(<AuditWorkspace />);
    expect(screen.getByText("Shared").closest("button")).toHaveAttribute(
      "title",
      expect.stringContaining("can read this audit in their portal"),
    );
  });
});
