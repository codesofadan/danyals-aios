// The client portal's honesty contract, pinned.
//
// THE CHAIN THIS PROTECTS. `report_viz.py` marks a series `placeholder=True` when it
// is a representative sample rather than the client's measured data. That flag travels:
// backend → `useClientReports` → `ClientContext.isPlaceholder` → `LockableChart` →
// a visible amber "Preview" badge instead of the green "Live" one.
//
// It works today. Nothing tested it. Every link in that chain is a plain prop or a
// derived boolean, so the failure mode is silent and ordinary: someone refactors
// `ChartBadge`, drops the `sample` prop, and a paying client is shown sample data
// wearing a "Live" badge. No test would have gone red, no error would have been
// logged, and the chart would look exactly as convincing as a real one.
//
// That is the defect class this whole recovery exists to remove — a green signal over
// something that did not happen — so the badge that prevents it gets a test.

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import LockableChart from "./LockableChart";
import type { DashboardReport } from "@/lib/client";

// The chart reads its state from ClientContext. Mocking the hook keeps this a test of
// the BADGE DECISION rather than of react-query, which is what actually matters here.
const clientState = {
  isGranted: vi.fn(() => true),
  isUnlocked: vi.fn(() => true),
  isPlaceholder: vi.fn(() => false),
  unlock: vi.fn(),
};

vi.mock("./ClientContext", () => ({ useClient: () => clientState }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));

// A FAITHFUL fixture, not a cast. The first version of this file used
// `as unknown as DashboardReport` with three fields and the component crashed on
// `viz.headline` — the cast silenced the type error that would have caught it at
// compile time. A fixture that lies about its shape tests a component that does not
// exist.
const REPORT: DashboardReport = {
  key: "audit_scores",
  label: "Audit Scores",
  short: "Audit Scores",
  icon: "fact_check",
  group: "Performance",
  desc: "Site-health scores per category, trended over time",
  viz: {
    kind: "stat",
    headline: "82",
    caption: "Site health across four categories",
    // A DIFFERENT value from the headline on purpose: identical numbers make a
    // `getByText` ambiguous, and that ambiguity reads as a component bug.
    stats: [{ label: "Overall", value: "76" }],
  },
};

function renderChart({ placeholder }: { placeholder: boolean }) {
  clientState.isGranted.mockReturnValue(true);
  clientState.isUnlocked.mockReturnValue(true);
  clientState.isPlaceholder.mockReturnValue(placeholder);
  return render(<LockableChart report={REPORT} />);
}

describe("LockableChart — the Live/Preview badge", () => {
  it("badges a backend-flagged placeholder series as Preview, never Live", () => {
    renderChart({ placeholder: true });

    expect(screen.getByText("Preview")).toBeInTheDocument();
    expect(screen.queryByText("Live")).toBeNull();
  });

  it("explains what Preview means, rather than leaving a bare label", () => {
    // A badge a client cannot interpret is barely better than no badge: "Preview" on
    // its own could read as a UI state. The tooltip says it is sample data and why.
    renderChart({ placeholder: true });

    expect(screen.getByTitle(/representative preview/i)).toBeInTheDocument();
  });

  it("badges a real measured series as Live", () => {
    renderChart({ placeholder: false });

    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(screen.queryByText("Preview")).toBeNull();
  });

  it("asks the placeholder question for the report it is actually rendering", () => {
    // A lookup against the wrong key would return `false` for everything and silently
    // badge every sample series "Live" — the exact bug, with a passing badge test.
    renderChart({ placeholder: true });

    expect(clientState.isPlaceholder).toHaveBeenCalledWith("audit_scores");
  });
});

describe("LockableChart — the grant boundary on the client surface", () => {
  // The backend enforces grants twice: the security-barrier view filters
  // `requires in (granted)`, and `report_viz.py` iterates only granted keys, so an
  // ungranted series is never queried and never serialized. This is the third layer —
  // the one on the client's own screen.
  //
  // What matters is that a locked card renders the figure NOWHERE IN THE DOM, rather
  // than drawing it and covering it with a padlock. A CSS-hidden value is still a
  // value: "inspect element" reads it straight out, and a client would be looking at a
  // report they were never granted.

  it("does not put the figure in the DOM when the report is not granted", () => {
    clientState.isGranted.mockReturnValue(false);
    clientState.isUnlocked.mockReturnValue(false);
    clientState.isPlaceholder.mockReturnValue(false);
    render(<LockableChart report={REPORT} />);

    // "Locked" appears on both the badge and the padlock overlay — assert it is
    // present, not that it is unique.
    expect(screen.getAllByText("Locked").length).toBeGreaterThan(0);
    // The headline value, the caption, and the stat label — none may be present.
    expect(screen.queryByText("82")).toBeNull();
    expect(screen.queryByText(/site health across four categories/i)).toBeNull();
  });

  it("still withholds the figure when granted but not yet opened", () => {
    // "Ready" is a granted report the client has not clicked to reveal. The reveal is
    // a deliberate act, so the data must not already be sitting in the markup.
    clientState.isGranted.mockReturnValue(true);
    clientState.isUnlocked.mockReturnValue(false);
    clientState.isPlaceholder.mockReturnValue(false);
    render(<LockableChart report={REPORT} />);

    expect(screen.getAllByText("Ready").length).toBeGreaterThan(0);
    expect(screen.queryByText("82")).toBeNull();
  });

  it("renders the figure only once unlocked", () => {
    renderChart({ placeholder: false });

    expect(screen.getByText("82")).toBeInTheDocument();
    expect(screen.getByText(/site health across four categories/i)).toBeInTheDocument();
  });

  it("always names the report, so a locked card is still identifiable", () => {
    // Withholding the DATA is the point; withholding the TITLE would leave the client
    // unable to ask for what they cannot see.
    clientState.isGranted.mockReturnValue(false);
    clientState.isUnlocked.mockReturnValue(false);
    render(<LockableChart report={REPORT} />);

    expect(screen.getByLabelText("Audit Scores")).toBeInTheDocument();
  });
});
