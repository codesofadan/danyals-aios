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
  acknowledged,
  onAcknowledgedChange,
}: {
  clientId?: string;
  /** Selected platform keys (enum name, falling back to row name). One entry in single mode. */
  selected: ReadonlySet<string>;
  onToggle: (platformKey: string) => void;
  /** Rendered under a non-empty grid — the caller's selection summary. */
  hint?: (eligibleCount: number) => React.ReactNode;
  /** Rendered when the client has zero eligible platforms. */
  emptyEligibleHint?: React.ReactNode;
  /** Whether the operator has accepted the advisories on their current selection. */
  acknowledged?: boolean;
  onAcknowledgedChange?: (next: boolean) => void;
}) {
  const boardQ = useWeb2PlatformBoard(clientId || undefined);
  const board: Web2PlatformStatusRow[] = boardQ.data ?? [];

  // WHO MAY BE PICKED. Two states are facts about the machine and can never be chosen:
  // `not_connected` (no credential) and `not_supported` (no publisher). The other two
  // are JUDGEMENTS about fit — a topical mismatch or an unread terms page — and those
  // are the operator's call, so they sit IN the grid behind a warning badge and one
  // acknowledgement. This is what makes every platform the pipeline can drive reachable
  // for every client, instead of capping a normal client at four.
  const eligible = board.filter((r) => r.status === "eligible");
  const advisory = board.filter(
    (r) => r.status === "not_eligible" || r.status === "not_reviewed",
  );
  const selectable = [...eligible, ...advisory];
  const needsAccount = board.filter((r) => r.status === "not_connected");
  const notSupported = board.filter((r) => r.status === "not_supported");
  const chosenAdvisories = advisory.filter((r) => selected.has(r.platform ?? r.name));

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
      {selectable.length === 0 ? (
        (emptyEligibleHint ?? (
          <div className="fld-hint" style={{ color: "var(--warn)" }}>
            No platform is currently available for this client. Connect an account below,
            then come back — a platform with no credential cannot publish, and that is
            the one thing an override cannot fix.
          </div>
        ))
      ) : (
        <div className="w2-plat-grid">
          {selectable.map((row) => {
            const key = row.platform ?? row.name;
            const on = selected.has(key);
            const meta = PLATFORM_META[key as Web2Platform];
            const flagged = PLATFORM_ISSUES[key as Web2Platform];
            const isAdvisory = row.status !== "eligible";
            return (
              <button
                type="button" key={key} onClick={() => onToggle(key)}
                className={`w2-plat${on ? " on" : ""}`} aria-pressed={on}
                title={isAdvisory ? row.reason : (flagged ?? undefined)}
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
                  {isAdvisory && (
                    <span style={{ color: "#92400e" }} title={row.reason}> ⚠</span>
                  )}
                </span>
                <span className="material-symbols-rounded w2-plat-check">
                  {on ? "check_circle" : "radio_button_unchecked"}
                </span>
              </button>
            );
          })}
        </div>
      )}
      {selectable.length > 0 && hint?.(selectable.length)}

      {/* The acknowledgement, shown ONLY for the advisory platforms actually chosen —
          each quoted with the platform's own rule, so the answer is informed rather
          than a habit. */}
      {chosenAdvisories.length > 0 && (
        <div
          className="fld-hint"
          style={{
            marginTop: 8, border: "1px solid #92400e", borderRadius: 6,
            padding: "10px 12px",
          }}
        >
          <b style={{ color: "#92400e" }}>
            {chosenAdvisories.length} platform(s) you chose carry their own warning for this client
          </b>
          <ul style={{ margin: "6px 0 8px 16px" }}>
            {chosenAdvisories.map((row) => (
              <li key={row.name} style={{ marginBottom: 4 }}>
                <b>{row.name}</b> — {row.reason}
                {row.termsSourceUrl && (
                  <>
                    {" "}
                    <a href={row.termsSourceUrl} target="_blank" rel="noopener noreferrer">
                      their terms
                    </a>
                  </>
                )}
              </li>
            ))}
          </ul>
          <label style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
            <input
              type="checkbox"
              checked={!!acknowledged}
              onChange={(e) => onAcknowledgedChange?.(e.target.checked)}
            />
            <span>
              I&rsquo;ve read these and I&rsquo;m choosing them for this client anyway.
            </span>
          </label>
        </div>
      )}

      {needsAccount.length > 0 && (
        <details className="fld-hint" style={{ marginTop: 8 }} open={eligible.length === 0}>
          <summary>
            {needsAccount.length} more platform(s) this client may use — connect an account
          </summary>
          <Web2SetupGuideList rows={needsAccount} />
        </details>
      )}

      {advisory.length > 0 && (
        <div className="fld-hint" style={{ marginTop: 8, opacity: 0.85 }}>
          {advisory.length} platform(s) in the grid are marked ⚠ — usable for this client,
          but their own rules argue against it. Hover one to read why; choosing it asks
          you to confirm.
        </div>
      )}

      {notSupported.length > 0 && (
        <div className="fld-hint" style={{ marginTop: 4, opacity: 0.75 }}>
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
