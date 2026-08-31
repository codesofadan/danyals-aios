// The Policy Radar recommendation queue.
//
// APPLY WAS WITHDRAWN. It persisted — a status flip plus an `audit_overlay` row —
// but `list_active_overlay` has one caller (`GET /policy/overlay`) and NOTHING calls
// that: no audit worker, no report renderer, no frontend hook. The overlay was
// written and read by nobody, so "Applied" badged an effect that never happened and
// the confirm dialog promised a change to "those clients' reports" that could not
// occur. QA asked for the honest option: remove the state, don't display a lie.
//
// Acknowledge and Dismiss stay — both mean exactly what they say.

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Recommendations from "./Recommendations";

const mutate = vi.fn();
let rows: Array<Record<string, unknown>> = [];

vi.mock("@/lib/hooks/policy", async () => {
  const actual = await vi.importActual<typeof import("@/lib/hooks/policy")>("@/lib/hooks/policy");
  return {
    ...actual,
    useRecommendations: () => ({ data: rows, isLoading: false, isError: false, error: null }),
    useTransitionRecommendation: () => ({ mutate, isPending: false }),
  };
});

function rec(over: Record<string, unknown> = {}) {
  return {
    id: "r1", title: "Tighten thin service pages", status: "new",
    why: "The core update devalues thin pages.", action: "Expand or consolidate.",
    target: "content", scope: "All clients", region: "global", regionLabel: "Global",
    clients: "", ...over,
  };
}

beforeEach(() => {
  mutate.mockClear();
  rows = [rec()];
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

describe("recommendation actions", () => {
  it("can acknowledge a new recommendation", async () => {
    const user = userEvent.setup();
    render(<Recommendations />);
    await user.click(screen.getByRole("button", { name: /Acknowledge/i }));
    expect(mutate).toHaveBeenCalledWith({ id: "r1", action: "acknowledge" });
  });

  it("can dismiss one", async () => {
    const user = userEvent.setup();
    render(<Recommendations />);
    await user.click(screen.getByRole("button", { name: /Dismiss/i }));
    expect(mutate).toHaveBeenCalledWith({ id: "r1", action: "dismiss" });
  });

  it("offers no Apply control at all", () => {
    render(<Recommendations />);
    // The regression guard: an operator must not be able to reach a state that
    // claims a downstream effect nothing produces.
    expect(screen.queryByRole("button", { name: /Apply/i })).not.toBeInTheDocument();
  });

  it("never sends an apply transition", async () => {
    const user = userEvent.setup();
    render(<Recommendations />);
    await user.click(screen.getByRole("button", { name: /Dismiss/i }));
    expect(mutate).not.toHaveBeenCalledWith(expect.objectContaining({ action: "apply" }));
  });

  it("stops offering Acknowledge once it has been acknowledged", () => {
    rows = [rec({ status: "acknowledged" })];
    render(<Recommendations />);
    expect(screen.queryByRole("button", { name: /Acknowledge/i })).not.toBeInTheDocument();
    // Dismiss is still reachable — acknowledged is not a terminal state.
    expect(screen.getByRole("button", { name: /Dismiss/i })).toBeInTheDocument();
  });

  it("still renders a recommendation applied before Apply was withdrawn", () => {
    // The server can still return `applied`, so STATUS_META must keep the entry.
    rows = [rec({ status: "applied" })];
    render(<Recommendations />);
    expect(screen.getByText("Applied")).toBeInTheDocument();
  });

  it.each(["applied", "dismissed"])("offers nothing on a %s recommendation", (status) => {
    // Terminal. Re-offering Apply would invite a second overlay row for one decision.
    rows = [rec({ status })];
    const { container } = render(<Recommendations />);
    const card = container.querySelector(".pr-rec") as HTMLElement;
    expect(within(card).queryByRole("button", { name: /Apply|Dismiss|Acknowledge/i })).toBeNull();
    expect(within(card).getByText(/no further action needed/i)).toBeInTheDocument();
  });
});
