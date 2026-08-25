// The milestones KPI row.
//
// Its four VALUES were always derived from the live `/milestones` payload. The
// movement printed beside them was not: `delta: "1"`, `"6"`, `"5%"` and one computed
// from the current at-risk count, every literal one of them pointing UP, under a note
// reading "this month, auto-advanced".
//
// Two separate untruths in one line. Nothing was measured over "this month" — the
// endpoint returns current state with no history at all — and nothing auto-advances:
// `advance_stage` has exactly one caller, at onboarding, so stages 3-5 never move.
//
// A delta is the first thing an operator reads on a KPI tile, and it is the part that
// says "things are going well". These assertions exist so it cannot come back without
// a real series behind it.

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import MilestoneStats from "./MilestoneStats";
import type { ClientProject } from "@/lib/milestones";

const PROJECTS = [
  {
    id: "p1", client: "Bellevue Dental", health: "on_track",
    stages: [
      { key: "onboarding", status: "completed" },
      { key: "baseline", status: "completed" },
      { key: "content", status: "in_progress" },
      { key: "offpage", status: "upcoming" },
      { key: "reporting", status: "upcoming" },
    ],
  },
  {
    id: "p2", client: "Northgate Law", health: "at_risk",
    stages: [
      { key: "onboarding", status: "completed" },
      { key: "baseline", status: "upcoming" },
      { key: "content", status: "upcoming" },
      { key: "offpage", status: "upcoming" },
      { key: "reporting", status: "upcoming" },
    ],
  },
] as unknown as ClientProject[];

vi.mock("@/lib/hooks/milestones", () => ({ useMilestones: () => ({ data: PROJECTS }) }));
// anime() returns the animation instance the count-up effect pauses on cleanup.
vi.mock("animejs", () => ({
  default: Object.assign(() => ({ pause: () => {}, restart: () => {} }), { remove: () => {} }),
}));

describe("MilestoneStats", () => {
  it("derives every figure from the live projects", () => {
    render(<MilestoneStats />);
    expect(screen.getByText("Active projects")).toBeInTheDocument();
    expect(screen.getByText("of 2 tracked")).toBeInTheDocument();
    // 3 completed stages across the two projects; 1 at-risk.
    expect(screen.getByText("Stages completed")).toBeInTheDocument();
    expect(screen.getByText("1 at-risk needs attention")).toBeInTheDocument();
  });

  it("prints no movement it cannot measure", () => {
    const { container } = render(<MilestoneStats />);
    expect(
      container.querySelectorAll(".delta").length,
      "a delta reappeared - /milestones returns no history, so any trend beside these " +
        "values is invented",
    ).toBe(0);
    for (const gone of ["trending_up", "trending_down"]) {
      expect(container.textContent).not.toContain(gone);
    }
  });

  it("does not claim milestones advanced this month", () => {
    render(<MilestoneStats />);
    expect(document.body.textContent).not.toMatch(/this month/i);
    expect(document.body.textContent).not.toMatch(/auto-advanced/i);
  });
});
