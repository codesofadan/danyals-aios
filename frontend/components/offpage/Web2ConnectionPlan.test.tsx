/**
 * The connection screen's two jobs: hold ONE login per client, and refuse to overclaim
 * what it reaches.
 *
 * THE DEFECT THIS SCREEN REPLACES. A grid of cards that all said "Connect" told an
 * operator nothing about which platform was one click away and which needed a paid API
 * tier — so a client sat at four connected platforms indefinitely and nobody could say
 * why. The rules worth guarding here are the ones that are easy to "simplify" away:
 *
 *   • A sealed password is never rendered back. The box stays EMPTY next to the badge
 *     that says one is held — that is what write-only looks like on screen.
 *   • A BLANK password field is not a clear. A form that round-trips an empty input
 *     must never be the thing that revokes a client's access to every platform they
 *     are on; clearing is its own deliberate button.
 *   • `one_step` and `blocked` stay separate. One is an action an operator can take
 *     today; the other is procurement. Merging them into "not connected" is how the
 *     old screen wasted afternoons.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Web2ConnectionPlan from "./Web2ConnectionPlan";

const put = vi.fn(async () => ({}));

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(async (path: string) => {
      if (path.includes("/connection-plan")) {
        return {
          clientId: "cl-1",
          summary: "23 platform(s) publish now, 30 need one sign-in step, 0 have no usable API.",
          readyCount: 23,
          oneStepCount: 30,
          blockedCount: 1,
          platforms: [
            { platform: "Telegra.ph", readiness: "ready", action: "", reason: "", missing: [] },
            {
              platform: "Bluesky", readiness: "one_step",
              action: "Generate an app password in Bluesky's settings and save it here.",
              reason: "", missing: ["app_password"],
            },
            {
              platform: "Medium", readiness: "blocked",
              action: "", reason: "no usable publishing API", missing: [],
            },
          ],
          notes: ["No shared login is set for this client yet."],
        };
      }
      if (path.includes("/identity")) {
        return {
          clientId: "cl-1", client: "Leeds Drainage Co", handleBase: "leedsdrainageco",
          contactEmail: "", imapHost: "", imapPort: 993, imapUser: "",
          imapPasswordHeld: false, mailboxReady: false,
          username: "leedsdrainageco", passwordHeld: true,
          proofPoints: [], testimonials: [], uniqueData: [], services: [],
        };
      }
      return {};
    }),
    put: (...args: unknown[]) => put(...(args as [])),
    post: vi.fn(async () => ({})),
  },
}));

function renderPlan() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Web2ConnectionPlan clientId="cl-1" />
    </QueryClientProvider>,
  );
}

describe("what the one login reaches", () => {
  it("answers with a number per state, not a yes or a no", async () => {
    renderPlan();
    expect(await screen.findByText(/23 platform\(s\) publish now/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /23 Publishes now/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /30 One step away/i })).toBeInTheDocument();
    // `blocked` keeps its own count rather than being folded into "not connected":
    // an operator sent to look for a button that does not exist is the waste this
    // separation prevents.
    expect(screen.getByRole("button", { name: /1 No usable API/i })).toBeInTheDocument();
  });

  it("names the ONE action for a platform that is one step away", async () => {
    renderPlan();
    // The whole point. "Connect" is what the old screen said, and it is why a client
    // could sit at four platforms forever with nobody able to say what was missing.
    expect(
      await screen.findByText(/Generate an app password in Bluesky's settings/i),
    ).toBeInTheDocument();
  });

  it("reports the platforms nobody can connect today, rather than hiding them", async () => {
    renderPlan();
    fireEvent.click(await screen.findByRole("button", { name: /1 No usable API/i }));
    expect(await screen.findByText("Medium")).toBeInTheDocument();
    expect(screen.getByText(/no usable publishing API/i)).toBeInTheDocument();
  });
});

describe("the sealed password", () => {
  it("is never rendered back into the form", async () => {
    renderPlan();
    const field = await screen.findByLabelText(/^Password/i);
    // A held password shows as a BADGE and an empty box. Populating the input with
    // anything — even a placeholder of the right length — would be the screen claiming
    // to know a secret it deliberately cannot read.
    expect((field as HTMLInputElement).value).toBe("");
    expect(screen.getByText(/Sealed/i)).toBeInTheDocument();
  });

  it("does not send a password when the operator left the box empty", async () => {
    renderPlan();
    // Wait for the stored username to be IN THE BOX, not merely for the fetch to land:
    // the hydrate runs in an effect one render later, and asserting in between tests a
    // form that is about to change under you.
    await waitFor(() =>
      expect((screen.getByLabelText(/Username/i) as HTMLInputElement).value)
        .toBe("leedsdrainageco"),
    );
    put.mockClear();

    fireEvent.change(screen.getByLabelText(/Username/i), { target: { value: "newhandle" } });
    fireEvent.click(screen.getByRole("button", { name: /Save login/i }));

    await waitFor(() => expect(put).toHaveBeenCalled());
    const body = (put.mock.calls[0] as unknown as [string, Record<string, unknown>])[1];
    // BLANK IS NOT CLEAR. If an empty field travelled as `password: ""` the save would
    // revoke the credential that unlocks every platform this client is on — silently,
    // as a side effect of editing the username.
    expect(body).not.toHaveProperty("password");
    expect(body.username).toBe("newhandle");
  });

  it("never overwrites what the operator is typing when the fetch lands", async () => {
    // THE REAL DEFECT THIS GUARDS. The form is usable the instant it mounts, and the
    // stored identity arrives a moment later. A plain `useEffect([identity])` re-seeds
    // the field AFTER that first render — so a username typed during the load is
    // replaced by the stored one, mid-word, with nothing on screen to explain it.
    renderPlan();
    const field = screen.getByLabelText(/Username/i) as HTMLInputElement;
    expect(field.value).toBe("");
    fireEvent.change(field, { target: { value: "typed-while-loading" } });

    // Let the identity land and its hydrate effect run.
    await screen.findByText(/Sealed/i);
    await waitFor(() => expect(screen.getByText(/23 platform\(s\)/i)).toBeInTheDocument());

    expect((screen.getByLabelText(/Username/i) as HTMLInputElement).value)
      .toBe("typed-while-loading");
  });

  it("clears only through its own deliberate action", async () => {
    renderPlan();
    // The clear button only exists once a sealed password is known about.
    const clear = await screen.findByRole("button", { name: /Remove the stored password/i });
    put.mockClear();

    fireEvent.click(clear);
    await waitFor(() => expect(put).toHaveBeenCalled());
    const body = (put.mock.calls[0] as unknown as [string, Record<string, unknown>])[1];
    expect(body.clearPassword).toBe(true);
  });
});
