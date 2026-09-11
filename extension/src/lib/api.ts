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
const EXPIRES_KEY = "aios.tokenExpiresAt";

export class NeedsPairing extends Error {
  constructor(message = "This device is not paired, or its token has expired.") {
    super(message);
    this.name = "NeedsPairing";
  }
}

/** What the rotation endpoint returns: a successor token, shaped like a mint. */
export type RotatedToken = {
  id: string;
  token: string;
  scopes: string[];
  expiresAt: string;
  deviceLabel: string;
  installId: string;
  pairingExpiresAt: string;
  apiBase: string;
  warning: string;
};

/**
 * `chrome.storage.local`, and the honest note about it: this is PLAINTEXT ON DISK,
 * readable by anything with filesystem access to the browser profile. That is inherent
 * to an extension and cannot be engineered away here — it is exactly why the token is
 * scoped to the citation queue alone and expires in twelve hours. Do not "improve" the
 * TTL for convenience; the short life IS the mitigation for the storage medium.
 *
 * `expiresAtMs` rides beside the token so the rotation alarm can decide "how long does
 * this credential have left" without a network call. At pair time it is an ESTIMATE
 * (the operator pastes a raw token, which carries no expiry); every successful rotation
 * replaces it with the server's own timestamp.
 */
export async function readCredentials(): Promise<
  { token: string; base: string; expiresAtMs: number | null } | null
> {
  const got = await chrome.storage.local.get([TOKEN_KEY, BASE_KEY, EXPIRES_KEY]);
  const token = got[TOKEN_KEY] as string | undefined;
  const base = got[BASE_KEY] as string | undefined;
  const expiresAtMs = got[EXPIRES_KEY] as number | undefined;
  if (!token || !base) return null;
  return { token, base, expiresAtMs: Number.isFinite(expiresAtMs) ? (expiresAtMs as number) : null };
}

export async function storeCredentials(
  token: string,
  base: string,
  expiresAtMs?: number,
): Promise<void> {
  await chrome.storage.local.set({
    [TOKEN_KEY]: token,
    [BASE_KEY]: base.replace(/\/+$/, ""),
    ...(expiresAtMs !== undefined ? { [EXPIRES_KEY]: expiresAtMs } : {}),
  });
}

/**
 * The rotation swap: token and expiry land in ONE `set` call, so a worker terminated
 * mid-rotation can never leave the new token beside the old expiry (which would make
 * the alarm rotate again immediately) or the reverse.
 */
export async function swapToken(token: string, expiresAtMs: number): Promise<void> {
  await chrome.storage.local.set({ [TOKEN_KEY]: token, [EXPIRES_KEY]: expiresAtMs });
}

export async function clearCredentials(): Promise<void> {
  await chrome.storage.local.remove([TOKEN_KEY, BASE_KEY, EXPIRES_KEY]);
}

/**
 * Rotation quiescence. The server treats a rotated token coming back as THEFT and
 * revokes the whole install chain — by design, and that design must stay: a grace
 * window server-side would give a real thief a free replay. Which makes the CLIENT
 * responsible for never racing itself: a queue request that reads the old token just
 * before the rotate commits would arrive at the server as a "replay" and unpair a
 * legitimate operator mid-shift. So rotation takes an exclusive lock: it waits for
 * in-flight requests to drain, and new requests wait for the swap to finish.
 */
let inflight = 0;
let idleWaiters: Array<() => void> = [];
let rotationGate: Promise<void> | null = null;

function noteRequestDone(): void {
  inflight -= 1;
  if (inflight === 0) {
    const waiters = idleWaiters;
    idleWaiters = [];
    for (const wake of waiters) wake();
  }
}

function whenIdle(): Promise<void> {
  if (inflight === 0) return Promise.resolve();
  return new Promise((resolve) => idleWaiters.push(resolve));
}

/**
 * Run `fn` (the rotate call + the storage swap, together) exclusively: no other API
 * request is in flight while it runs, and none starts until it finishes.
 */
export async function withRotationLock<T>(fn: () => Promise<T>): Promise<T> {
  while (rotationGate) await rotationGate; // a concurrent rotation already runs
  let release!: () => void;
  rotationGate = new Promise<void>((resolve) => {
    release = resolve;
  });
  try {
    await whenIdle();
    return await fn();
  } finally {
    rotationGate = null;
    release();
  }
}

async function call<T>(
  path: string,
  init: RequestInit = {},
  opts: { insideRotation?: boolean } = {},
): Promise<T> {
  // Ordinary requests wait out an in-progress rotation so they never present the
  // predecessor token after its successor was minted (the false-theft race). The
  // rotate call itself runs INSIDE the lock and must not wait on it.
  if (!opts.insideRotation) {
    while (rotationGate) await rotationGate;
  }
  const creds = await readCredentials();
  if (!creds) throw new NeedsPairing();
  if (!opts.insideRotation) inflight += 1;
  try {
    return await performCall<T>(creds, path, init);
  } finally {
    if (!opts.insideRotation) noteRequestDone();
  }
}

async function performCall<T>(
  creds: { token: string; base: string },
  path: string,
  init: RequestInit = {},
): Promise<T> {

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
  /** Exchange the live token for its 12h successor. The presented token is consumed:
   *  replaying it afterwards revokes this whole install, by design. Callers wrap the
   *  rotate + `swapToken` pair in `withRotationLock` (see `maybeRotate`) so no other
   *  request can race the swap and trip the server's theft response. */
  rotate: () =>
    call<RotatedToken>(
      "/extension/tokens/rotate",
      { method: "POST", body: "{}" },
      { insideRotation: true },
    ),
  board: () => call<unknown>("/citation-builder/queue"),
  claim: () => call<unknown>("/citation-builder/queue/claim", { method: "POST", body: "{}" }),
  item: (id: string) => call<unknown>(`/citation-builder/queue/${id}`),
  heartbeat: (id: string, workedSeconds: number) =>
    call<unknown>(`/citation-builder/queue/${id}/heartbeat`, {
      method: "POST",
      body: JSON.stringify({ workedSeconds }),
    }),
  complete: (
    id: string, liveUrl: string, workedSeconds: number, note: string, operatorConfirmed = false,
  ) =>
    call<unknown>(`/citation-builder/queue/${id}/complete`, {
      method: "POST",
      body: JSON.stringify({ liveUrl, workedSeconds, note, operatorConfirmed }),
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

  // --- operator sessions (0130). Same isolation rule: only the service worker calls
  // these; the panel asks over messages and renders what comes back. -------------
  /** Per-client session-able workload — the cheap counts read the client selector
   *  polls (requires citation_queue:read). */
  sessionClients: () => call<unknown>("/citation-builder/session-clients"),
  /** Start a session. kind 'citation' (default) pulls from this client's gaps;
   *  'web2_placement' (0136) pulls its parked extension-lane properties. Returns the
   *  session plus every task card; batch 1 arrives released (citations: with the
   *  lease already held server-side). */
  createSession: (clientId: string, limit: number, batchSize: number, kind = "citation") =>
    call<unknown>("/citation-builder/sessions", {
      method: "POST",
      body: JSON.stringify(
        kind === "web2_placement"
          ? { clientId, batchSize, kind }
          : { clientId, batchSize, kind, fromGaps: { limit } },
      ),
    }),
  /** The caller's own active sessions (summaries) — how a fresh browser adopts a
   *  server session that outlived the last one's storage. */
  myActiveSessions: () => call<unknown>("/citation-builder/sessions?mine=true&active=true"),
  getSession: (id: string) => call<unknown>(`/citation-builder/sessions/${id}`),
  sessionHeartbeat: (id: string, workedSeconds: number) =>
    call<unknown>(`/citation-builder/sessions/${id}/heartbeat`, {
      method: "POST",
      body: JSON.stringify({ workedSeconds }),
    }),
  closeSession: (id: string) =>
    call<unknown>(`/citation-builder/sessions/${id}/close`, { method: "POST", body: "{}" }),
  /** Forward-only, NON-terminal ui_state report. The server 409s a backwards or
   *  repeated move — callers treat that as "already known", never as an error. */
  taskTelemetry: (id: string, taskId: string, uiState: string) =>
    call<unknown>(`/citation-builder/sessions/${id}/tasks/${taskId}/telemetry`, {
      method: "POST",
      body: JSON.stringify({ uiState }),
    }),
  skipTask: (id: string, taskId: string, reason: string) =>
    call<unknown>(`/citation-builder/sessions/${id}/tasks/${taskId}/skip`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  deferTask: (id: string, taskId: string) =>
    call<unknown>(`/citation-builder/sessions/${id}/tasks/${taskId}/defer`, {
      method: "POST",
      body: "{}",
    }),

  // --- web2 placement (0136). Same isolation rule: only the service worker calls
  // these; the panel asks over messages and renders what comes back. --------------
  /** Block a WEB2 placement task (closed vocabulary, task-only - the property stays
   *  parked). Citation tasks must go through `blocked` (the queue door) instead. */
  blockPlacementTask: (id: string, taskId: string, reason: string, detail: string) =>
    call<unknown>(`/citation-builder/sessions/${id}/tasks/${taskId}/blocked`, {
      method: "POST",
      body: JSON.stringify({ reason, detail }),
    }),
  /** Hand the server the PUBLIC URL of a post the operator just published. The
   *  server fetches it itself (host-pinned to the platform + link check); a refusal
   *  comes back `accepted:false` and nothing advances. */
  completePlacement: (web2Id: string, url: string) =>
    call<unknown>(`/offpage/web2/placements/${web2Id}/complete`, {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
};
