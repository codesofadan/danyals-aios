import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { readCredentials, storeCredentials } from "../src/lib/api";
import { ASSUMED_TTL_MS, maybeRotate } from "../src/lib/rotation";

/**
 * The rotation flow, against a fake `chrome.storage.local` and a fake fetch — the same
 * approach the other tests take: real module code, mocked platform edges.
 *
 * The properties that matter:
 *  - rotation only fires when the credential is actually short-lived (<2h left);
 *  - a successful rotation swaps token AND expiry in ONE storage write (a worker
 *    terminated mid-rotation must never leave a new token beside a stale expiry);
 *  - a 401 clears the credentials so the panel shows its re-pair state;
 *  - a transient failure keeps the still-valid token for the next alarm to retry.
 */

type Store = Record<string, unknown>;

function installFakeChrome(): { data: Store; setCalls: Store[] } {
  const data: Store = {};
  const setCalls: Store[] = [];
  const local = {
    get: async (keys: string[]): Promise<Store> => {
      const out: Store = {};
      for (const k of keys) if (k in data) out[k] = data[k];
      return out;
    },
    set: async (obj: Store): Promise<void> => {
      setCalls.push({ ...obj });
      Object.assign(data, obj);
    },
    remove: async (keys: string[]): Promise<void> => {
      for (const k of keys) delete data[k];
    },
  };
  (globalThis as { chrome?: unknown }).chrome = { storage: { local } };
  return { data, setCalls };
}

const NOW = 1_700_000_000_000;
const HOUR = 60 * 60 * 1000;

const rotatedBody = (token: string, expiresAtMs: number): string =>
  JSON.stringify({
    id: "tok-2",
    token,
    scopes: ["citation_queue:read", "citation_queue:write", "client_profile:read"],
    expiresAt: new Date(expiresAtMs).toISOString(),
    deviceLabel: "test device",
    installId: "inst-1",
    pairingExpiresAt: new Date(NOW + 20 * 24 * HOUR).toISOString(),
    apiBase: "http://127.0.0.1:8000",
    warning: "",
  });

describe("maybeRotate", () => {
  let fake: { data: Store; setCalls: Store[] };

  beforeEach(() => {
    fake = installFakeChrome();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("does nothing when the device is not paired", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    expect(await maybeRotate(NOW)).toBe("not_paired");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("does nothing while the token still has comfortable life left", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    await storeCredentials("aop_old_secret", "http://127.0.0.1:8000", NOW + 3 * HOUR);
    expect(await maybeRotate(NOW)).toBe("not_due");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("rotates when under two hours remain, swapping token and expiry atomically", async () => {
    const newExpiry = NOW + 12 * HOUR;
    const fetchSpy = vi.fn(
      async (url: string | URL, init?: RequestInit): Promise<Response> => {
        expect(String(url)).toBe("http://127.0.0.1:8000/api/v1/extension/tokens/rotate");
        const headers = (init?.headers ?? {}) as Record<string, string>;
        // The OLD token authenticates its own succession.
        expect(headers["X-Operator-Token"]).toBe("aop_old_secret");
        return new Response(rotatedBody("aop_new_secret", newExpiry), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      },
    );
    vi.stubGlobal("fetch", fetchSpy);

    await storeCredentials("aop_old_secret", "http://127.0.0.1:8000", NOW + 1 * HOUR);
    fake.setCalls.length = 0; // only the swap's writes matter below

    expect(await maybeRotate(NOW)).toBe("rotated");
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    const creds = await readCredentials();
    expect(creds?.token).toBe("aop_new_secret");
    expect(creds?.expiresAtMs).toBe(newExpiry);
    // ONE write carrying both keys — never a token write followed by an expiry write.
    expect(fake.setCalls).toHaveLength(1);
    expect(Object.keys(fake.setCalls[0]!).sort()).toEqual([
      "aios.operatorToken",
      "aios.tokenExpiresAt",
    ]);
  });

  it("treats a credential with no stored expiry as due now (legacy pairings)", async () => {
    const fetchSpy = vi.fn(
      async (): Promise<Response> =>
        new Response(rotatedBody("aop_new_secret", NOW + ASSUMED_TTL_MS), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
    );
    vi.stubGlobal("fetch", fetchSpy);
    await storeCredentials("aop_old_secret", "http://127.0.0.1:8000");
    expect(await maybeRotate(NOW)).toBe("rotated");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("clears credentials on a 401 so the panel shows the re-pair state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (): Promise<Response> => new Response("", { status: 401 })),
    );
    await storeCredentials("aop_old_secret", "http://127.0.0.1:8000", NOW + 1 * HOUR);
    expect(await maybeRotate(NOW)).toBe("unpaired");
    expect(await readCredentials()).toBeNull();
  });

  it("keeps the still-valid token on a transient failure and reports it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (): Promise<Response> => {
        throw new TypeError("Failed to fetch");
      }),
    );
    await storeCredentials("aop_old_secret", "http://127.0.0.1:8000", NOW + 1 * HOUR);
    expect(await maybeRotate(NOW)).toBe("failed");
    const creds = await readCredentials();
    expect(creds?.token).toBe("aop_old_secret");
    expect(creds?.expiresAtMs).toBe(NOW + 1 * HOUR);
  });
});
