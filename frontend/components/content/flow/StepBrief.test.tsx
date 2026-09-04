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
let questions: { slotKey: string; question: string }[] = [];

// Every hook the screen calls has to be here: a vi.mock factory REPLACES the module,
// so a hook added to the component and not added here throws "no export is defined"
// and takes the whole file down with it, whatever it was actually testing.
vi.mock("@/lib/hooks/content", () => ({
  useSiteDesign: () => ({ mutate: vi.fn(), isPending: false, isError: false, error: null }),
  useExperienceQuestions: () => ({ data: questions, isPending: false, isError: false }),
}));
vi.mock("@/lib/hooks/replica", () => ({
  useReplicate: () => ({ mutate: replicateMutate, isPending: false, isError: false, error: null }),
  useReplicaJob: () => ({ data: job }),
  useReplicaRuns: () => ({ data: [] }),
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
  questions = [];
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

/**
 * The Experience interview, asked BEFORE the build.
 *
 * It used to be asked by the pipeline, after the operator pressed Build on screen 4 -
 * so a run they believed was under way parked itself on five questions they had never
 * been shown. The questions are a pure function of the page kind, so there was never
 * a reason to wait for a job to exist before asking them.
 *
 * What is pinned here is that the questions are RENDERED and that an answer reaches
 * `patch` under the backend's own slot key - the key is the whole contract, because a
 * mismatched one seeds nothing and the page halts exactly as before, silently.
 */
describe("the Experience interview on screen 3", () => {
  it("asks the proof questions this page kind requires", () => {
    questions = [
      { slotKey: "founding_date", question: "What year did the business start trading?" },
      { slotKey: "license_permit", question: "What is the licence number?" },
    ];
    renderStep();
    expect(screen.getByText(/What year did the business start trading\?/)).toBeInTheDocument();
    expect(screen.getByText(/What is the licence number\?/)).toBeInTheDocument();
    expect(screen.getByText(/0 of 2 answered/)).toBeInTheDocument();
  });

  it("records an answer under the slot key the pipeline seeds from", async () => {
    questions = [{ slotKey: "license_permit", question: "What is the licence number?" }];
    const patch = renderStep();
    await userEvent.type(screen.getByLabelText(/What is the licence number\?/), "M-41982");
    expect(patch).toHaveBeenCalledWith(
      expect.objectContaining({ experience: expect.objectContaining({ license_permit: "M" }) }),
    );
  });

  it("counts only answers that are actually filled in", () => {
    questions = [
      { slotKey: "founding_date", question: "Trading since?" },
      { slotKey: "license_permit", question: "Licence?" },
    ];
    // Whitespace is not an answer: the pipeline's gate counts a blank slot as
    // unanswered and halts, so the screen must not report it as done.
    renderStep({ experience: { founding_date: "2011", license_permit: "   " } });
    expect(screen.getByText(/1 of 2 answered/)).toBeInTheDocument();
  });
});
