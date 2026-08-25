// The Policy Radar recommendation queue.
//
// It rendered four status pills — New / Acknowledged / Applied / Dismissed — under a
// subtitle reading "Closed-loop recommendations", and offered no control that could
// reach any of them. `useTransitionRecommendation` had zero call sites and
// `POST /policy/recommendations/{id}/{action}` had no caller, so every recommendation
// the radar produced stayed "New" forever however many times an operator read it.
//
// `apply` is the consequential action: server-side it also writes an `audit_overlay`
// row, which changes what affected clients' reports say. So it confirms first, and
// settled rows offer nothing at all.

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

  it("confirms before applying, because apply writes an audit overlay", async () => {
    const user = userEvent.setup();
    render(<Recommendations />);
    await user.click(screen.getByRole("button", { name: /Apply/i }));
    expect(window.confirm).toHaveBeenCalled();
    expect(mutate).toHaveBeenCalledWith({ id: "r1", action: "apply" });
  });

  it("does not apply when the confirmation is declined", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    render(<Recommendations />);
    await user.click(screen.getByRole("button", { name: /Apply/i }));
    expect(mutate).not.toHaveBeenCalled();
  });

  it("stops offering Acknowledge once it has been acknowledged", async () => {
    rows = [rec({ status: "acknowledged" })];
    render(<Recommendations />);
    expect(screen.queryByRole("button", { name: /Acknowledge/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Apply/i })).toBeInTheDocument();
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
