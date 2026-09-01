import { describe, expect, it } from "vitest";

import { diagnoseConnection } from "../src/lib/diagnose";

/**
 * The night of 2026-09-01, pairing failed for three stacked reasons — a CORS allowlist
 * with no extension origin, a default pointing at a stale backend on another port, and
 * `localhost` resolving to ::1 where the IPv4-only server refuses — and every one of
 * them rendered as the same two words: "Failed to fetch". These fixtures pin that each
 * failure mode maps to its OWN verdict, so the panel can say what to do next.
 *
 * The fixture fetch distinguishes the two request shapes the prober sends: the
 * `no-cors` reachability probe and the credentialed call. Shuffling the stage order
 * breaks the cors fixture (an opaque success must classify as CORS, never unreachable).
 */

type Behavior = "reject" | "opaque" | number; // number = respond with that HTTP status

function fetchTable(byUrl: (url: string, init?: RequestInit) => Behavior) {
  return async (url: string, init?: RequestInit): Promise<Response> => {
    const behavior = byUrl(url, init);
    if (behavior === "reject") throw new TypeError("Failed to fetch");
    if (behavior === "opaque") return new Response(null, { status: 200 });
    return new Response(
      JSON.stringify({ error: { message: `status ${behavior}` } }),
      { status: behavior, headers: { "content-type": "application/json" } },
    );
  };
}

const isProbe = (init?: RequestInit): boolean => init?.mode === "no-cors";

describe("diagnoseConnection", () => {
  it("nothing listening anywhere → server_unreachable", async () => {
    const d = await diagnoseConnection("http://127.0.0.1:8000", "aop_x", fetchTable(() => "reject"));
    expect(d.verdict).toBe("server_unreachable");
  });

  it("localhost rejects but 127.0.0.1 answers → ipv6_localhost_trap, carrying the working address", async () => {
    const d = await diagnoseConnection(
      "http://localhost:8000",
      "aop_x",
      fetchTable((url) => (url.includes("127.0.0.1") ? "opaque" : "reject")),
    );
    expect(d.verdict).toBe("ipv6_localhost_trap");
    expect(d.detail).toBe("http://127.0.0.1:8000");
  });

  it("server up, credentialed call network-fails → cors_refused (never unreachable)", async () => {
    const d = await diagnoseConnection(
      "http://127.0.0.1:8000",
      "aop_x",
      fetchTable((_url, init) => (isProbe(init) ? "opaque" : "reject")),
    );
    expect(d.verdict).toBe("cors_refused");
  });

  it("server up, 401 → token_rejected with the server's own message", async () => {
    const d = await diagnoseConnection(
      "http://127.0.0.1:8000",
      "aop_x",
      fetchTable((_url, init) => (isProbe(init) ? "opaque" : 401)),
    );
    expect(d.verdict).toBe("token_rejected");
    expect(d.detail).toBe("status 401");
  });

  it("server up, 403 → scope_or_role_refused", async () => {
    const d = await diagnoseConnection(
      "http://127.0.0.1:8000",
      "aop_x",
      fetchTable((_url, init) => (isProbe(init) ? "opaque" : 403)),
    );
    expect(d.verdict).toBe("scope_or_role_refused");
  });

  it("server up, 200 → connected", async () => {
    const d = await diagnoseConnection(
      "http://127.0.0.1:8000",
      "aop_x",
      fetchTable((_url, init) => (isProbe(init) ? "opaque" : 200)),
    );
    expect(d.verdict).toBe("connected");
  });

  it("server up but erroring → server_error, not a network verdict", async () => {
    const d = await diagnoseConnection(
      "http://127.0.0.1:8000",
      "aop_x",
      fetchTable((_url, init) => (isProbe(init) ? "opaque" : 500)),
    );
    expect(d.verdict).toBe("server_error");
  });

  it("does not retry 127.0.0.1 for a non-localhost host", async () => {
    // The ::1 tripwire is a loopback-only heuristic; a down production host must not
    // be probed at a loopback address it has nothing to do with.
    const urls: string[] = [];
    const d = await diagnoseConnection(
      "https://app.qanry.com",
      "aop_x",
      fetchTable((url) => {
        urls.push(url);
        return "reject";
      }),
    );
    expect(d.verdict).toBe("server_unreachable");
    expect(urls.some((u) => u.includes("127.0.0.1"))).toBe(false);
  });
});
