// The staff composer on a discussion thread.
//
// The property under test is not layout — it is which of two very different actions
// the button is about to perform. A thread on a client's request carries both the
// agency talking to itself and the agency talking to the client, and
// `thread_messages` is APPEND-ONLY at the database: a note posted to the wrong
// audience reaches someone it was never meant for and cannot be recalled.
//
// So: internal is the default, addressing the client is an explicit act, and the
// button says which one it is doing.

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ThreadPanel from "./ThreadPanel";
import type { ThreadMessage } from "@/lib/threads";

const postMutate = vi.fn();
let messages: ThreadMessage[] = [];

vi.mock("@/lib/hooks/threads", () => ({
  useThread: () => ({ data: messages, isLoading: false, isError: false, error: null, refetch: vi.fn() }),
  usePostMessage: () => ({ mutate: postMutate, isPending: false, error: null }),
}));

beforeEach(() => {
  postMutate.mockClear();
  messages = [];
});

describe("ThreadPanel composer", () => {
  it("defaults to an internal note", async () => {
    const user = userEvent.setup();
    render(<ThreadPanel entity="ticket" code="T-4821" />);

    // The button states the action, so the default is visible without inspecting state.
    expect(screen.getByRole("button", { name: /Add internal note/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Send to client/i })).not.toBeInTheDocument();

    await user.type(screen.getByRole("textbox"), "Client is unpaid — hold delivery");
    await user.click(screen.getByRole("button", { name: /Add internal note/i }));

    expect(postMutate).toHaveBeenCalledTimes(1);
    expect(postMutate.mock.calls[0][0]).toMatchObject({
      body: "Client is unpaid — hold delivery",
      visibility: "internal",
    });
  });

  it("sends to the client only after an explicit choice", async () => {
    const user = userEvent.setup();
    render(<ThreadPanel entity="ticket" code="T-4821" />);

    await user.click(screen.getByRole("tab", { name: /Reply to client/i }));
    expect(screen.getByRole("button", { name: /Send to client/i })).toBeInTheDocument();

    await user.type(screen.getByRole("textbox"), "Report attached.");
    await user.click(screen.getByRole("button", { name: /Send to client/i }));

    expect(postMutate.mock.calls[0][0]).toMatchObject({ visibility: "client_visible" });
  });

  it("does not send on a bare Enter", async () => {
    // A half-typed reply to a client must not leave on a stray keystroke; it cannot
    // be edited or deleted afterwards.
    const user = userEvent.setup();
    render(<ThreadPanel entity="ticket" code="T-4821" />);

    await user.type(screen.getByRole("textbox"), "half a thought{Enter}");
    expect(postMutate).not.toHaveBeenCalled();
  });

  it("refuses to post an empty message", async () => {
    const user = userEvent.setup();
    render(<ThreadPanel entity="task" code="J-1042" />);
    expect(screen.getByRole("button", { name: /Add internal note/i })).toBeDisabled();

    await user.type(screen.getByRole("textbox"), "   ");
    await user.click(screen.getByRole("button", { name: /Add internal note/i }));
    expect(postMutate).not.toHaveBeenCalled();
  });

  it("never offers to address the client on a TASK thread", () => {
    // `portal_threads` filters `entity_type='ticket'`, so a task's discussion is
    // agency-internal by construction. A "Reply to client" control there would file
    // the message as client-visible and no client would ever see it - a control that
    // silently does nothing is worse than one that is absent.
    render(<ThreadPanel entity="task" code="J-1042" />);
    expect(screen.queryByRole("tab", { name: /Reply to client/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Add internal note/i })).toBeInTheDocument();
  });

  it("hides the client option on a ticket with no client linked", () => {
    render(<ThreadPanel entity="ticket" code="T-1" clientLinked={false} />);
    expect(screen.queryByRole("tab", { name: /Reply to client/i })).not.toBeInTheDocument();
  });

  it("labels every message in the transcript with who could see it", () => {
    messages = [
      { id: "1", author: "Rae", authorKind: "staff", body: "Unpaid — hold.", visibility: "internal", createdAt: "", ago: "2h ago" },
      { id: "2", author: "Rae", authorKind: "staff", body: "On it, Friday.", visibility: "client_visible", createdAt: "", ago: "1h ago" },
    ];
    const { container } = render(<ThreadPanel entity="ticket" code="T-4821" />);

    const rows = [...container.querySelectorAll<HTMLElement>(".th-msg")];
    expect(rows).toHaveLength(2);
    // Reading a transcript back, "who saw this" is the first question.
    expect(within(rows[0]).getByText(/Internal note/i)).toBeInTheDocument();
    expect(within(rows[1]).getByText(/Reply to client/i)).toBeInTheDocument();
    expect(rows[0].className).toContain("internal");
  });

  it("says an empty thread is empty rather than showing nothing", () => {
    render(<ThreadPanel entity="task" code="J-1042" />);
    expect(screen.getByText(/Nothing here yet/i)).toBeInTheDocument();
  });
});
