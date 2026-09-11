/**
 * The rotation lock. The server treats a rotated token coming back as theft and
 * revokes the whole install — by design (the plan pins it). So the CLIENT must never
 * race itself: a queue request must not read the old token from storage while the
 * rotate is consuming it. These tests drive the real api module against a fake
 * `chrome.storage.local` and a scripted `fetch`, and assert both directions of the
 * quiescence: requests wait for a rotation, and a rotation waits for requests.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

type Deferred = { promise: Promise<Response>; resolve: (r: Response) => void };

function deferred(): Deferred {
  let resolve!: (r: Response) => void;
  const promise = new Promise<Response>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

/** A minimal chrome.storage.local over a plain object. */
function fakeChrome(store: Record<string, unknown>): void {
  (globalThis as Record<string, unknown>).chrome = {
    storage: {
      local: {
        get: async (keys: string[]) => {
          const out: Record<string, unknown> = {};
          for (const k of keys) if (k in store) out[k] = store[k];
          return out;
        },
        set: async (items: Record<string, unknown>) => {
          Object.assign(store, items);
        },
        remove: async (keys: string[]) => {
          for (const k of keys) delete store[k];
        },
      },
    },
  };
}

async function loadApi() {
  vi.resetModules();
  return import("../src/lib/api");
}

const seeded = () => ({
  "aios.operatorToken": "aop_old_token",
  "aios.apiBase": "https://api.example",
  "aios.tokenExpiresAt": Date.now() + 60_000,
});

describe("the rotation lock", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("a request started during a rotation waits and then carries the SUCCESSOR token", async () => {
    const store = seeded();
    fakeChrome(store);
    const tokensSeen: string[] = [];
    const rotateGate = deferred();

    vi.stubGlobal("fetch", (url: string, init: RequestInit) => {
      const token = (init.headers as Record<string, string>)["X-Operator-Token"];
      tokensSeen.push(`${String(url).includes("/rotate") ? "rotate" : "board"}:${token}`);
      if (String(url).includes("/rotate")) return rotateGate.promise;
      return Promise.resolve(jsonResponse({ items: [] }));
    });

    const { api, swapToken, withRotationLock } = await loadApi();

    const rotation = withRotationLock(async () => {
      const rotated = await api.rotate();
      await swapToken(rotated.token, Date.now() + 60_000);
    });
    // Give the rotate fetch a tick to be issued, then start a board read: it must
    // NOT go out with the old token while the rotation is mid-swap.
    await new Promise((r) => setTimeout(r, 0));
    const board = api.board();
    await new Promise((r) => setTimeout(r, 0));
    expect(tokensSeen).toEqual(["rotate:aop_old_token"]);

    rotateGate.resolve(
      jsonResponse({ token: "aop_new_token", expiresAt: new Date().toISOString() }),
    );
    await rotation;
    await board;
    expect(tokensSeen).toEqual(["rotate:aop_old_token", "board:aop_new_token"]);
  });

  it("a rotation waits for an in-flight request to drain before consuming the token", async () => {
    const store = seeded();
    fakeChrome(store);
    const calls: string[] = [];
    const boardGate = deferred();

    vi.stubGlobal("fetch", (url: string) => {
      if (String(url).includes("/rotate")) {
        calls.push("rotate");
        return Promise.resolve(
          jsonResponse({ token: "aop_new_token", expiresAt: new Date().toISOString() }),
        );
      }
      calls.push("board");
      return boardGate.promise;
    });

    const { api, swapToken, withRotationLock } = await loadApi();

    const board = api.board();
    await new Promise((r) => setTimeout(r, 0));
    const rotation = withRotationLock(async () => {
      const rotated = await api.rotate();
      await swapToken(rotated.token, Date.now() + 60_000);
    });
    await new Promise((r) => setTimeout(r, 0));
    // The board request is still in flight: the rotate must not have started.
    expect(calls).toEqual(["board"]);

    boardGate.resolve(jsonResponse({ items: [] }));
    await board;
    await rotation;
    expect(calls).toEqual(["board", "rotate"]);
    expect(store["aios.operatorToken"]).toBe("aop_new_token");
  });
});
