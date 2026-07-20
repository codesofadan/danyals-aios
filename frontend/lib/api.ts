// ============================================================
// AIOS · the fetch seam
// The single door between the dashboard and the FastAPI backend.
// Every screen reads/writes through `api.*` (usually wrapped in a
// TanStack Query hook). Responsibilities kept in ONE place:
//   • inject the bearer token (from localStorage, readable outside React)
//   • decode the backend error envelope { error: { type, message, request_id } }
//   • on 401 → clear the token and bounce to /login (no refresh route; ~1h TTL)
//   • flag a 503 (backend up, a dependency unconfigured) so a banner can show
// Bearer auth only — we NEVER send cookies.
// ============================================================

// Relative default → same-origin in dev via the next.config rewrite proxy (no CORS).
// Set to an absolute origin (e.g. https://api.example.com/api/v1) for cross-origin.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";
const TOKEN_KEY = "aios-token-v1";
// The auth session snapshot's storage key — owned by lib/auth.tsx (imports this
// constant rather than defining its own), so there is exactly ONE key string to
// keep in sync. MUST be cleared together with the token (see clearSession below):
// clearing only the token left a stale session snapshot behind, which made
// LoginForm's "already signed in" bounce fire on dead data — /admin → 401 →
// /login?expired=1 → stale session still says "signed in" → bounce back to
// /admin → 401 again → infinite loop.
export const SESSION_KEY = "aios-session-v1";

// The one place that fully clears auth state — used by BOTH a 401 (below) and a
// manual logout (lib/auth.tsx), so the token and the session snapshot can never
// drift out of sync again.
export function clearSession(): void {
  setToken(null);
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage unavailable — the in-memory token is already cleared */
  }
}

// --- token (module-level so the fetch layer can read it without a React hook) ---
let _token: string | null = null;

export function getToken(): string | null {
  if (_token !== null) return _token;
  if (typeof window === "undefined") return null;
  try {
    _token = window.localStorage.getItem(TOKEN_KEY);
  } catch {
    _token = null;
  }
  return _token;
}

export function setToken(token: string | null): void {
  _token = token;
  if (typeof window === "undefined") return;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable — the in-memory copy still carries the session */
  }
}

// --- errors -------------------------------------------------------------------
export class ApiError extends Error {
  readonly status: number;
  readonly type: string;
  readonly requestId: string;
  constructor(status: number, type: string, message: string, requestId: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.type = type;
    this.requestId = requestId;
  }
}

// A 503 means the API is reachable but a dependency (DB/Redis/a provider key) is
// not configured — a distinct, recoverable state worth its own banner.
export class BackendUnavailableError extends ApiError {}

async function decodeError(res: Response): Promise<ApiError> {
  let type = "http_error";
  let message = res.statusText || `Request failed (${res.status})`;
  let requestId = "";
  try {
    const data = (await res.json()) as { error?: { type?: string; message?: string; request_id?: string } };
    if (data?.error) {
      type = data.error.type ?? type;
      message = data.error.message ?? message;
      requestId = data.error.request_id ?? "";
    }
  } catch {
    /* non-JSON error body — keep the status-derived defaults */
  }
  return res.status === 503
    ? new BackendUnavailableError(res.status, type, message, requestId)
    : new ApiError(res.status, type, message, requestId);
}

// --- the request primitive ----------------------------------------------------
type FetchOptions = {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  // Login uses this: a wrong-password 401 must surface as "invalid credentials",
  // NOT trigger the session-expired redirect.
  noAuthRedirect?: boolean;
};

export async function apiFetch<T>(path: string, opts: FetchOptions = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, {
    method: opts.method ?? "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });

  if (res.status === 401) {
    if (opts.noAuthRedirect) throw await decodeError(res);
    // clearSession() (NOT setToken(null)): a 401 must clear BOTH the token AND the
    // session snapshot, or LoginForm re-hydrates the stale snapshot, fires its
    // "already signed in" bounce back to the dashboard, 401s again, and loops.
    clearSession();
    if (typeof window !== "undefined") window.location.assign("/login?expired=1");
    throw new ApiError(401, "unauthorized", "Your session expired. Please sign in again.", "");
  }

  if (!res.ok) throw await decodeError(res);

  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

// --- authenticated binary fetch ------------------------------------------------
// For bearer-protected file endpoints (audit report.pdf / findings.json, client
// deliverables) that JSON `apiFetch` can't serve. Shared by downloadFile/openFile
// below; never caches the bytes.
async function fetchAuthedBlob(path: string): Promise<Blob> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (res.status === 401) {
    // Full clear (token + session snapshot) — same anti-loop reason as apiFetch above.
    clearSession();
    if (typeof window !== "undefined") window.location.assign("/login?expired=1");
    throw new ApiError(401, "unauthorized", "Your session expired. Please sign in again.", "");
  }
  if (!res.ok) throw await decodeError(res);
  return res.blob();
}

// Streams the blob, triggers a browser download (forces save-as via filename), and
// revokes the object URL.
export async function downloadFile(path: string, filename?: string): Promise<void> {
  const blob = await fetchAuthedBlob(path);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  if (filename) a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Opens the blob in a new tab (no forced download attribute) — for a "View" action
// where the browser's native viewer (e.g. PDF) is preferable to a save prompt.
// Revokes the object URL after a delay long enough for the new tab to load it.
export async function openFile(path: string): Promise<void> {
  const blob = await fetchAuthedBlob(path);
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank", "noopener,noreferrer");
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

// --- verb helpers -------------------------------------------------------------
export const api = {
  get: <T>(path: string, signal?: AbortSignal) => apiFetch<T>(path, { signal }),
  post: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
    apiFetch<T>(path, { method: "POST", body, signal }),
  put: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
    apiFetch<T>(path, { method: "PUT", body, signal }),
  patch: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
    apiFetch<T>(path, { method: "PATCH", body, signal }),
  del: <T>(path: string, signal?: AbortSignal) => apiFetch<T>(path, { method: "DELETE", signal }),
};
