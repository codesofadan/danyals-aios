// Approving content publishes to a client's live site. The approver must be
// looking at the QA score when they do it.
//
// THE BUG THIS CATCHES, in its exact shape:
//
//     <button onClick={() => onAction(job.id, "approve")}>Approve & publish</button>
//
// No score, no dialog, straight to `status = publishing`. Three of the four
// content approve buttons shipped exactly that. The 14-dimension scorecard did
// exist — on the FIFTH tab of a preview whose default tab is "article", so a
// reviewer could sign off on a client's live page having never opened it.
//
// This is not a second gate and must not become one. The score stays advisory:
// a human can approve a draft that scored 61, because the human is the authority
// and the threshold is still uncalibrated (P7A-11 — the golden set holds 2 cases
// against the 30-50 the decision log asks for). What is enforced is only that
// they cannot do it UNKNOWINGLY.
//
// THE RULE: a file under components/content/ that dispatches the "approve"
// review action must render `ApproveGate` — the shared dialog carrying the
// weighted total, the sub-floor dimensions, and the "Acknowledge & approve"
// confirm. One file is exempted BY NAME below, for a stated reason.
//
// An earlier draft of this guard also accepted `useContentQa`, on the reasoning
// that a file fetching the scorecard must be showing it. That was wrong, and
// wrong in the exact way that lets the original bug through: ReviewPreview
// fetched the scorecard for its QA TAB while its Approve button published with
// no dialog at all. Fetching a score somewhere in the file says nothing about
// whether it is in front of the person clicking Approve. Only an explicit
// mechanism at the approve site counts.
//
// WHAT THIS CANNOT CATCH, because it is a textual scan:
//   - a file that imports ApproveGate and renders it for the wrong job, or
//     renders it and then approves outside it;
//   - an approve dispatched through a variable (`onAction(id, act)`) rather than
//     the "approve" literal;
//   - an approve surface added OUTSIDE components/content/ — the GMB, Web 2.0
//     and portal review buttons are separate flows with their own rules and are
//     deliberately out of scope here.
// A green run means "no file matches the known-bad shape", never "every approval
// in the product shows a score."

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const DIR = join(process.cwd(), "components", "content");

/** Dispatches the review action rather than merely declaring its type. */
const DISPATCHES_APPROVE = /\b(?:onAction|onReview|review\.mutate|decide\.mutate)\s*\(\s*[^)]*"approve"/s;

/** Renders the shared gate — not merely mentions it in prose. */
const RENDERS_GATE = /<ApproveGate\b/;

/**
 * Files that implement an equivalent acknowledgement of their own. Each entry
 * needs a reason, and the reason has to be about the APPROVE SITE.
 */
const OWN_GATE = new Map<string, string>([
  [
    "ContentJobDetail.tsx",
    // Its approve ConfirmDialog renders "The QA scorecard reads N / 100 —
    // passed/FAILED" and sets typeToConfirm="PUBLISH" when the draft failed, so
    // approving over a failing score costs a typed word. That is a STRONGER
    // acknowledgement than ApproveGate's single click, not a weaker one.
    "renders the score in its own ConfirmDialog and requires typing PUBLISH on a failed draft",
  ],
]);

describe("every content approve button shows the QA score", () => {
  const files = readdirSync(DIR).filter(
    (f) => f.endsWith(".tsx") && !f.endsWith(".test.tsx"),
  );

  it("finds the approve surfaces at all (the scan is not vacuous)", () => {
    const dispatchers = files.filter((f) =>
      DISPATCHES_APPROVE.test(readFileSync(join(DIR, f), "utf8")),
    );
    // If this drops to zero the regex has rotted and every assertion below is
    // silently passing over an empty list.
    expect(dispatchers.length).toBeGreaterThanOrEqual(3);
  });

  it.each(files)("%s", (file) => {
    const src = readFileSync(join(DIR, file), "utf8");
    if (!DISPATCHES_APPROVE.test(src)) return;
    if (OWN_GATE.has(file)) {
      // Still assert the exemption is EARNED, so it cannot rot into a blanket
      // pass if someone later strips the dialog out of an exempted file.
      expect(
        /typeToConfirm|ConfirmDialog/.test(src) && /\bqaVerdict\b|\buseContentQa\b/.test(src),
        `${file} is exempt because it ${OWN_GATE.get(file)}, but it no longer ` +
          `shows a score in a confirm. Either restore that or route it through ` +
          `<ApproveGate> and drop the exemption.`,
      ).toBe(true);
      return;
    }
    expect(
      RENDERS_GATE.test(src),
      `${file} approves content without showing the QA score. Render ` +
        `<ApproveGate> (see ReviewGate.tsx) so the approver acknowledges the ` +
        `scorecard they are publishing over.`,
    ).toBe(true);
  });
});
