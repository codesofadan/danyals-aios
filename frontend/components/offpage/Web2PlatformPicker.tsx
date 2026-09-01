"use client";

import { useWeb2PlatformBoard } from "@/lib/hooks/offpage";
import { PLATFORM_ISSUES, PLATFORM_META, type Web2Platform, type Web2PlatformStatusRow } from "@/lib/offpage";

/**
 * The per-client platform board, shared by "One property" and "New campaign".
 *
 * Both modals used to carry their own copy of this — the same grid, the same two
 * `<details>` lists, ~60 duplicated lines that had already drifted (the campaign grid
 * silently dropped the PLATFORM_ISSUES flag the single grid shows). One component, one
 * truth.
 *
 * The board is five-state and every state renders honestly:
 *  - eligible          -> the pickable grid
 *  - not_connected     -> "connect an account", with the setup guide attached
 *  - not_eligible      -> a REVIEWED exclusion, shown with its terms evidence + date
 *  - not_reviewed      -> nobody has read this platform's terms yet; a safe default,
 *                         named as such — never dressed up as a policy verdict
 *  - not_supported     -> catalogued build target, no publisher code yet
 */
export default function Web2PlatformPicker({
  clientId,
  selected,
  onToggle,
  hint,
  emptyEligibleHint,
}: {
  clientId?: string;
  /** Selected platform keys (enum name, falling back to row name). One entry in single mode. */
  selected: ReadonlySet<string>;
  onToggle: (platformKey: string) => void;
  /** Rendered under a non-empty grid — the caller's selection summary. */
  hint?: (eligibleCount: number) => React.ReactNode;
  /** Rendered when the client has zero eligible platforms. */
  emptyEligibleHint?: React.ReactNode;
}) {
  const boardQ = useWeb2PlatformBoard(clientId || undefined);
  const board: Web2PlatformStatusRow[] = boardQ.data ?? [];

  const eligible = board.filter((r) => r.status === "eligible");
  // Different problems, different lists. `not_connected` is a missing credential an
  // operator fixes in ten minutes; `not_eligible` is a reviewed judgement no credential
  // changes; `not_reviewed` is homework nobody has done; `not_supported` is unbuilt code.
  const needsAccount = board.filter((r) => r.status === "not_connected");
  const blocked = board.filter((r) => r.status === "not_eligible");
  const notReviewed = board.filter((r) => r.status === "not_reviewed");
  const notSupported = board.filter((r) => r.status === "not_supported");

  if (!clientId) {
    return <div className="fld-hint">Choose a client to see which platforms they may publish to.</div>;
  }
  if (boardQ.isLoading) {
    return <div className="fld-hint">Loading the platform board…</div>;
  }
  if (boardQ.isError) {
    return (
      <div className="fld-hint" style={{ color: "var(--warn)" }} role="alert">
        Couldn&apos;t load the platform board — {(boardQ.error as Error)?.message ?? "try again"}.
      </div>
    );
  }

  return (
    <>
      {eligible.length === 0 ? (
        (emptyEligibleHint ?? (
          <div className="fld-hint" style={{ color: "var(--warn)" }}>
            No platform is currently available for this client. Connect an account below,
            then come back — planning against an unavailable platform is refused by the
            server.
          </div>
        ))
      ) : (
        <div className="w2-plat-grid">
          {eligible.map((row) => {
            const key = row.platform ?? row.name;
            const on = selected.has(key);
            const meta = PLATFORM_META[key as Web2Platform];
            const flagged = PLATFORM_ISSUES[key as Web2Platform];
            return (
              <button
                type="button" key={key} onClick={() => onToggle(key)}
                className={`w2-plat${on ? " on" : ""}`} aria-pressed={on}
                title={flagged ?? undefined}
              >
                <span className="op-plat-ic" style={{ background: meta?.c ?? "#64748b" }}>
                  <span className="material-symbols-rounded" style={{ fontSize: 14 }}>
                    {meta?.icon ?? "public"}
                  </span>
                </span>
                <span className="w2-plat-name">
                  {row.name}
                  {/* A platform with a known live issue, flagged where it is CHOSEN —
                      it used to appear only on the status board, which nobody reads
                      while planning. */}
                  {flagged && <span style={{ color: "#92400e" }}> *</span>}
                </span>
                <span className="material-symbols-rounded w2-plat-check">
                  {on ? "check_circle" : "radio_button_unchecked"}
                </span>
              </button>
            );
          })}
        </div>
      )}
      {eligible.length > 0 && hint?.(eligible.length)}

      {needsAccount.length > 0 && (
        <details className="fld-hint" style={{ marginTop: 8 }} open={eligible.length === 0}>
          <summary>
            {needsAccount.length} more platform(s) this client may use — connect an account
          </summary>
          <Web2SetupGuideList rows={needsAccount} />
        </details>
      )}

      {blocked.length > 0 && (
        <details className="fld-hint" style={{ marginTop: 8 }}>
          <summary>{blocked.length} platform(s) not suitable for this client — reviewed, with reasons</summary>
          <ul style={{ margin: "8px 0 0 16px" }}>
            {blocked.map((row) => (
              <li key={row.name} style={{ marginBottom: 4 }}>
                <b>{row.name}</b> — {row.reason}
                {row.termsCheckedOn && (
                  <span style={{ opacity: 0.75 }}>
                    {" "}(terms read {row.termsCheckedOn}
                    {row.termsSourceUrl && (
                      <>
                        {", "}
                        <a href={row.termsSourceUrl} target="_blank" rel="noopener noreferrer">source</a>
                      </>
                    )})
                  </span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}

      {notReviewed.length > 0 && (
        <details className="fld-hint" style={{ marginTop: 8 }}>
          <summary>
            {notReviewed.length} platform(s) not yet reviewed — unusable by default, not by verdict
          </summary>
          <div style={{ margin: "8px 0 0 2px" }}>
            Nobody has read these platforms&rsquo; terms yet, so they stay off. Reviewing a
            platform&rsquo;s terms (and recording the result on the catalogue) is what would
            unlock or exclude it honestly.
          </div>
          <ul style={{ margin: "6px 0 0 16px" }}>
            {notReviewed.map((row) => (
              <li key={row.name}>{row.name}</li>
            ))}
          </ul>
        </details>
      )}

      {notSupported.length > 0 && (
        <div className="fld-hint" style={{ marginTop: 8, opacity: 0.75 }}>
          {notSupported.length} more catalogued platform(s) have no publisher built yet.
        </div>
      )}
    </>
  );
}

/** The per-platform setup guide list (where to sign up, what it costs, what blocks it,
 *  which token to fetch). Shared with the Accounts tab, where connecting is the JOB —
 *  the guides used to render only inside the two planning modals. */
export function Web2SetupGuideList({ rows }: { rows: Web2PlatformStatusRow[] }) {
  return (
    <ul style={{ margin: "8px 0 0 16px" }}>
      {rows.map((row) => (
        <li key={row.name} style={{ marginBottom: 8 }}>
          <b>{row.name}</b>
          {row.setupCost && !/^free/i.test(row.setupCost) && (
            <span style={{ color: "#92400e" }}> — {row.setupCost}</span>
          )}
          {row.setupBlocker && (
            <div style={{ color: "#92400e", marginTop: 2 }}>⚠ {row.setupBlocker}</div>
          )}
          {row.setupSteps && <div style={{ marginTop: 2 }}>{row.setupSteps}</div>}
          {row.setupUrl && (
            <div style={{ marginTop: 2 }}>
              <a href={row.setupUrl} target="_blank" rel="noopener noreferrer">
                {row.setupUrl}
              </a>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
