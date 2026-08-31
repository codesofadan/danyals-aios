// The cron schedule, on Operations.
//
// Moved here with the panel (QA 12: "Reports and Operations overlap ... keep
// Operations as the single location for operational information, including cron
// jobs"). The property below moved with it because it is the reason the panel is
// worth rendering at all, and it would have been silently lost in the relocation.
//
// An EMPTY scheduled-jobs list must say the schedule is deliberately PAUSED.
// Celery's `beat_schedule` is `{}` by an owner instruction, not by accident. "No
// scheduled jobs are configured" reads as a broken deployment, and an operator who
// believes that goes looking for a fault that is not there.

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ScheduledJobs from "./ScheduledJobs";

const empty = { data: [], isLoading: false, isError: false, error: null };

vi.mock("@/lib/hooks/reports", () => ({
  useScheduledJobs: () => empty,
}));

describe("ScheduledJobs", () => {
  it("explains that the cron schedule is paused rather than implying a fault", () => {
    render(<ScheduledJobs />);
    expect(screen.getByTestId("jobs-parked")).toBeInTheDocument();
    expect(screen.getByText(/Background jobs are paused/i)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/No scheduled jobs are configured/i);
  });
});
