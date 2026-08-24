// The one place in the client portal where the client WRITES.
//
// Everything else on this surface is a read, so the worst a bug can do is show the
// wrong thing. Here a bug can lose what a client typed, tell them a message was sent
// when it was not, or raise the same request twice. The component already handles all
// three correctly — this pins that, because every one of them is a plain piece of
// local state that a refactor could quietly drop.
//
// `retry: 0` on the mutation stops react-query re-sending a request after a transport
// failure. It does NOT stop a person clicking Submit twice, which is the far likelier
// double. That is what the `busy` guard is for, and it is tested here.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ClientRequests from "./ClientRequests";

type AddArgs = [
  { kind: string; subject: string; detail: string },
  { onSuccess: () => void; onError: () => void },
];

const addRequest = vi.fn();
const clientState = {
  requests: [] as unknown[],
  requestsLoading: false,
  requestsError: false,
  refetchRequests: vi.fn(),
  addRequest,
};

vi.mock("./ClientContext", () => ({ useClient: () => clientState }));
vi.mock("./ClientHeader", () => ({ default: () => null }));

beforeEach(() => {
  addRequest.mockReset();
  clientState.requests = [];
  clientState.requestsLoading = false;
  clientState.requestsError = false;
});

// The subject input, addressed by its real placeholder. Named so the queries read as
// intent rather than as string matching.
const subjectField = () => screen.getByPlaceholderText(/please unlock the backlink/i);

async function compose(subject = "Please refresh my audit") {
  render(<ClientRequests />);
  await userEvent.type(subjectField(), subject);
  // Captured as an element, not re-queried: the accessible name changes to
  // "Sending…" while in flight, so a name-based re-query would stop finding it —
  // which is exactly the state the double-click test needs to assert on.
  return screen.getByRole("button", { name: /send request/i });
}

describe("ClientRequests — the client's only write path", () => {
  it("sends only kind, subject and detail — never a client id", async () => {
    // The tenant boundary on the wire. `client_id` is pinned server-side from the
    // authenticated session; a client-supplied one would be an attempt to write
    // into another tenant, and the body must not carry the field at all.
    const send = await compose();
    await userEvent.click(send);

    await waitFor(() => expect(addRequest).toHaveBeenCalled());
    const [payload] = addRequest.mock.calls[0] as AddArgs;
    expect(Object.keys(payload).sort()).toEqual(["detail", "kind", "subject"]);
  });

  it("does NOT clear what the client typed when the send fails", async () => {
    // Losing a client's typed message on a network blip is a real harm, and the
    // tempting simplification — clear the form optimistically on submit — causes it.
    const send = await compose("Please refresh my audit");
    addRequest.mockImplementation((_payload: unknown, cbs: AddArgs[1]) => cbs.onError());
    await userEvent.click(send);

    await waitFor(() => {
      expect(subjectField()).toHaveValue("Please refresh my audit");
    });
  });

  it("never says a failed request was sent", async () => {
    // The project's whole theme, on the client's own screen.
    const send = await compose();
    addRequest.mockImplementation((_p: unknown, cbs: AddArgs[1]) => cbs.onError());
    await userEvent.click(send);

    await waitFor(() => {
      expect(screen.getByText(/couldn't send/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/request sent/i)).toBeNull();
  });

  it("confirms and clears only once the send actually succeeded", async () => {
    const send = await compose();
    addRequest.mockImplementation((_p: unknown, cbs: AddArgs[1]) => cbs.onSuccess());
    await userEvent.click(send);

    await waitFor(() => {
      expect(screen.getByText(/request sent/i)).toBeInTheDocument();
    });
    expect(subjectField()).toHaveValue("");
  });

  it("cannot raise the same request twice from a double click", async () => {
    // `retry: 0` covers a transport re-send. It does not cover a person clicking
    // twice, which is the likelier double — and a duplicate request is visible to
    // the client and embarrassing to the agency.
    const send = await compose();
    addRequest.mockImplementation(() => {
      /* in flight: neither callback fires */
    });

    await userEvent.click(send);
    await userEvent.click(send);

    expect(addRequest).toHaveBeenCalledTimes(1);
    expect(send).toBeDisabled();
  });

  it("refuses a subject too short to act on", async () => {
    render(<ClientRequests />);
    await userEvent.type(subjectField(), "hi");

    expect(screen.getByRole("button", { name: /send request/i })).toBeDisabled();
  });
});
