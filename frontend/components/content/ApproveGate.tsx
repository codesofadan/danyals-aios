"use client";

// What a reviewer is shown at the moment of approval.
//
// WHAT CHANGED, 2026-09-26 (the operator's decision). This dialog used to lead with the
// QA scorecard's weighted total — "61/100 weighted, does not pass" — and require an
// acknowledgement of it. The number is gone. Its own module declares the threshold and the
// weight vector uncalibrated against ranking outcomes or a human SEO grade, so it cannot
// support the verdict it reads like: a reviewer who trusts it is misled, and one who
// learns to ignore it is reading noise on the one screen where attention matters.
//
// WHAT REPLACES IT is the half that was never provisional. The deterministic detections
// underneath the score are not a matter of calibration — either the draft asserts
// something that traces to nothing supplied, or it does not — so they arrive here as named
// problems in the reviewer's own language: "a claim here has no source", "no first-hand
// experience". A clean draft shows none, which is exactly what a clean draft should show.
//
// The scorecard itself is untouched: still computed, still stored, still readable at
// /content/jobs/{code}/qa for the calibration work that would let it earn authority later.
// This is a change to what gets PUT IN FRONT OF A PERSON, not to what gets measured.
//
// Still not a gate. A reviewer may approve a draft carrying problems — the human is the
// authority — and the note records what they were shown, so "approved with an ungrounded
// claim flagged" is answerable afterwards.

import { useReviewFlags, type ReviewFlag } from "@/lib/hooks/content";
import ConfirmDialog from "@/components/ui/ConfirmDialog";

export type ApproveGateProps = {
  /** The job awaiting approval, or null when the gate is closed. */
  code: string | null;
  title: string;
  pending?: boolean;
  onCancel: () => void;
  /** Receives the note recording what the approver was shown. */
  onConfirm: (note: string) => void;
};

/** One flag, rendered as a problem or a quieter note. */
function FlagRow({ flag }: { flag: ReviewFlag }) {
  const isProblem = flag.kind === "problem";
  return (
    <div
      style={{
        marginTop: "var(--s-3)",
        paddingLeft: 10,
        borderLeft: `3px solid ${isProblem ? "var(--crit)" : "var(--warn)"}`,
      }}
    >
      <div style={{ fontWeight: 700, color: isProblem ? "var(--crit)" : "var(--ink)" }}>
        {flag.title}
      </div>
      <div className="cs" style={{ marginTop: 2 }}>
        {flag.detail}
      </div>
    </div>
  );
}

export default function ApproveGate({
  code,
  title,
  pending,
  onCancel,
  onConfirm,
}: ApproveGateProps) {
  const flagsQ = useReviewFlags(code);
  const flags = flagsQ.data?.flags ?? [];
  const problems = flags.filter((f) => f.kind === "problem");

  // The note is the audit trail. It names the problems the approver was shown, so
  // "approved with an ungrounded claim flagged" is answerable later without re-deriving
  // anything. A clean draft records that it was clean, which is equally worth knowing.
  const note = flagsQ.isError
    ? "Approved without the review checks: they could not be loaded at approval time."
    : flags.length === 0
      ? "Approved; the automated checks raised nothing."
      : `Approved with ${flags.length} check${flags.length === 1 ? "" : "s"} raised: ` +
        flags.map((f) => f.title).join("; ");

  return (
    <ConfirmDialog
      open={code !== null}
      // The tone rises only when a doctrine floor was actually tripped. Approving good
      // work is the normal, desirable path and should not look like a warning.
      tone={problems.length > 0 ? "danger" : "normal"}
      title={
        problems.length > 0 ? "Approve despite what we found?" : "Approve and publish?"
      }
      body={
        <>
          <div>
            <b>{title}</b> will be published to the client&rsquo;s site.
          </div>
          <div style={{ marginTop: "var(--s-5)" }}>
            {flagsQ.isLoading ? (
              "Checking the draft…"
            ) : flagsQ.isError ? (
              // Said plainly rather than implying a clean draft by omission.
              <span style={{ color: "var(--crit)" }}>
                The automated checks could not be loaded, so this approval is being made
                without them.
              </span>
            ) : flags.length === 0 ? (
              <span style={{ color: "var(--ok)", fontWeight: 700 }}>
                Nothing was flagged in this draft.
              </span>
            ) : (
              flags.map((f) => <FlagRow key={f.key} flag={f} />)
            )}
          </div>
        </>
      }
      reassurance="Your read is the gate — these are the checks a machine can make. This records what you were shown."
      confirmLabel={problems.length > 0 ? "Approve anyway" : "Approve & publish"}
      pending={pending}
      onCancel={onCancel}
      onConfirm={() => onConfirm(note)}
    />
  );
}
