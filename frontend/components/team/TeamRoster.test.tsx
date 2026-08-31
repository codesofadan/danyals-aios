// Removing a team member.
//
// QA: "Team members can be created, but there is no option to delete a team member."
// The server side already existed in full — suspend/reactivate, the owner-only
// interlock, the last-super-admin refusal, session revocation — with zero callers.
// Two things were genuinely missing: the UI, and the `suspended` status label, which
// migration 0078 added to the enum and `lib/data.ts` never learned. So the roster
// could not have RENDERED a removed member even if one had existed.

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui/Toast";
import { STATUS_META, type TeamMemberRecord } from "@/lib/data";

import TeamRoster from "./TeamRoster";

const suspendMutate = vi.fn();
const reactivateMutate = vi.fn();

vi.mock("@/lib/hooks/team", () => ({
  useSuspendMember: () => ({ mutate: suspendMutate, isPending: false, error: null }),
  useReactivateMember: () => ({ mutate: reactivateMutate, isPending: false, error: null }),
  useRevealCredentials: () => ({ mutate: vi.fn(), isPending: false, error: null }),
  useSetPassword: () => ({ mutate: vi.fn(), isPending: false, error: null }),
}));

function member(over: Partial<TeamMemberRecord> = {}): TeamMemberRecord {
  return {
    id: "u1", name: "Priya Raman", init: "PR", c: "#C6FF3C", title: "SEO Lead",
    email: "priya@example.com", role: "Manager", status: "active",
    activeTasks: 3, completed: 12, onTime: 90, utilization: 62, quality: 88, joined: "2025",
    ...over,
  } as unknown as TeamMemberRecord;
}

beforeEach(() => {
  suspendMutate.mockClear();
  reactivateMutate.mockClear();
});

describe("removing a team member", () => {
  it("offers Remove on an active member", () => {
    render(<ToastProvider><TeamRoster members={[member()]} onAdd={vi.fn()} /></ToastProvider>);
    expect(screen.getByTitle(/Remove Priya Raman from the team/i)).toBeInTheDocument();
  });

  it("does not remove anyone on the first click", async () => {
    render(<ToastProvider><TeamRoster members={[member()]} onAdd={vi.fn()} /></ToastProvider>);
    await userEvent.click(screen.getByTitle(/Remove Priya Raman from the team/i));
    // The click opens the confirmation; nothing has been sent yet.
    expect(suspendMutate).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("says the work history survives, because removal is not deletion", async () => {
    render(<ToastProvider><TeamRoster members={[member()]} onAdd={vi.fn()} /></ToastProvider>);
    await userEvent.click(screen.getByTitle(/Remove Priya Raman from the team/i));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/stay in the ledger/i)).toBeInTheDocument();
  });

  it("sends the suspension once confirmed", async () => {
    render(<ToastProvider><TeamRoster members={[member()]} onAdd={vi.fn()} /></ToastProvider>);
    await userEvent.click(screen.getByTitle(/Remove Priya Raman from the team/i));
    await userEvent.click(screen.getByRole("button", { name: /Remove member/i }));
    expect(suspendMutate).toHaveBeenCalledWith(
      expect.objectContaining({ userId: "u1" }),
      expect.anything(),
    );
  });

  it("offers Restore instead of Remove for an already-removed member", () => {
    render(
      <ToastProvider>
        <TeamRoster members={[member({ status: "suspended" })]} onAdd={vi.fn()} />
      </ToastProvider>,
    );
    expect(screen.getByTitle(/Restore Priya Raman's access/i)).toBeInTheDocument();
    expect(screen.queryByTitle(/Remove Priya Raman from the team/i)).not.toBeInTheDocument();
  });

  it("can render a removed member at all", () => {
    // The latent defect: STATUS_META had no `suspended` entry, so StatusDot read
    // `undefined.c`. This is the regression guard for the missing enum label.
    expect(STATUS_META.suspended).toBeDefined();
    render(
      <ToastProvider>
        <TeamRoster members={[member({ status: "suspended" })]} onAdd={vi.fn()} />
      </ToastProvider>,
    );
    expect(screen.getByText("Removed")).toBeInTheDocument();
  });
});
