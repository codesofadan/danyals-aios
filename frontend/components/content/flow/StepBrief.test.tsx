/**
 * Replicating a design inside the content flow (QA 20).
 *
 * "Design Replicator is currently separate from the Content module ... the Content
 * module should allow the user to replicate a website design, specify the number of
 * pages, generate content and images, and publish the resulting pages to WordPress
 * through one integrated flow."
 *
 * The seam already existed and was unused: the replicator measured a richer design
 * system than the content analyzer does and discarded it. It now returns that profile
 * on the job, so this screen can adopt it as the design the pages are built on.
 *
 * The two properties pinned here are the ones that would quietly go wrong:
 * the COPYRIGHT assertion must be the operator's real answer, and a run that comes
 * back with no design must not read as success.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui/Toast";

import StepBrief from "./StepBrief";
import { EMPTY_FLOW, type FlowState } from "./types";

const replicateMutate = vi.fn();
let job: Record<string, unknown> | undefined;

vi.mock("@/lib/hooks/content", () => ({
  useSiteDesign: () => ({ mutate: vi.fn(), isPending: false, isError: false, error: null }),
}));
vi.mock("@/lib/hooks/replica", () => ({
  useReplicate: () => ({ mutate: replicateMutate, isPending: false, isError: false, error: null }),
  useReplicaJob: () => ({ data: job }),
}));
vi.mock("@/components/content/TemplateGallery", () => ({ default: () => <div /> }));

function renderStep(over: Partial<FlowState> = {}, patch = vi.fn()) {
  const state: FlowState = { ...EMPTY_FLOW, clientId: "cl-1", siteDomain: "client.test", ...over };
  render(<ToastProvider><StepBrief state={state} patch={patch} /></ToastProvider>);
  return patch;
}

beforeEach(() => {
  replicateMutate.mockClear();
  job = undefined;
});

describe("replicating a design in the content flow", () => {
  it("offers replication as a design source", () => {
    renderStep();
    expect(screen.getByLabelText(/Page to replicate/i)).toBeInTheDocument();
  });

  it("will not replicate until ownership is confirmed", async () => {
    renderStep({ replicaUrl: "https://example.com/page", replicaOwnerConfirmed: false });
    const btn = screen.getByRole("button", { name: /Replicate this design/i });
    expect(btn).toBeDisabled();
    await userEvent.click(btn);
    expect(replicateMutate).not.toHaveBeenCalled();
  });

  it("sends the operator's real ownership assertion, never a hardcoded true", async () => {
    renderStep({ replicaUrl: "https://example.com/page", replicaOwnerConfirmed: true });
    await userEvent.click(screen.getByRole("button", { name: /Replicate this design/i }));
    expect(replicateMutate).toHaveBeenCalledWith(
      expect.objectContaining({
        url: "https://example.com/page",
        owner_confirmed_source: true,
        client_id: "cl-1",
      }),
      expect.anything(),
    );
  });

  it("adopts the measured design when the run returns one", async () => {
    const profile = { palette: { primary: "#0f172a" } };
    job = { status: "completed", design_profile: profile };
    const patch = renderStep({ replicaJobId: "job-1", replicaUrl: "https://example.com/page" });
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith(
        expect.objectContaining({ design: profile, designFrom: "https://example.com/page" }),
      ),
    );
  });

  it("does not report a design a degraded run never produced", async () => {
    // The silent-failure guard: a degraded replica must fall back to measuring or a
    // template AND say so, not leave the operator believing the pages will carry the
    // source's design.
    job = { status: "degraded", design_profile: null };
    renderStep({ replicaJobId: "job-1", replicaUrl: "https://example.com/page" });
    expect(await screen.findByText(/no design came back/i)).toBeInTheDocument();
    expect(screen.queryByText(/Design replicated/i)).not.toBeInTheDocument();
  });

  it("reports a successful replication as one", async () => {
    job = { status: "completed", design_profile: { palette: { primary: "#0f172a" } } };
    renderStep({ replicaJobId: "job-1", replicaUrl: "https://example.com/page" });
    expect(await screen.findByText(/Design replicated/i)).toBeInTheDocument();
  });
});
