import { beforeEach, describe, expect, it } from "vitest";

import {
  clientSummary,
  clientsForLane,
  isLane,
  LANE_LABEL,
  LANES,
  laneToSessionKind,
  laneWorkCount,
  readLane,
  sessionKindToLane,
  writeLane,
} from "../src/lib/lanes";
import type { SessionClientCount } from "../src/lib/messages";

/**
 * The lane logic behind the Citation / Web 2.0 tabs.
 *
 * **THE MOST IMPORTANT TEST IN THIS FILE** is
 * `test an unreported backlog is null, never zero`.
 *
 * The panel renders a lane's backlog as a headline number. If a server that does not
 * report `web2Placements` produced `0`, the Web 2.0 tab would read "0 placement(s)
 * outstanding" — and an operator who trusts that stops opening the tab. The lane may
 * be full. That is the same error-vs-absence confusion the grid module encodes in a
 * CHECK constraint, restated for a number on a button: measured-and-empty and
 * never-measured must not render the same.
 *
 * The rest guard the two places the lane vocabulary crosses a boundary: the tab is
 * `web2`, the server's session kind is `web2_placement`, and confusing them starts a
 * citation session for an operator who asked for placements.
 */

type Store = Record<string, unknown>;

function stubStorage(initial: Store = {}, { broken = false } = {}): Store {
  const store: Store = { ...initial };
  (globalThis as any).chrome = {
    storage: {
      local: {
        get: async (key: string) => {
          if (broken) throw new Error("site data blocked");
          return key in store ? { [key]: store[key] } : {};
        },
        set: async (patch: Store) => {
          if (broken) throw new Error("site data blocked");
          Object.assign(store, patch);
        },
      },
    },
  };
  return store;
}

const client = (over: Partial<SessionClientCount> = {}): SessionClientCount => ({
  clientId: "c1",
  client: "Acme Dental",
  readyForHuman: 0,
  verifyFirst: 0,
  candidateGaps: 0,
  web2Placements: 0,
  ...over,
});

describe("a lane's backlog is honest about what was not reported", () => {
  it("an unreported backlog is null, never zero", () => {
    // A pre-0136 server sends no `web2Placements` at all. Delete it rather than
    // setting 0: 0 is a measurement, absence is not.
    const old = client({ readyForHuman: 4 }) as Partial<SessionClientCount>;
    delete old.web2Placements;

    expect(laneWorkCount("web2", [old as SessionClientCount])).toBeNull();
    // ...and the citation lane, whose fields ARE present, still reports its number.
    expect(laneWorkCount("citation", [old as SessionClientCount])).toBe(4);
  });

  it("a reported zero really is zero", () => {
    // The other half of the contract: a server that says "none" must not be shown as
    // unknown, or a genuinely empty lane would look like a reporting failure.
    expect(laneWorkCount("web2", [client({ web2Placements: 0 })])).toBe(0);
  });

  it("a mixed response still reports the rows that answered", () => {
    const silent = client({ clientId: "old" }) as Partial<SessionClientCount>;
    delete silent.web2Placements;
    const rows = [silent as SessionClientCount, client({ clientId: "new", web2Placements: 3 })];
    expect(laneWorkCount("web2", rows)).toBe(3);
  });

  it("no clients at all is unknown, not zero", () => {
    // An empty list means the fetch found nothing to ask about; the panel says so
    // separately ("no work yet"). Reporting 0 here would assert a measurement.
    expect(laneWorkCount("web2", [])).toBeNull();
    expect(laneWorkCount("citation", [])).toBeNull();
  });

  it("sums every citation state a session can pick up", () => {
    const rows = [
      client({ readyForHuman: 2, verifyFirst: 3, candidateGaps: 5 }),
      client({ clientId: "c2", readyForHuman: 1 }),
    ];
    expect(laneWorkCount("citation", rows)).toBe(11);
  });

  it("ignores a non-finite count rather than poisoning the total", () => {
    const bad = client({ web2Placements: Number.NaN });
    expect(laneWorkCount("web2", [bad])).toBeNull();
  });
});

describe("the lane picker offers the right clients", () => {
  it("hides clients with no work in THIS lane", () => {
    const rows = [
      client({ clientId: "cites", readyForHuman: 3 }),
      client({ clientId: "places", web2Placements: 2 }),
    ];
    expect(clientsForLane("citation", rows).map((c) => c.clientId)).toEqual(["cites"]);
    expect(clientsForLane("web2", rows).map((c) => c.clientId)).toEqual(["places"]);
  });

  it("KEEPS a client whose count was not reported", () => {
    // Hiding it would turn "we don't know" into "this client has nothing", which is
    // the null-vs-zero bug wearing a different hat: the operator loses the client
    // entirely instead of just losing the number.
    const silent = client({ clientId: "unknown" }) as Partial<SessionClientCount>;
    delete silent.web2Placements;
    expect(clientsForLane("web2", [silent as SessionClientCount])).toHaveLength(1);
  });

  it("describes a client in the vocabulary of the lane", () => {
    const c = client({ readyForHuman: 2, verifyFirst: 1, candidateGaps: 4, web2Placements: 6 });
    expect(clientSummary("citation", c)).toContain("2 ready");
    expect(clientSummary("citation", c)).not.toContain("placement");
    expect(clientSummary("web2", c)).toContain("6 placement(s)");
    expect(clientSummary("web2", c)).not.toContain("ready");
  });

  it("says a count was not reported instead of printing a number", () => {
    const silent = client() as Partial<SessionClientCount>;
    delete silent.web2Placements;
    expect(clientSummary("web2", silent as SessionClientCount)).toContain("not reported");
  });
});

describe("the tab vocabulary and the server's are kept apart", () => {
  it("maps the web2 tab to the session kind 0136 actually defined", () => {
    expect(laneToSessionKind("web2")).toBe("web2_placement");
    expect(laneToSessionKind("citation")).toBe("citation");
  });

  it("maps a session back to the tab that owns it", () => {
    expect(sessionKindToLane("web2_placement")).toBe("web2");
    expect(sessionKindToLane("citation")).toBe("citation");
    // Pre-0136 stored state has no kind; it was always a citation session.
    expect(sessionKindToLane(undefined)).toBe("citation");
  });

  it("round-trips every lane through the server's vocabulary", () => {
    for (const l of LANES) expect(sessionKindToLane(laneToSessionKind(l))).toBe(l);
  });

  it("names both lanes", () => {
    expect(LANES).toHaveLength(2);
    for (const l of LANES) expect(LANE_LABEL[l]).toBeTruthy();
  });
});

describe("the chosen tab survives the panel being closed", () => {
  beforeEach(() => stubStorage());

  it("defaults to citations when nothing was stored", async () => {
    await expect(readLane()).resolves.toBe("citation");
  });

  it("remembers the lane the operator picked", async () => {
    await writeLane("web2");
    await expect(readLane()).resolves.toBe("web2");
  });

  it("ignores a stored value that is not a lane", async () => {
    // A half-written or hand-edited storage entry must not render an empty board.
    stubStorage({ "aios.activeLane": "web3" });
    await expect(readLane()).resolves.toBe("citation");
  });

  it("survives storage being unavailable entirely", async () => {
    // A profile with site data blocked throws on every access. A tab preference is
    // not worth a broken panel.
    stubStorage({}, { broken: true });
    await expect(readLane()).resolves.toBe("citation");
    await expect(writeLane("web2")).resolves.toBeUndefined();
  });

  it("rejects non-lane values at the type guard", () => {
    expect(isLane("citation")).toBe(true);
    expect(isLane("web2")).toBe(true);
    expect(isLane("web2_placement")).toBe(false);
    expect(isLane(undefined)).toBe(false);
  });
});
