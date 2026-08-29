"use client";

// The QA verdict, at the moment of approval.
//
// DECISION D-4 asks for "advisory + mandatory acknowledgement". Only the advisory
// half existed. The 14-dimension scorecard was rendered — but on the FIFTH tab of
// a preview the reviewer did not have to open, while both Approve buttons showed
// no score at all. So the one enforced quality boundary in the whole platform was
// a button clicked with no quality information in front of it, on an action that
// publishes to a client's live site.
//
// This is deliberately NOT a second gate. The score stays advisory: a reviewer can
// approve a draft that scored badly, because the human is the authority and the
// threshold is still uncalibrated (P7A-11 — the golden set is 2 cases against the
// 30-50 the decision log asks for). What changes is that they cannot do it
// unknowingly. The acknowledgement travels in the review note, so the activity log
// records what the approver was shown.
//
// A DURABLE COLUMN IS STILL MISSING. R3A-36 specifies qa_acknowledged_by /
// qa_acknowledged_at / qa_override_reason; none of them exist. Until they do, the
// note is the audit trail — honest, searchable, and weaker than a column.

import { useContentQa } from "@/lib/hooks/content";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { qaVerdict } from "@/lib/content";

/** The floor a single dimension must clear (doctrine §11). */
const DIMENSION_FLOOR = 70;

export type ApproveGateProps = {
  /** The job awaiting approval, or null when the gate is closed. */
  code: string | null;
  title: string;
  pending?: boolean;
  onCancel: () => void;
  /** Receives the note recording what the approver acknowledged. */
  onConfirm: (note: string) => void;
};

export default function ApproveGate({
  code,
  title,
  pending,
  onCancel,
  onConfirm,
}: ApproveGateProps) {
  const qaQ = useContentQa(code);
  const qa = qaQ.data?.qa ?? null;
  const verdict = qaVerdict(qa);

  const weak = qa
    ? Object.entries(qa.dimensions)
        .filter(([, score]) => score < DIMENSION_FLOOR)
        .sort((a, b) => a[1] - b[1])
    : [];

  // The note is the audit trail. It states the score the approver was shown, so
  // "approved at 61" is answerable later without re-deriving anything.
  const note = qa
    ? `QA acknowledged: ${verdict ? `${verdict.total}/100 weighted, ${verdict.passed ? "passed" : "did not pass"}` : "not scored"}` +
      (qa.provisional ? " (provisional weights)" : "") +
      (weak.length ? `; below floor: ${weak.map(([d]) => d).join(", ")}` : "")
    : qaQ.isError
      ? "QA acknowledged: the scorecard could not be loaded at approval time"
      : "QA acknowledged: no scorecard was available";

  return (
    <ConfirmDialog
      open={code !== null}
      // Never "danger": approving good work is the normal, desirable path. The
      // tone rises only when the draft actually failed its own scorecard.
      tone={qa && !qa.passed ? "danger" : "normal"}
      title={qa && !qa.passed ? "Approve despite a failing QA score?" : "Approve and publish?"}
      body={
        <>
          <div>
            <b>{title}</b> will be published to the client&rsquo;s site.
          </div>
          <div style={{ marginTop: "var(--s-5)" }}>
            {qaQ.isLoading ? (
              "Loading the QA scorecard…"
            ) : qaQ.isError ? (
              // Say it plainly rather than implying a pass by omission.
              <span style={{ color: "var(--crit)" }}>
                The QA scorecard could not be loaded, so this approval is being made
                without it.
              </span>
            ) : qa ? (
              <>
                <span
                  style={{
                    fontWeight: 800,
                    color: qa.passed ? "var(--ok)" : "var(--crit)",
                  }}
                >
                  {verdict ? `${verdict.total}/100` : "not scored"}
                </span>{" "}
                weighted — {qa.passed ? "passes" : "does not pass"} the advisory
                threshold
                {qa.provisional ? " (weights still provisional)" : ""}.
                {weak.length > 0 ? (
                  <div style={{ marginTop: "var(--s-3)", color: "var(--body)" }}>
                    Below the {DIMENSION_FLOOR} floor:{" "}
                    <b>{weak.map(([d, s]) => `${d} (${s})`).join(", ")}</b>
                  </div>
                ) : null}
              </>
            ) : (
              "This draft has no QA scorecard."
            )}
          </div>
        </>
      }
      reassurance="The score is advisory — your approval is the gate. This records which score you were shown."
      confirmLabel="Acknowledge & approve"
      pending={pending}
      onCancel={onCancel}
      onConfirm={() => onConfirm(note)}
    />
  );
}
