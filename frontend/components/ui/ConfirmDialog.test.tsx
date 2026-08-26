// The confirmation step is a safety device, so its behaviour is pinned rather
// than assumed. Every case below corresponds to a defect the audit found in the
// hand-rolled modals this replaces: three had no Escape, none trapped focus,
// none restored focus, and eleven destructive actions had no dialog at all.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import ConfirmDialog from "./ConfirmDialog";

function open(props: Partial<React.ComponentProps<typeof ConfirmDialog>> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <ConfirmDialog
      open
      title="Halt all API spending?"
      body="Every paid call is refused platform-wide."
      confirmLabel="Halt spending"
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...props}
    />,
  );
  return { onConfirm, onCancel };
}

describe("ConfirmDialog", () => {
  it("is a real dialog, labelled by its title", () => {
    open();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleName("Halt all API spending?");
  });

  it("renders nothing when closed", () => {
    render(
      <ConfirmDialog
        open={false}
        title="t"
        body="b"
        confirmLabel="go"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("names the action on its button instead of saying OK", () => {
    open();
    expect(screen.getByRole("button", { name: "Halt spending" })).toBeInTheDocument();
  });

  it("cancels on Escape — three modals in this app had no Escape at all", async () => {
    const { onCancel, onConfirm } = open();
    await userEvent.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("cancels when the scrim behind it is clicked", async () => {
    const { onCancel } = open();
    await userEvent.click(document.querySelector(".modal-scrim")!);
    expect(onCancel).toHaveBeenCalled();
  });

  it("does NOT cancel when the panel itself is clicked", async () => {
    const { onCancel } = open();
    await userEvent.click(screen.getByRole("dialog"));
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("does not open focused on the destructive verb", () => {
    open();
    // Landing on the confirm button invites a reflexive Enter.
    expect(document.activeElement).not.toBe(
      screen.getByRole("button", { name: "Halt spending" }),
    );
  });

  it("keeps Tab inside the dialog — no modal in this app trapped focus", async () => {
    open();
    const dialog = screen.getByRole("dialog");
    // Walk further than there are focusable elements; focus must never escape.
    for (let i = 0; i < 6; i += 1) {
      await userEvent.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });

  it("restores focus to whatever opened it", async () => {
    function Host() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open
          </button>
          <ConfirmDialog
            open={open}
            title="Sure?"
            body="b"
            confirmLabel="Do it"
            onConfirm={() => setOpen(false)}
            onCancel={() => setOpen(false)}
          />
        </>
      );
    }
    render(<Host />);
    const opener = screen.getByRole("button", { name: "Open" });
    await userEvent.click(opener);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(document.activeElement).toBe(opener);
  });

  describe("typeToConfirm — reserved for the irreversible", () => {
    it("keeps the action disabled until the exact word is typed", async () => {
      const { onConfirm } = open({ typeToConfirm: "RESUME" });
      const button = screen.getByRole("button", { name: "Halt spending" });
      expect(button).toBeDisabled();

      await userEvent.type(screen.getByRole("textbox"), "resum");
      expect(button).toBeDisabled();

      await userEvent.clear(screen.getByRole("textbox"));
      await userEvent.type(screen.getByRole("textbox"), "RESUME");
      expect(button).toBeEnabled();
      await userEvent.click(button);
      expect(onConfirm).toHaveBeenCalledTimes(1);
    });

    it("labels the acknowledgement field", () => {
      open({ typeToConfirm: "RESUME" });
      expect(screen.getByRole("textbox")).toHaveAccessibleName(/type\s+RESUME\s+to confirm/i);
    });
  });

  it("blocks both buttons while the mutation is in flight", () => {
    open({ pending: true });
    expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  });
});
