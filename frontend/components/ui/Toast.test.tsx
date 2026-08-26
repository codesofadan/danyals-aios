// The rules that matter are the two the old hand-rolled mechanisms broke:
// a failure must not vanish on a timer, and it must carry its reason.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider, describeError, useToast } from "./Toast";

function Harness() {
  const toast = useToast();
  return (
    <>
      <button type="button" onClick={() => toast.success("Proof saved")}>
        ok
      </button>
      <button type="button" onClick={() => toast.error("Couldn't save proof", "403")}>
        fail
      </button>
      <button
        type="button"
        onClick={() =>
          toast.fromError("Couldn't save proof", {
            message: "You do not have permission",
            status: 403,
          })
        }
      >
        fromError
      </button>
    </>
  );
}

function mount() {
  return render(
    <ToastProvider>
      <Harness />
    </ToastProvider>,
  );
}

describe("Toast", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  it("shows nothing until something happens", () => {
    mount();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("announces a success politely and clears it on its own", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mount();
    await user.click(screen.getByRole("button", { name: "ok" }));
    expect(screen.getByRole("status")).toHaveTextContent("Proof saved");

    await act(async () => {
      vi.advanceTimersByTime(4500);
    });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("does NOT auto-dismiss a failure — an error nobody sees is the bug", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mount();
    await user.click(screen.getByRole("button", { name: "fail" }));
    expect(screen.getByRole("alert")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("lets the operator dismiss a failure", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mount();
    await user.click(screen.getByRole("button", { name: "fail" }));
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("carries the API's own reason instead of a shrug", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mount();
    await user.click(screen.getByRole("button", { name: "fromError" }));
    expect(screen.getByRole("alert")).toHaveTextContent("You do not have permission");
  });

  it("stacks several at once", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mount();
    await user.click(screen.getByRole("button", { name: "fail" }));
    await user.click(screen.getByRole("button", { name: "fromError" }));
    expect(screen.getAllByRole("alert")).toHaveLength(2);
  });
});

describe("describeError", () => {
  it("prefers the message, and names the status when there is one", () => {
    expect(describeError({ message: "Nope", status: 403 })).toBe("Nope (403)");
  });

  it("falls back to the status alone", () => {
    expect(describeError({ status: 500 })).toMatch(/500/);
  });

  it("passes a plain string through", () => {
    expect(describeError("boom")).toBe("boom");
  });

  it("says nothing rather than inventing a reason", () => {
    expect(describeError(undefined)).toBeUndefined();
    expect(describeError({})).toBeUndefined();
  });
});
