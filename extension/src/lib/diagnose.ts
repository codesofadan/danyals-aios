/**
 * The connection diagnostic: turns fetch()'s single unhelpful "Failed to fetch" into a
 * verdict an operator can act on.
 *
 * The night this was written, pairing failed for THREE stacked reasons at once — the
 * server's CORS allowlist had no extension origin, the panel's default pointed at a
 * stale backend on another port, and `localhost` resolved to ::1 where the (IPv4-only)
 * server refuses connections. Every one of them rendered as the same two words. The
 * staged probe below separates them:
 *
 *   stage 1  `no-cors` GET — a *simple* request that resolves (opaquely) whenever ANY
 *            HTTP response comes back. A rejection here is the network layer itself:
 *            nothing listening, wrong port, wrong address family. No preflight, so CORS
 *            cannot be the thing that failed.
 *   stage 1b when the host was `localhost` and stage 1 failed, the same probe against
 *            `127.0.0.1` — succeeding there is the macOS ::1 trap, and the verdict
 *            carries the address that works.
 *   stage 2  the real credentialed call. It carries a custom header, so where the
 *            host-permission bypass does not apply Chrome preflights it; a network
 *            failure AFTER stage 1 succeeded is CORS (or a stale loaded build holding
 *            old permissions), never the server being down.
 *
 * Pure and injectable (fetch passed in) so it is testable without a browser.
 */

export type DiagnosisVerdict =
  | "connected"
  | "server_unreachable"
  | "ipv6_localhost_trap"
  | "cors_refused"
  | "token_rejected"
  | "scope_or_role_refused"
  | "server_error";

export type Diagnosis = {
  verdict: DiagnosisVerdict;
  /** The working address for ipv6_localhost_trap; the server's own message otherwise. */
  detail: string;
};

type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;

async function reachable(url: string, fetchFn: FetchLike): Promise<boolean> {
  try {
    // `no-cors` sends a simple request; the opaque response proves reachability even
    // when the server would refuse this origin. Any status counts — a 404 still means
    // a server answered.
    await fetchFn(url, { mode: "no-cors", cache: "no-store" });
    return true;
  } catch {
    return false;
  }
}

/** Pull the platform's error envelope message out of a response, best-effort. */
async function readDetail(response: Response): Promise<string> {
  try {
    const text = await response.text();
    try {
      const parsed = JSON.parse(text) as { error?: { message?: string } };
      return parsed.error?.message ?? text;
    } catch {
      return text;
    }
  } catch {
    return "";
  }
}

export async function diagnoseConnection(
  apiBase: string,
  token: string,
  fetchFn: FetchLike,
): Promise<Diagnosis> {
  const base = apiBase.trim().replace(/\/+$/, "");

  if (!(await reachable(`${base}/health`, fetchFn))) {
    // The ::1 tripwire: `localhost` resolves to ::1 first on macOS, and a server bound
    // to 127.0.0.1 refuses it. Retry the identical probe with the hostname swapped.
    try {
      const url = new URL(base);
      if (url.hostname === "localhost") {
        url.hostname = "127.0.0.1";
        if (await reachable(`${url.origin}/health`, fetchFn)) {
          return { verdict: "ipv6_localhost_trap", detail: url.origin };
        }
      }
    } catch {
      /* an unparseable base is simply unreachable */
    }
    return { verdict: "server_unreachable", detail: "" };
  }

  let response: Response;
  try {
    response = await fetchFn(`${base}/api/v1/citation-builder/queue`, {
      headers: { "X-Operator-Token": token || "aop_diagnostic_probe" },
      cache: "no-store",
    });
  } catch {
    return { verdict: "cors_refused", detail: "" };
  }

  if (response.status === 401) return { verdict: "token_rejected", detail: await readDetail(response) };
  if (response.status === 403) return { verdict: "scope_or_role_refused", detail: await readDetail(response) };
  if (!response.ok) return { verdict: "server_error", detail: await readDetail(response) };
  return { verdict: "connected", detail: "" };
}
