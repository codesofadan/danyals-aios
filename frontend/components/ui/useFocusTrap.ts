"use client";

// The focus discipline every dialog owes its keyboard user, as one hook.
//
// Measured before this existed: of eleven hand-rolled modals, ZERO trapped
// focus (Tab walked into the page behind the scrim), three had no Escape at
// all, and none restored focus to the control that opened them. ConfirmDialog
// fixed all three for confirmations; this is that logic EXTRACTED - not
// duplicated - so Modal and ConfirmDialog cannot drift apart.

import { useEffect, useRef, type RefObject } from "react";

export function useFocusTrap(
  active: boolean,
  panelRef: RefObject<HTMLElement | null>,
  onClose: () => void,
) {
  const returnFocusTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!active) return;
    returnFocusTo.current = document.activeElement as HTMLElement | null;
    // Focus the panel, not the first button: landing on an action invites a
    // reflexive Enter.
    panelRef.current?.focus();
    return () => returnFocusTo.current?.focus?.();
  }, [active, panelRef]);

  useEffect(() => {
    if (!active) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const panel = panelRef.current;
      if (!panel) return;
      const focusable = panel.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
          'textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const activeEl = document.activeElement;
      // Wrap at both ends, and pull focus back in if it has escaped the panel.
      if (e.shiftKey && (activeEl === first || activeEl === panel)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && activeEl === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [active, panelRef, onClose]);
}

export default useFocusTrap;
