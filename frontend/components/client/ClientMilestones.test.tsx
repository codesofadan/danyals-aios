// The client's engagement timeline — the last untested client-portal surface.
//
// The property that matters here is a THREE-WAY distinction, not a two-way one:
//
//   loading      we are still asking
//   404          there genuinely is no project yet — true, and expected during
//                onboarding
//   failed       we do not know, and must not pretend otherwise
//
// Before this, the component collapsed the last two: `!project` rendered "No
// milestones yet — your engagement timeline will appear here once onboarding begins"
// for BOTH. So a 500 or a dropped connection told a paying client, in plain language,
// that their onboarding had not started. A false statement about their own
// engagement, produced by a server problem they could not see and had no way to
// distinguish from the truth.
//
// The requests surface already drew this distinction. This one did not, and the
// asymmetry is what made it easy to miss.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ClientMilestones from "./ClientMilestones";
import type { ClientProject } from "@/lib/milestones";

const refetch = vi.fn();
const projectQ = {
  data: undefined as ClientProject | undefined,
  isLoading: false,
  isError: false,
  isFetching: false,
  refetch,
};

vi.mock("@/lib/hooks/portalClient", () => ({ useClientMilestones: () => projectQ }));
vi.mock("./ClientHeader", () => ({
  default: ({ focus }: { focus: React.ReactNode }) => <div>{focus}</div>,
}));

beforeEach(() => {
  refetch.mockReset();
  projectQ.data = undefined;
  projectQ.isLoading = false;
  projectQ.isError = false;
  projectQ.isFetching = false;
});

describe("ClientMilestones — loading vs empty vs failed", () => {
  it("says it is still loading while it is", () => {
    projectQ.isLoading = true;
    render(<ClientMilestones />);

    expect(screen.getByText(/loading your timeline/i)).toBeInTheDocument();
    expect(screen.queryByText(/no milestones yet/i)).toBeNull();
  });

  it("says there is no project yet when the server says so", () => {
    // The 404 case: genuinely true during onboarding, and the client should see it.
    render(<ClientMilestones />);

    expect(screen.getByText(/no milestones yet/i)).toBeInTheDocument();
    expect(screen.getByText(/no active project/i)).toBeInTheDocument();
  });

  it("NEVER tells the client onboarding has not begun when the fetch failed", () => {
    // The defect this file exists for. "We could not load it" and "you have not
    // started" are entirely different statements, and only one of them is true.
    projectQ.isError = true;
    render(<ClientMilestones />);

    expect(screen.getByText(/couldn't load your timeline/i)).toBeInTheDocument();
    expect(screen.queryByText(/no milestones yet/i)).toBeNull();
    expect(screen.queryByText(/once onboarding begins/i)).toBeNull();
  });

  it("does not claim 'No active project' in the header on a failure either", () => {
    // The header asserts project health independently of the body, so fixing only
    // the body would leave the same false claim in a second place.
    projectQ.isError = true;
    render(<ClientMilestones />);

    expect(screen.queryByText(/no active project/i)).toBeNull();
    // Exact, not a regex: the body also says "Couldn't load your timeline", and a
    // loose match would pass on the body alone while the header still lied.
    expect(screen.getByText("Couldn't load")).toBeInTheDocument();
  });

  it("offers a retry that actually refetches", async () => {
    projectQ.isError = true;
    render(<ClientMilestones />);

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("disables the retry while a retry is in flight", () => {
    // Otherwise an impatient click stacks requests against a server already failing.
    projectQ.isError = true;
    projectQ.isFetching = true;
    render(<ClientMilestones />);

    expect(screen.getByRole("button", { name: /retrying/i })).toBeDisabled();
  });
});
