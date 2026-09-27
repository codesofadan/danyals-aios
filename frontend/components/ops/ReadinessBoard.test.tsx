// The readiness panel, where an operator reads it: on the screen they are about to spend
// money from.
//
// Three properties are pinned, each of which is the difference between a panel people read
// and one they learn to scroll past:
//
//   1. QUIET WHEN READY. A healthy deploy gets one line, collapsed. A panel that shouts on
//      a green deploy is ignored on the day it matters.
//   2. A BLOCK AND A DEGRADE READ DIFFERENTLY, and both carry their fix. "Nothing will
//      draft" must not render in the same words as "images will be skipped".
//   3. IT NEVER TAKES THE HOST SCREEN DOWN. The readiness read failing is not a reason to
//      put an error banner on the audit queue.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const board = {
  spendHalted: false,
  ready: 1,
  partial: 1,
  blocked: 1,
  capabilities: [
    {
      id: "audit_free",
      name: "Free audit",
      group: "Audit",
      verdict: "ready",
      summary: "Ready - and it spends nothing",
      measures: ["A condensed crawl", "Core Web Vitals"],
      gaps: [],
    },
    {
      id: "audit_deep",
      name: "Deep audit",
      group: "Audit",
      verdict: "partial",
      summary: "It will run, with 1 gap",
      measures: ["The crawl", "No local checks"],
      gaps: [
        {
          what: "the local checks will be skipped",
          why: "the engine has no Places key",
          fix: "add GOOGLE_PLACES_API_KEY to the audit engine's .env",
          severity: "degrades",
        },
      ],
    },
    {
      id: "content_draft",
      name: "Content pipeline",
      group: "Content",
      verdict: "blocked",
      summary: "Nothing will draft",
      measures: ["A researched brief"],
      gaps: [
        {
          what: "nothing will draft - every page holds at drafting, honestly, at $0",
          why: "there is no Anthropic key",
          fix: "set ANTHROPIC_API_KEY",
          severity: "blocks",
        },
      ],
    },
  ],
};

const state = { data: board as unknown, isError: false };
vi.mock("@/lib/hooks/readiness", () => ({ useReadiness: () => state }));

import ReadinessBoard from "./ReadinessBoard";

describe("the readiness panel", () => {
  it("says one quiet line when everything in the group is ready", () => {
    // Only the free audit is ready, so a group of just that one is the all-ready case.
    const only = { ...board, capabilities: [board.capabilities[0]] };
    state.data = only;
    render(<ReadinessBoard group="Audit" />);
    expect(screen.getByText("Everything here is ready to run")).toBeTruthy();
    // Collapsed: the capability name is not on screen until asked for.
    expect(screen.queryByText("Free audit")).toBeNull();
    state.data = board;
  });

  it("counts what will not run, in the header, before anything is expanded", () => {
    render(<ReadinessBoard group="Content" />);
    expect(screen.getByText("1 thing will not run on this setup")).toBeTruthy();
  });

  it("separates a block from a degrade, and shows the fix for each", async () => {
    render(<ReadinessBoard group="Audit" title="Before you run an audit" />);
    await userEvent.click(screen.getByText("Before you run an audit"));
    // The degrade is expanded on demand; the wording is not the block's.
    await userEvent.click(screen.getByText("Deep audit"));
    expect(screen.getByText(/Will be thinner:/)).toBeTruthy();
    expect(screen.getByText(/GOOGLE_PLACES_API_KEY/)).toBeTruthy();
    expect(screen.queryByText(/Will not run:/)).toBeNull();
  });

  it("opens a blocked capability without being asked", async () => {
    // A block is the case where the operator has to act, so it does not hide behind a
    // second click.
    render(<ReadinessBoard group="Content" />);
    await userEvent.click(screen.getByText("Before you run this"));
    expect(screen.getByText(/Will not run:/)).toBeTruthy();
    expect(screen.getByText(/set ANTHROPIC_API_KEY/)).toBeTruthy();
  });

  it("shows nothing at all when the readiness read fails", () => {
    state.isError = true;
    const { container } = render(<ReadinessBoard group="Audit" />);
    expect(container.innerHTML).toBe("");
    state.isError = false;
  });

  it("shows nothing for a group with no capabilities", () => {
    const { container } = render(<ReadinessBoard group="Off-page" />);
    expect(container.innerHTML).toBe("");
  });
});
