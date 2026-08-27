// The Phase-1 grammar primitives, pinned to the bar the earlier ones set.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import Modal from "./Modal";
import PageHeader from "./PageHeader";
import StageTimeline from "./StageTimeline";

describe("Modal", () => {
  function mount(open = true) {
    const onClose = vi.fn();
    render(
      <Modal open={open} title="Edit connection" onClose={onClose}>
        <input aria-label="Site URL" />
      </Modal>,
    );
    return onClose;
  }

  it("renders nothing when closed", () => {
    mount(false);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("is a labelled dialog", () => {
    mount();
    expect(screen.getByRole("dialog")).toHaveAccessibleName("Edit connection");
  });

  it("closes on Escape - three hand-rolled modals had none", async () => {
    const onClose = mount();
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on scrim click but not on panel click", async () => {
    const onClose = mount();
    await userEvent.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();
    await userEvent.click(document.querySelector(".modal-scrim")!);
    expect(onClose).toHaveBeenCalled();
  });

  it("keeps Tab inside - zero hand-rolled modals trapped focus", async () => {
    mount();
    const dialog = screen.getByRole("dialog");
    for (let i = 0; i < 5; i += 1) {
      await userEvent.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });
});

describe("PageHeader", () => {
  it("states the screen's purpose next to its verb", () => {
    render(
      <PageHeader
        title="Audits"
        purpose="Every audit the platform has run, and the door to running one."
        actions={<button type="button">Run audit</button>}
      />,
    );
    expect(screen.getByRole("heading", { name: "Audits" })).toBeInTheDocument();
    expect(screen.getByText(/every audit the platform has run/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run audit" })).toBeInTheDocument();
  });
});

describe("StageTimeline", () => {
  it("announces each stage's state in words, not just colour", () => {
    render(
      <StageTimeline
        stages={[
          { key: "research", label: "Research", state: "done", detail: "6 SERP pulls" },
          { key: "draft", label: "Draft", state: "running" },
          { key: "qa", label: "QA", state: "pending" },
        ]}
      />,
    );
    expect(screen.getByText("Research").textContent).toMatch(/completed/);
    expect(screen.getByText("Draft").textContent).toMatch(/running now/);
    expect(screen.getByText("QA").textContent).toMatch(/not started/);
    expect(screen.getByText("6 SERP pulls")).toBeInTheDocument();
  });
});
