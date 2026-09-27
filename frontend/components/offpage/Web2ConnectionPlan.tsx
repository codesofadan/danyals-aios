"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  useSaveWeb2ClientIdentity,
  useWeb2ClientIdentity,
  useWeb2ConnectionPlan,
} from "@/lib/hooks/offpage";
import type { Web2PlatformConnection, Web2Readiness } from "@/lib/offpage";

/**
 * ONE login per client, and an honest account of what it reaches.
 *
 * THE SCREEN THIS REPLACES. A grid of cards that all say "Connect" tells an operator
 * nothing about which of fifty platforms is one click away and which needs a paid API
 * tier — so a client sits at four connected platforms indefinitely and nobody can say
 * why. This answers with a NUMBER, and for every platform that is not ready, the one
 * action that would make it ready.
 *
 * WHY THE HEADLINE IS NOT A YES/NO. The agency enters a single username and password
 * per client, and that is genuinely how the client's identity works — but a password
 * publishes DIRECTLY on 8 of the 53 adapters. 43 need an OAuth grant or a personal
 * access token that no password substitutes for. Rendering those as "connected"
 * because a credential exists would promise a capability the system does not have, and
 * the operator would discover it one failed publish at a time. So the three buckets are
 * three genuinely different situations and are never merged:
 *
 *   ready     — publishes now, nothing left to do
 *   one_step  — ONE named human action away (sign in, generate an app password)
 *   blocked   — no usable API at all; procurement, not a click
 *
 * The password is WRITE-ONLY here. It travels in the save body, is sealed into the
 * vault under `<client_id>:web2-login`, and is never read back — the screen only ever
 * learns WHETHER one is held, which it gets from a vault label rather than by opening
 * the vault.
 */

const READINESS_META: Record<Web2Readiness, { label: string; cls: string; icon: string }> = {
  ready: { label: "Publishes now", cls: "ok", icon: "check_circle" },
  one_step: { label: "One step away", cls: "warn", icon: "key" },
  blocked: { label: "No usable API", cls: "mut", icon: "block" },
};

const GROUPS: { key: Web2Readiness; title: string; blurb: string }[] = [
  {
    key: "ready",
    title: "Publishes now",
    blurb:
      "This client's login is enough on its own. Pick these in the composer and the article goes out through the platform's own API.",
  },
  {
    key: "one_step",
    title: "One step away",
    blurb:
      "Each of these needs exactly one human action, named on the row. Do it once per client and the platform moves up to “Publishes now”.",
  },
  {
    key: "blocked",
    title: "No usable API",
    blurb:
      "Nothing an operator can do today — these need a developer app, a paid tier, or an approval we do not have. Listed so nobody spends an afternoon looking for the button.",
  },
];

export default function Web2ConnectionPlan({ clientId }: { clientId?: string }) {
  const identityQ = useWeb2ClientIdentity(clientId);
  const planQ = useWeb2ConnectionPlan(clientId);
  const save = useSaveWeb2ClientIdentity(clientId);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [reveal, setReveal] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [open, setOpen] = useState<Web2Readiness | null>("one_step");

  const identity = identityQ.data;
  const passwordHeld = !!identity?.passwordHeld;

  // WHY THIS IS NOT ONE `useEffect([identity, clientId])`.
  //
  // The obvious version — re-seed the form from `identity` whenever it changes — loses
  // the operator's typing. The form mounts and is usable immediately; the fetch lands a
  // moment later and its effect runs AFTER the render that showed the empty box. Anyone
  // who started typing a username in that window has it silently replaced by the stored
  // one, and the only signal is their own text vanishing mid-word. It also fires again
  // on any later refetch of the identity query.
  //
  // So: a client switch clears the form outright (a different client's credential must
  // never be sitting in the box), and the stored value hydrates it exactly ONCE per
  // client — and never over something already typed.
  const hydratedFor = useRef<string | null>(null);
  const dirty = useRef(false);

  useEffect(() => {
    hydratedFor.current = null;
    dirty.current = false;
    setUsername("");
    setPassword("");
    setReveal(false);
    setError("");
    setSaved("");
  }, [clientId]);

  useEffect(() => {
    if (!identity || dirty.current || hydratedFor.current === clientId) return;
    hydratedFor.current = clientId ?? null;
    // The username only. The password is never sent to this screen, so an empty box
    // next to "a password is sealed" is the honest rendering of write-only.
    setUsername(identity.username ?? "");
  }, [identity, clientId]);

  const byReadiness = useMemo(() => {
    const map: Record<Web2Readiness, Web2PlatformConnection[]> = {
      ready: [], one_step: [], blocked: [],
    };
    for (const row of planQ.data?.platforms ?? []) {
      (map[row.readiness] ?? map.blocked).push(row);
    }
    return map;
  }, [planQ.data]);

  if (!clientId) {
    return (
      <div className="op-empty">
        Choose a client above to see what their login reaches. Publishing access is a
        per-client fact — the agency holds one username and password for each client, and
        every platform that can authenticate with it uses that one.
      </div>
    );
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSaved("");
    if (!username.trim() && !password) {
      setError("Enter the username, the password, or both.");
      return;
    }
    save.mutate(
      // BLANK IS NOT CLEAR. A form that round-trips an empty password field must not
      // silently drop the credential that unlocks every platform this client is on, so
      // the field is only sent when the operator actually typed one. Clearing it is a
      // separate, deliberate button.
      { username: username.trim(), ...(password ? { password } : {}) },
      {
        onSuccess: () => {
          setPassword("");
          setReveal(false);
          setSaved(
            password
              ? "Saved — the password is sealed in the vault and will not be shown again."
              : "Saved.",
          );
        },
        onError: (err) => setError((err as Error)?.message ?? "Could not save."),
      },
    );
  }

  function clearPassword() {
    setError("");
    setSaved("");
    save.mutate(
      { clearPassword: true },
      {
        onSuccess: () => setSaved("The stored password was removed."),
        onError: (err) => setError((err as Error)?.message ?? "Could not clear it."),
      },
    );
  }

  const plan = planQ.data;

  return (
    <div style={{ marginTop: 14 }}>
      {/* --- the one login ------------------------------------------------- */}
      <form className="wiz-creds" onSubmit={submit} style={{ marginTop: 0 }}>
        <div className="wiz-creds-h">
          <span className="material-symbols-rounded" aria-hidden="true">key</span>
          <div>
            <div className="wiz-creds-t">This client&apos;s publishing login</div>
            <div className="wiz-creds-s">
              One username and one password, used as this client&apos;s identity on every
              platform. Entered once here; the password is sealed in the vault and is
              never displayed again — not on this screen and not in any report.
            </div>
          </div>
        </div>

        <div
          style={{
            display: "grid", gap: 10, marginTop: 12,
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          }}
        >
          <div className="fld">
            <label htmlFor="w2-login-user">Username</label>
            <input
              id="w2-login-user"
              value={username}
              onChange={(e) => { dirty.current = true; setUsername(e.target.value); }}
              placeholder="leedsdrainageco"
              autoComplete="off"
            />
          </div>
          <div className="fld">
            <label htmlFor="w2-login-pass">
              Password{" "}
              {passwordHeld && (
                <span className="status-pill ok" style={{ marginLeft: 6 }}>
                  <span className="material-symbols-rounded op-pill-ic" aria-hidden="true">lock</span>
                  Sealed
                </span>
              )}
            </label>
            <input
              id="w2-login-pass"
              type={reveal ? "text" : "password"}
              value={password}
              onChange={(e) => { dirty.current = true; setPassword(e.target.value); }}
              placeholder={passwordHeld ? "•••••••• — leave blank to keep it" : "Set a password"}
              autoComplete="new-password"
            />
            <div className="fld-hint">
              {passwordHeld
                ? "Leaving this blank keeps the sealed password. Typing a new one replaces it."
                : "Stored in the vault, not in the database — no column ever holds it."}
            </div>
          </div>
        </div>

        <div className="op-toolset" style={{ gap: 8, marginTop: 10, flexWrap: "wrap" }}>
          <button type="submit" className="primary-btn" disabled={save.isPending}>
            <span className="material-symbols-rounded" aria-hidden="true">save</span>
            {save.isPending ? "Saving…" : "Save login"}
          </button>
          {password && (
            <button type="button" className="ghostbtn" onClick={() => setReveal((r) => !r)}>
              <span className="material-symbols-rounded" aria-hidden="true">
                {reveal ? "visibility_off" : "visibility"}
              </span>
              {reveal ? "Hide" : "Show"} what I typed
            </button>
          )}
          {passwordHeld && (
            // CLEARING IS EXPLICIT, and deliberately not a blank field: an accidental
            // empty box must never be the thing that revokes a client's access to every
            // platform they are on.
            <button
              type="button" className="ghostbtn" onClick={clearPassword} disabled={save.isPending}
            >
              <span className="material-symbols-rounded" aria-hidden="true">key_off</span>
              Remove the stored password
            </button>
          )}
        </div>
        {error && <div className="note bad" style={{ marginTop: 10 }}>{error}</div>}
        {saved && !error && (
          <div className="fld-hint" style={{ marginTop: 10, color: "var(--ok)" }}>{saved}</div>
        )}
      </form>

      {/* --- what it reaches ----------------------------------------------- */}
      {planQ.isLoading && <div className="op-empty">Working out what this login reaches…</div>}
      {planQ.isError && !planQ.isLoading && (
        <div className="note bad" style={{ marginTop: 14 }}>
          Couldn&apos;t read the connection plan — {(planQ.error as Error)?.message ?? "try again"}.
        </div>
      )}

      {plan && (
        <>
          <div className="op-stat-row" style={{ display: "flex", gap: 10, flexWrap: "wrap", margin: "16px 0 6px" }}>
            {GROUPS.map((g) => {
              const count =
                g.key === "ready" ? plan.readyCount
                : g.key === "one_step" ? plan.oneStepCount
                : plan.blockedCount;
              const meta = READINESS_META[g.key];
              return (
                <button
                  key={g.key}
                  type="button"
                  onClick={() => setOpen(open === g.key ? null : g.key)}
                  className={`chip${open === g.key ? " on" : ""}`}
                  style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 14px" }}
                  aria-expanded={open === g.key}
                  // The visible text is a bold number next to a label, which concatenates
                  // to "23Publishes now" with no separator for a screen reader — the gap
                  // between them is flex spacing, not a space. Stating the name outright
                  // is how it reads as a sentence rather than a run-on.
                  aria-label={`${count} ${g.title}`}
                >
                  <span className="material-symbols-rounded" aria-hidden="true" style={{ fontSize: 18 }}>
                    {meta.icon}
                  </span>
                  <b style={{ fontSize: 17 }}>{count}</b>
                  <span>{g.title}</span>
                </button>
              );
            })}
          </div>

          <div className="fld-hint" style={{ marginBottom: 10 }}>{plan.summary}</div>

          {plan.notes.map((note, i) => (
            <div key={i} className="note" style={{ marginBottom: 8 }}>{note}</div>
          ))}

          {GROUPS.filter((g) => open === g.key).map((g) => {
            const rows = byReadiness[g.key];
            return (
              <div key={g.key} style={{ marginTop: 6 }}>
                <div className="fld-hint" style={{ marginBottom: 8 }}>{g.blurb}</div>
                {rows.length === 0 ? (
                  <div className="op-empty">No platform is in this state for this client.</div>
                ) : (
                  <div className="tbl-wrap">
                    <table className="tbl op-tbl">
                      <thead>
                        <tr>
                          <th>Platform</th>
                          <th>State</th>
                          <th>{g.key === "one_step" ? "The one thing to do" : "Why"}</th>
                          <th>Still needs</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((row) => {
                          const meta = READINESS_META[row.readiness];
                          return (
                            <tr key={row.platform}>
                              <td className="op-strong">{row.platform}</td>
                              <td>
                                <span className={`status-pill ${meta.cls}`}>
                                  <span className="material-symbols-rounded op-pill-ic" aria-hidden="true">
                                    {meta.icon}
                                  </span>
                                  {meta.label}
                                </span>
                              </td>
                              <td>{row.action || row.reason || <span className="op-muted">—</span>}</td>
                              <td>
                                {row.missing.length === 0 ? (
                                  <span className="op-muted">nothing</span>
                                ) : (
                                  <span className="op-anchor">{row.missing.join(", ")}</span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}
