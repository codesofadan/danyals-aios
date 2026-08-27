"use client";

// One modal, instead of eleven.
//
// The codebase carried 11 hand-rolled modal/drawer scaffolds across two
// competing class systems (`modal-scrim`+`modal` vs `modal-overlay`+`modal-panel`)
// plus two bespoke ones, with the identical 4-line Escape effect written out
// EIGHT times - and three modals that had no Escape at all, including the
// largest form in the product. None trapped focus; none restored it.
//
// This renders the `modal-scrim` + `modal` classes globals.css already styles,
// so migrating a hand-roll changes no pixels - what it adds is the behaviour:
// focus trap, focus restore, Escape, scrim-click-to-close (panel clicks do not
// close), and a real labelled role="dialog".
//
// For CONFIRMATIONS use ConfirmDialog, which builds on the same focus hook and
// adds tone, consequence copy and type-to-confirm. This is for content: forms,
// previews, editors.

import { useId, useRef, type ReactNode } from "react";
import useFocusTrap from "./useFocusTrap";

export type ModalProps = {
  open: boolean;
  /** The dialog's name, announced and rendered as the header. */
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  /** Footer actions (buttons). Rendered right-aligned below the body. */
  footer?: ReactNode;
  /** "wide" matches the existing `.modal.wide` treatment for large forms. */
  wide?: boolean;
};

export default function Modal({ open, title, onClose, children, footer, wide }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useFocusTrap(open, panelRef, onClose);

  if (!open) return null;

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div
        ref={panelRef}
        className={wide ? "modal wide" : "modal"}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        style={{ outline: "none" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "var(--s-6)",
            padding: "var(--s-7) var(--s-7) 0",
          }}
        >
          <h2 id={titleId} style={{ margin: 0, fontSize: "var(--fs-lg)", fontWeight: 800 }}>
            {title}
          </h2>
          <button type="button" className="iconbtn" aria-label="Close" onClick={onClose}>
            <span className="material-symbols-rounded" aria-hidden="true">close</span>
          </button>
        </div>
        <div style={{ padding: "var(--s-6) var(--s-7)" }}>{children}</div>
        {footer ? (
          <div
            style={{
              display: "flex",
              justifyContent: "flex-end",
              gap: "var(--s-4)",
              padding: "0 var(--s-7) var(--s-7)",
            }}
          >
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );
}
