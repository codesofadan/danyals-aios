"use client";

// The confirmation step for actions that spend money, change what a client can
// see, or cannot be undone.
//
// THE RISK GRADIENT WAS INVERTED. Deleting a WordPress connection — a thing you
// can recreate in a minute — asked "are you sure?". Meanwhile the platform-wide
// API SPEND HALT, whose own card copy promises to "instantly pause every paid
// feature across the platform", fired on a single click. So did replaying a
// dead letter (re-runs a job, with real side effects and real spend), cancelling
// a running job, and exposing an audit report to a tenant. Eleven such actions
// shipped with no confirmation at all.
//
// WHY NOT window.confirm. Five call sites already use it and it does work, but
// it cannot carry a consequence sentence, cannot style the destructive verb,
// cannot require typed acknowledgement for the truly irreversible, and is
// suppressible by the browser. It also can't say what will NOT happen, which is
// usually the sentence that lets someone click with confidence.
//
// ACCESSIBILITY, because this is where the app's modals were weakest: of the
// eleven hand-rolled modals in this codebase, ZERO trapped focus and three had
// no Escape handling, so Tab from inside a dialog walked into the page behind
// it. This one traps Tab, restores focus to whatever opened it, closes on
// Escape, and is a real role="dialog" + aria-modal.

import { useEffect, useId, useRef, useState } from "react";

export type ConfirmTone = "danger" | "caution" | "normal";

export type ConfirmDialogProps = {
  open: boolean;
  /** The question, as a verb phrase: "Halt all API spend?" */
  title: string;
  /** What will happen. Say the consequence, not a warning adjective. */
  body: React.ReactNode;
  /** Optional: what is NOT affected. Often the sentence that unblocks someone. */
  reassurance?: string;
  /** The button's label — name the action, never "OK": "Halt spending". */
  confirmLabel: string;
  cancelLabel?: string;
  tone?: ConfirmTone;
  /** When set, the confirm button stays disabled until this exact text is typed.
   *  Reserve it for the irreversible and the platform-wide. */
  typeToConfirm?: string;
  /** True while the mutation is in flight. */
  pending?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

const TONE_ICON: Record<ConfirmTone, string> = {
  danger: "report",
  caution: "warning",
  normal: "help",
};

export default function ConfirmDialog({
  open,
  title,
  body,
  reassurance,
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "caution",
  typeToConfirm,
  pending = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const returnFocusTo = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const bodyId = useId();
  const [typed, setTyped] = useState("");

  // Reset the typed acknowledgement whenever the dialog reopens, so a previous
  // confirmation can never pre-arm the next one.
  useEffect(() => {
    if (open) setTyped("");
  }, [open]);

  useEffect(() => {
    if (!open) return;
    returnFocusTo.current = document.activeElement as HTMLElement | null;
    // Focus the panel rather than the confirm button: landing on the
    // destructive verb invites a reflexive Enter.
    panelRef.current?.focus();
    return () => returnFocusTo.current?.focus?.();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCancel();
        return;
      }
      if (e.key !== "Tab") return;
      const panel = panelRef.current;
      if (!panel) return;
      const focusable = panel.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      // Wrap at both ends, and pull focus back in if it has escaped the panel.
      if (e.shiftKey && (active === first || active === panel)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [open, onCancel]);

  if (!open) return null;

  const armed = !typeToConfirm || typed.trim() === typeToConfirm;

  return (
    <div className="modal-scrim" onClick={onCancel}>
      <div
        ref={panelRef}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        tabIndex={-1}
        style={{ maxWidth: 460, outline: "none" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", gap: 12, padding: "18px 18px 0" }}>
          <span
            className="material-symbols-rounded"
            aria-hidden="true"
            style={{
              fontSize: 26,
              color: tone === "danger" ? "var(--crit)" : "var(--warn)",
            }}
          >
            {TONE_ICON[tone]}
          </span>
          <div>
            <h2 id={titleId} style={{ margin: 0, fontSize: 15.5, fontWeight: 800 }}>
              {title}
            </h2>
            <div
              id={bodyId}
              style={{
                marginTop: 6,
                fontSize: 12.8,
                lineHeight: 1.6,
                color: "var(--body)",
              }}
            >
              {body}
              {reassurance ? (
                <div style={{ marginTop: 8, color: "var(--muted)" }}>{reassurance}</div>
              ) : null}
            </div>
          </div>
        </div>

        {typeToConfirm ? (
          <div className="fld" style={{ padding: "14px 18px 0" }}>
            <label htmlFor={`${titleId}-ack`}>
              Type <b>{typeToConfirm}</b> to confirm
            </label>
            <input
              id={`${titleId}-ack`}
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              autoComplete="off"
              placeholder={typeToConfirm}
            />
          </div>
        ) : null}

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 8,
            padding: 18,
          }}
        >
          <button type="button" className="ghostbtn" onClick={onCancel} disabled={pending}>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={tone === "danger" ? "danger-btn" : "primary-btn"}
            onClick={onConfirm}
            disabled={pending || !armed}
          >
            {pending ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
