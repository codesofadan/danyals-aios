// The first tests in the dashboard.
//
// They cover the error boundaries, deliberately, because a boundary is the one piece
// of UI whose whole job is to behave correctly when everything else has failed — and
// it is therefore the piece least likely to be exercised by hand before it matters.
//
// Two properties are worth pinning, and one of them is a security property:
//
//   1. `error.message` is NEVER rendered. Next strips it in production, but the rule
//      has to hold in development too: the client portal is a tenant-facing surface
//      and an exception string is agency-internal detail. If someone "helpfully" adds
//      `{error.message}` to make debugging easier, this test fails.
//   2. `reset` is actually wired. A "Try again" button that does nothing is worse than
//      no button — it is advice that cannot work, which is the UI form of a green
//      board over a failed job.
//
// WHAT THESE DO NOT CLAIM. They do not prove that Next MOUNTS these files when a route
// throws — that is framework wiring, exercised by `next build` validating the file
// conventions and by running the app, not by a component test. Stating the limit here
// so nobody reads a green suite as end-to-end coverage of the boundary mechanism.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SegmentError from "./SegmentError";

function makeError(message: string, digest?: string): Error & { digest?: string } {
  const err = new Error(message) as Error & { digest?: string };
  if (digest) err.digest = digest;
  return err;
}

describe("SegmentError", () => {
  // The component logs every error it catches, deliberately: the server has the real
  // stack, and this is the browser-side breadcrumb that ties a user's screenshot to
  // that stack via the digest. Spying keeps the suite output readable AND turns the
  // logging into a pinned property rather than incidental noise.
  let logged: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    logged = vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    logged.mockRestore();
  });

  it("logs the failure so a screenshot can be tied back to the server stack", () => {
    render(
      <SegmentError
        area="client"
        headline="This page didn't load."
        error={makeError("boom", "d1e2f3a4")}
        reset={() => {}}
      />,
    );
    expect(logged).toHaveBeenCalledWith(
      "[aios] client render error",
      "d1e2f3a4",
      expect.any(Error),
    );
  });

  it("shows the headline and the detail it was given", () => {
    render(
      <SegmentError
        area="client"
        headline="This page didn't load."
        detail="Your reports are safe."
        error={makeError("boom")}
        reset={() => {}}
      />,
    );
    expect(screen.getByText("This page didn't load.")).toBeInTheDocument();
    expect(screen.getByText("Your reports are safe.")).toBeInTheDocument();
  });

  it("NEVER renders the exception message", () => {
    // The security property. An exception string is agency-internal detail and this
    // component renders on a tenant-facing surface.
    const secret = "psycopg.OperationalError: password authentication failed for user";
    render(
      <SegmentError
        area="client"
        headline="This page didn't load."
        error={makeError(secret)}
        reset={() => {}}
      />,
    );
    expect(screen.queryByText(new RegExp(secret, "i"))).toBeNull();
    expect(document.body.textContent).not.toContain("password authentication");
  });

  it("renders the digest, which is the only correlator that survives production", () => {
    render(
      <SegmentError
        area="admin"
        headline="This screen failed to render."
        error={makeError("boom", "d1e2f3a4")}
        reset={() => {}}
      />,
    );
    expect(screen.getByText("d1e2f3a4")).toBeInTheDocument();
  });

  it("omits the reference line entirely when there is no digest", () => {
    // Rather than rendering "Reference undefined", which reads as a bug to whoever is
    // being asked to quote it.
    render(
      <SegmentError
        area="admin"
        headline="This screen failed to render."
        error={makeError("boom")}
        reset={() => {}}
      />,
    );
    expect(screen.queryByText(/Reference/i)).toBeNull();
  });

  it("actually calls reset when Try again is pressed", async () => {
    const reset = vi.fn();
    render(
      <SegmentError
        area="team"
        headline="This screen failed to render."
        error={makeError("boom")}
        reset={reset}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(reset).toHaveBeenCalledOnce();
  });

  it("announces itself to assistive technology", () => {
    // A screen reader user must be told the screen failed, not left on a page that
    // silently changed under them.
    render(
      <SegmentError
        area="client"
        headline="This page didn't load."
        error={makeError("boom")}
        reset={() => {}}
      />,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
