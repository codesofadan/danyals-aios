"use client";

/**
 * The Web 2.0 readiness board — WHAT EACH LANE ACTUALLY NEEDS before it can publish.
 *
 * WHY THIS WAS REWRITTEN (2026-09-12). The previous board read `/citation-builder/
 * web2-status`, which is the pre-R2-06 view of the world, and it was wrong in three
 * ways that all pointed the operator at work that no longer exists:
 *
 *  1. It listed **54** platforms from a hard-coded tuple. The catalogue holds **90**,
 *     classified by `0135` into four lanes, and the lane is the whole question: an
 *     `extension` platform needs no credential at all, and an `unsupported` one is not
 *     a placement target. Rendering all of them as identical "credential slots" told
 *     the operator to go and find tokens for platforms we will never publish to, and
 *     hid the fact that a third of the catalogue is ready to work by hand today.
 *  2. Its instruction was `"Seal a per-client vault row (web2:<platform>) …"` — the
 *     `seed_web2_vault` model **R2-06 deleted**, because copying one house login into
 *     every client's row made one suspension everyone's outage and made the clients
 *     mutually identifiable. An account is now a `web2_accounts` row whose credential
 *     is sealed ONCE under `label = <account id>`.
 *  3. It counted `vault_keys` rows. The account is the unit now: a vault row whose
 *     account was retired is not a connection, and a vault row says nothing about
 *     ownership, handle, or health — the three things that decide whether a platform
 *     can actually be used for a given client.
 *
 * So this board is built from the two endpoints that DO model the current world:
 * `/offpage/web2/catalog` (90 rows, with mechanism and each platform's credential
 * shape) and `/offpage/web2/accounts` (what is really registered). Nothing here is
 * hard-coded: adding a platform or reclassifying a lane changes this screen with no
 * frontend edit.
 *
 * THE HONESTY RULE IT KEEPS. A lane's readiness is never rendered as a bare
 * percentage. "0 of 50" and "not yet assessed" are different facts, and a platform
 * whose adapter exists but has no account is a different problem from one we have
 * decided not to use — so each lane says which of those it is, in words.
 */

import { useMemo } from "react";

import { useWeb2Accounts, useWeb2Catalog } from "@/lib/hooks/offpage";
import {
  MECHANISM_META,
  type Web2Account,
  type Web2CatalogPlatform,
  type Web2Mechanism,
} from "@/lib/offpage";
import w from "./Wave4.module.css";

/** The lanes, in the order an operator should read them: what publishes itself, what
 *  they can work today, what is manual, what is off the table. */
const LANE_ORDER: Web2Mechanism[] = ["api", "extension", "human", "unsupported", ""];

/** What each lane needs before a placement can happen. This is the sentence the old
 *  board could not write, because it did not know the lane. */
const LANE_NEEDS: Record<Web2Mechanism, { needs: string; gate: string }> = {
  api: {
    needs:
      "A registered account per platform, with its credential sealed once. Publishing " +
      "then runs through the platform's own API behind a lead's approval.",
    gate: "account",
  },
  extension: {
    needs:
      "No credential and no account here — the operator publishes in their own " +
      "logged-in session from the extension's Web 2.0 tab and pastes the public URL " +
      "back. The server verifies the host and the link before anything moves.",
    gate: "operator",
  },
  human: {
    needs:
      "Manual placement start to finish; there is no adapter and no assisted lane. " +
      "Use these only when a specific client genuinely warrants the time.",
    gate: "manual",
  },
  unsupported: {
    needs:
      "Not a placement target. Kept in the catalogue so it is visibly excluded rather " +
      "than quietly missing — the reason is on each row.",
    gate: "excluded",
  },
  "": {
    needs:
      "Not yet classified into a lane, so nothing can be promised about it. It needs " +
      "a capability review before it is offered for a placement.",
    gate: "unclassified",
  },
};

type LaneRollup = {
  mechanism: Web2Mechanism;
  platforms: Web2CatalogPlatform[];
  /** Platforms in this lane that have at least one registered account. Only
   *  meaningful for the `api` lane — the others do not gate on an account. */
  withAccounts: number;
  accounts: number;
};

export default function Web2StatusBoard() {
  const catalogQ = useWeb2Catalog();
  const accountsQ = useWeb2Accounts();

  const catalog = catalogQ.data;
  const accounts: Web2Account[] = accountsQ.data ?? [];

  /** platform name -> its registered accounts. The account row is the unit of
   *  connection since R2-06, so this is what "connected" means now. */
  const accountsByPlatform = useMemo(() => {
    const map = new Map<string, Web2Account[]>();
    for (const a of accounts) {
      const list = map.get(a.platform) ?? [];
      list.push(a);
      map.set(a.platform, list);
    }
    return map;
  }, [accounts]);

  const lanes = useMemo<LaneRollup[]>(() => {
    if (!catalog) return [];
    const byLane = new Map<Web2Mechanism, Web2CatalogPlatform[]>();
    for (const p of catalog.platforms) {
      const list = byLane.get(p.mechanism) ?? [];
      list.push(p);
      byLane.set(p.mechanism, list);
    }
    return LANE_ORDER.filter((m) => (byLane.get(m)?.length ?? 0) > 0).map((m) => {
      const platforms = (byLane.get(m) ?? []).slice().sort((a, b) => a.name.localeCompare(b.name));
      let withAccounts = 0;
      let total = 0;
      for (const p of platforms) {
        const n = accountsByPlatform.get(p.name)?.length ?? 0;
        if (n > 0) withAccounts += 1;
        total += n;
      }
      return { mechanism: m, platforms, withAccounts, accounts: total };
    });
  }, [catalog, accountsByPlatform]);

  const apiLane = lanes.find((l) => l.mechanism === "api");

  if (catalogQ.isLoading) return <div className="op-muted">Loading the platform catalogue…</div>;
  if (catalogQ.isError || !catalog) {
    return (
      <div className="op-muted">
        Couldn&apos;t load the platform catalogue —{" "}
        {(catalogQ.error as Error)?.message ?? "try again"}. Nothing is shown rather than
        a guess at what is connected.
      </div>
    );
  }

  return (
    <div>
      {/* The rollup an operator needs first: how the catalogue divides, then the ONE
          number that decides whether the API lane can publish at all. */}
      <div className={w.rollup}>
        <span>
          <b>{catalog.total}</b> platforms ·{" "}
          {LANE_ORDER.filter((m) => (catalog.byMechanism?.[m] ?? 0) > 0)
            .map((m) => `${catalog.byMechanism[m]} ${MECHANISM_META[m].label.toLowerCase()}`)
            .join(" · ")}
        </span>
        <span>
          <b>{catalog.automationReady}</b> with a working adapter
        </span>
      </div>

      {apiLane && (
        <div
          className="op-flash"
          style={{
            position: "static",
            display: "block",
            marginBottom: 12,
            ...(apiLane.withAccounts === 0
              ? { background: "#fef3c7", color: "#92400e" }
              : {}),
          }}
        >
          <b>
            {apiLane.withAccounts} of {apiLane.platforms.length} API platforms have a
            registered account
          </b>
          {apiLane.withAccounts === 0 ? (
            <div style={{ marginTop: 4 }}>
              Nothing can publish through the API lane yet. An account is created on the
              platform by hand once, then registered under <b>Accounts</b> — its
              credential is sealed there and never read back. The extension lane below
              needs none of this and can be worked today.
            </div>
          ) : (
            <div style={{ marginTop: 4 }}>
              {apiLane.accounts} account(s) registered. A complete credential proves
              shape, not validity — press <b>Check</b> on an account to ask the platform
              itself.
            </div>
          )}
        </div>
      )}

      {accountsQ.isError && (
        <div className="op-muted" style={{ marginBottom: 10 }}>
          Couldn&apos;t load registered accounts — {(accountsQ.error as Error)?.message ?? "try again"}.
          Every platform below is shown as having none, which may understate what exists.
        </div>
      )}

      {lanes.map((lane) => (
        <Lane
          key={lane.mechanism || "unclassified"}
          lane={lane}
          accountsByPlatform={accountsByPlatform}
          accountsKnown={!accountsQ.isError && !accountsQ.isLoading}
          credentialFields={catalog.credentialFields ?? {}}
        />
      ))}

      <div className="op-muted" style={{ marginTop: 20 }}>
        Citation submission engines live on{" "}
        <a className="op-url" href="/admin/citations">the Citations page</a> under
        Automation — beside the earned-spec whitelist that governs them.
      </div>
    </div>
  );
}

function Lane({
  lane,
  accountsByPlatform,
  accountsKnown,
  credentialFields,
}: {
  lane: LaneRollup;
  accountsByPlatform: Map<string, Web2Account[]>;
  accountsKnown: boolean;
  credentialFields: Record<string, string[]>;
}) {
  const meta = MECHANISM_META[lane.mechanism];
  const needs = LANE_NEEDS[lane.mechanism];
  // Only the API lane is gated on a credential, so it is the only one opened by
  // default — the others are reference, and expanding all four buries the gate.
  const gatesOnAccount = needs.gate === "account";

  return (
    <details open={gatesOnAccount} style={{ marginBottom: 10 }}>
      <summary style={{ cursor: "pointer", padding: "6px 0" }}>
        <span className={`status-pill ${meta.cls}`}>{meta.label}</span>{" "}
        <b style={{ marginLeft: 6 }}>{lane.platforms.length} platform(s)</b>
        {gatesOnAccount && (
          <span className="op-muted" style={{ marginLeft: 8 }}>
            · {accountsKnown ? `${lane.withAccounts} connected` : "account state unknown"}
          </span>
        )}
      </summary>

      <div className="op-muted" style={{ margin: "2px 0 10px" }}>
        {needs.needs}
      </div>

      <div className={w.board}>
        {lane.platforms.map((p) => {
          const mine = accountsByPlatform.get(p.name) ?? [];
          const fields = credentialFields[p.name] ?? [];
          return (
            <div key={p.id} className={w.card}>
              <div className={w.cardHead}>
                <span className={w.cardName}>{p.name}</span>
                {gatesOnAccount ? (
                  <span
                    className={`status-pill ${
                      !accountsKnown ? "mut" : mine.length > 0 ? "ok" : "warn"
                    }`}
                  >
                    {!accountsKnown
                      ? "unknown"
                      : mine.length > 0
                        ? `${mine.length} account(s)`
                        : "no account"}
                  </span>
                ) : (
                  <span className={`status-pill ${meta.cls}`}>{meta.label}</span>
                )}
              </div>

              {/* The adapter fact and the LANE fact are separate: an adapter can exist
                  for a platform we have chosen not to use, and saying "ready" of it
                  would invite a placement the lane forbids. */}
              <div className={w.reason}>
                {p.automationReady
                  ? "Adapter built and shippable."
                  : "Adapter not marked ready — needs an auth or instance detail pinned down."}
                {p.authorityTier ? ` Authority: ${p.authorityTier}.` : ""}
              </div>

              {gatesOnAccount && (
                <div className={w.meta}>
                  Needs:{" "}
                  {fields.length > 0
                    ? fields.join(", ")
                    : "no credential fields published for this platform yet"}
                </div>
              )}

              {mine.length > 0 && (
                <div className={w.meta}>
                  {mine
                    .map(
                      (a) =>
                        `${a.ownership === "house" ? "house" : "per-client"} · ${a.handle}` +
                        (a.health ? ` · ${a.health}` : ""),
                    )
                    .join(" | ")}
                </div>
              )}

              {p.notes && <div className={w.external}>{p.notes}</div>}

              {p.signupUrl && gatesOnAccount && mine.length === 0 && (
                <div className={w.meta}>
                  <a
                    className="op-url"
                    href={p.signupUrl.startsWith("http") ? p.signupUrl : `https://${p.signupUrl}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Create the account
                    <span className="material-symbols-rounded">open_in_new</span>
                  </a>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </details>
  );
}
