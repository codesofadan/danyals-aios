/**
 * The API client. Lives in the SERVICE WORKER and nowhere else.
 *
 * That placement is the security design, not a detail. A content script shares a
 * renderer process with whatever JavaScript a directory serves; anything it can read, a
 * hostile page can eventually read too. So the content script never imports this file,
 * never learns the API base, and never sees the operator token — it receives a list of
 * selectors and values over `chrome.runtime.sendMessage` and returns an outcome.
 *
 * It also happens to sidestep CORS: a fetch issued from the service worker to a host in
 * `host_permissions` is made with extension privileges rather than being page-checked.
 */

const TOKEN_KEY = "aios.operatorToken";
const BASE_KEY = "aios.apiBase";

export class NeedsPairing extends Error {
  constructor(message = "This device is not paired, or its token has expired.") {
    super(message);
    this.name = "NeedsPairing";
  }
}

/**
 * `chrome.storage.local`, and the honest note about it: this is PLAINTEXT ON DISK,
 * readable by anything with filesystem access to the browser profile. That is inherent
 * to an extension and cannot be engineered away here — it is exactly why the token is
 * scoped to the citation queue alone and expires in twelve hours. Do not "improve" the
 * TTL for convenience; the short life IS the mitigation for the storage medium.
 */
export async function readCredentials(): Promise<{ token: string; base: string } | null> {
  const got = await chrome.storage.local.get([TOKEN_KEY, BASE_KEY]);
  const token = got[TOKEN_KEY] as string | undefined;
  const base = got[BASE_KEY] as string | undefined;
  return token && base ? { token, base } : null;
}

export async function storeCredentials(token: string, base: string): Promise<void> {
  await chrome.storage.local.set({ [TOKEN_KEY]: token, [BASE_KEY]: base.replace(/\/+$/, "") });
}

export async function clearCredentials(): Promise<void> {
  await chrome.storage.local.remove([TOKEN_KEY, BASE_KEY]);
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const creds = await readCredentials();
  if (!creds) throw new NeedsPairing();

  const response = await fetch(`${creds.base}/api/v1${path}`, {
    ...init,
    headers: {
      ...(init.headers ?? {}),
      // Its OWN header, never `Authorization`. The token is not a JWT, so presenting it
      // as a bearer would simply fail — and this way a paired extension can never be
      // confused with a dashboard session by anything reading the request.
      "X-Operator-Token": creds.token,
      ...(init.body ? { "Content-Type": "application/json" } : {}),
    },
  });

  if (response.status === 401) throw new NeedsPairing();
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  if (!response.ok) {
    let message = text;
    try {
      message = (JSON.parse(text) as { error?: { message?: string } }).error?.message ?? text;
    } catch {
      /* a non-JSON error body is still worth showing verbatim */
    }
    throw new Error(message || `Request failed (${response.status})`);
  }
  return text ? (JSON.parse(text) as T) : (undefined as T);
}

export const api = {
  board: () => call<unknown>("/citation-builder/queue"),
  claim: () => call<unknown>("/citation-builder/queue/claim", { method: "POST", body: "{}" }),
  item: (id: string) => call<unknown>(`/citation-builder/queue/${id}`),
  heartbeat: (id: string, workedSeconds: number) =>
    call<unknown>(`/citation-builder/queue/${id}/heartbeat`, {
      method: "POST",
      body: JSON.stringify({ workedSeconds }),
    }),
  complete: (id: string, liveUrl: string, workedSeconds: number, note: string) =>
    call<unknown>(`/citation-builder/queue/${id}/complete`, {
      method: "POST",
      body: JSON.stringify({ liveUrl, workedSeconds, note }),
    }),
  blocked: (id: string, reason: string, detail: string, workedSeconds: number) =>
    call<unknown>(`/citation-builder/queue/${id}/blocked`, {
      method: "POST",
      body: JSON.stringify({ reason, detail, workedSeconds }),
    }),
  release: (id: string, workedSeconds: number) =>
    call<unknown>(`/citation-builder/queue/${id}/release`, {
      method: "POST",
      body: JSON.stringify({ workedSeconds }),
    }),
};
