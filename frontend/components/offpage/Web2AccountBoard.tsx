"use client";

import { useState } from "react";

import {
  useCheckWeb2Account,
  useRegisterWeb2Account,
  useWeb2Accounts,
  useWeb2Catalog,
  useWeb2PlatformBoard,
} from "@/lib/hooks/offpage";
import type { Web2Account } from "@/lib/offpage";
import { Web2SetupGuideList } from "./Web2PlatformPicker";
import Web2ClientIdentityPanel from "./Web2ClientIdentityPanel";
import Web2AccountBuilder from "./Web2AccountBuilder";

/**
 * The connection board — which publishing accounts exist and whether they still work.
 *
 * Registering an account was CLI-only, which made onboarding an engineer's job. Worse,
 * an account counted as "connected" the moment its fields were non-empty: that proves
 * SHAPE, not validity, so a revoked token looked identical to a working one until a
 * campaign failed — after the drafting spend.
 *
 * Hence two separate columns, because they are two different claims:
 *   • Credential — every required field is present (a publisher can be built)
 *   • Platform   — the platform was ASKED and answered
 * A credential can be complete and still rejected, and showing one number would hide
 * exactly the case worth catching.
 */
export default function Web2AccountBoard({ clientId }: { clientId?: string }) {
  const q = useWeb2Accounts(clientId);
  const check = useCheckWeb2Account();
  const [results, setResults] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const accounts = q.data ?? [];

  async function verify(a: Web2Account) {
    setBusy(a.id);
    try {
      const r = await check.mutateAsync(a.id);
      const who = r.identity ? ` — signed in as ${r.identity}` : "";
      setResults((prev) => ({ ...prev, [a.id]: `${r.detail}${who}` }));
    } catch (e) {
      setResults((prev) => ({ ...prev, [a.id]: (e as Error)?.message ?? "check failed" }));
    } finally {
      setBusy(null);
    }
  }

  if (q.isLoading) return <div className="op-empty">Loading accounts…</div>;
  if (!accounts.length && !adding) {
    return (
      <div className="op-empty">
        <p style={{ margin: "0 0 10px" }}>
          No publishing accounts yet. Create the account on the platform by hand (once), then
          register it here — publishing then runs through the platform&rsquo;s API, with every
          article still approved by a lead (Tumblr requires that approval per post, by its own
          API licence).
        </p>
        <button className="op-act" onClick={() => setAdding(true)}>Register an account</button>
        <Web2ClientIdentityPanel clientId={clientId} />
        <Web2AccountBuilder clientId={clientId} />
        <ConnectGuides clientId={clientId} />
      </div>
    );
  }

  return (
    <div className="tbl-wrap">
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
        <button className="op-act" onClick={() => setAdding((v) => !v)}>
          {adding ? "Cancel" : "Register an account"}
        </button>
      </div>
      {adding && (
        <RegisterAccountForm clientId={clientId} onDone={() => setAdding(false)} />
      )}
      <Web2ClientIdentityPanel clientId={clientId} />
      <Web2AccountBuilder clientId={clientId} />
      <ConnectGuides clientId={clientId} />
      <table className="tbl op-tbl w2-ledger">
        <thead>
          <tr>
            <th>Platform</th>
            <th>Account</th>
            <th>Owner</th>
            <th>Credential</th>
            <th>Platform says</th>
            <th>Used</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {accounts.map((a) => (
            <tr key={a.id}>
              <td className="op-strong">{a.platform}</td>
              <td>
                <span>{a.handle || "—"}</span>
                {a.email && <span className="w2-sub">{a.email}</span>}
              </td>
              <td>
                {a.ownership === "house" ? (
                  <span className="status-pill warn">shared house</span>
                ) : (
                  <span className="status-pill ok">{a.client || "client-owned"}</span>
                )}
              </td>
              <td>
                {a.complete ? (
                  <span className="status-pill ok">complete</span>
                ) : (
                  <>
                    <span className="status-pill crit">incomplete</span>
                    {/* Name the missing fields: "incomplete" alone sends someone hunting. */}
                    <span className="w2-sub">needs {a.required.join(", ")}</span>
                  </>
                )}
              </td>
              <td>
                <HealthCell account={a} />
                {results[a.id] && <span className="w2-sub">{results[a.id]}</span>}
              </td>
              <td className="op-muted">{a.properties}/{a.maxProperties}</td>
              <td>
                <button
                  className="op-act"
                  disabled={busy === a.id}
                  onClick={() => void verify(a)}
                >
                  {busy === a.id ? "Checking…" : "Test connection"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="fld-hint" style={{ marginTop: 8 }}>
        <b>Credential</b> means every required field is present. <b>Platform says</b> means the
        platform was actually asked. <i>Unverified</i> is not a failure — it means nobody has
        checked yet, which is deliberately different from a platform rejecting the credential.
      </div>
    </div>
  );
}

/** The platforms this client could use but holds no account for, with the setup guide
 *  for each — ON the screen where connecting is the job. The guides used to render only
 *  inside the two planning modals, so the person sent here to "add an account" arrived
 *  with no instructions. */
function ConnectGuides({ clientId }: { clientId?: string }) {
  const boardQ = useWeb2PlatformBoard(clientId || undefined);
  const rows = (boardQ.data ?? []).filter((r) => r.status === "not_connected");
  if (!clientId) {
    return (
      <div className="fld-hint" style={{ margin: "8px 0" }}>
        Pick a client above to see which platforms they may use and the setup guide for each.
      </div>
    );
  }
  if (rows.length === 0) return null;
  return (
    <details className="fld-hint" style={{ margin: "8px 0" }}>
      <summary>
        {rows.length} platform(s) this client may use have no account yet — setup guides
      </summary>
      <Web2SetupGuideList rows={rows} />
    </details>
  );
}

function HealthCell({ account }: { account: Web2Account }) {
  const tone =
    account.health === "active" ? "ok"
    : account.health === "suspended" ? "crit"
    : account.health === "degraded" ? "warn"
    : "mut";
  const label =
    account.health === "active" ? "authenticates"
    : account.health === "suspended" ? "rejected"
    : account.health;
  return (
    <>
      <span className={`status-pill ${tone}`}>{label}</span>
      {account.checked && <span className="w2-sub">checked {account.checked}</span>}
    </>
  );
}


/**
 * Register one account. The credential fields are DECLARED PER PLATFORM by the backend
 * (`PLATFORM_CREDENTIAL_HINTS` mirrors the same map the publishers validate against), so
 * adding a platform needs no change here.
 *
 * The secret is typed once, posted once, and sealed server-side. It is never put in a
 * query cache, never echoed in a response, and a refusal names the RULE rather than the
 * value — an operator who pastes the wrong token should not see it read back to them.
 */
function RegisterAccountForm({
  clientId,
  onDone,
}: {
  clientId?: string;
  onDone: () => void;
}) {
  const register = useRegisterWeb2Account();
  const catalog = useWeb2Catalog();
  const shapes = catalog.data?.credentialFields ?? {};
  const [platform, setPlatform] = useState("");
  const [handle, setHandle] = useState("");
  const [email, setEmail] = useState("");
  const [cred, setCred] = useState<Record<string, string>>({});
  const [error, setError] = useState("");

  const fields = shapes[platform] ?? [];
  const ready = platform && handle.trim() && fields.every((f) => (cred[f] ?? "").trim());

  async function submit() {
    setError("");
    try {
      await register.mutateAsync({
        platform,
        ownership: clientId ? "per_client" : "house",
        clientId,
        handle: handle.trim(),
        email: email.trim(),
        maxProperties: 10,
        credential: cred,
      });
      setCred({});          // drop the secret from component state immediately
      onDone();
    } catch (e) {
      setError((e as Error)?.message ?? "registration failed");
    }
  }

  return (
    <div className="fld" style={{ border: "1px solid var(--line, #e5e7eb)", padding: 12, marginBottom: 12 }}>
      {/* Ownership is DERIVED from the selected client, and it decides which
          platforms the account can ever satisfy - a house account only matches a
          house-tier platform. Saying so here is what stops someone registering a
          WordPress.com login as "house" and being unable to explain why the
          platform still shows as not connected. */}
      <div className="fld-hint" style={{ marginBottom: 10 }}>
        {clientId
          ? "This account will be owned by the selected client (per-client), which is what most platforms require."
          : "This account will be house-owned and shared across clients. Only Telegra.ph accepts a house account — switch to a client above for any other platform."}
      </div>

      <label>Platform</label>
      <select value={platform} onChange={(e) => { setPlatform(e.target.value); setCred({}); }}>
        <option value="">Choose a platform…</option>
        {Object.keys(shapes).sort().map((p) => (
          <option key={p} value={p}>{p}</option>
        ))}
      </select>

      <label style={{ marginTop: 10 }}>Account name on the platform</label>
      <input value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="the real username" />
      <div className="fld-hint">
        A per-client handle may not contain the platform name or a long hex run — both are
        footprint tells that make a link network enumerable.
      </div>

      <label style={{ marginTop: 10 }}>Registration email</label>
      <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@clientdomain.com" />
      <div className="fld-hint">
        For a client account this must be the client&rsquo;s own domain, not the agency catch-all.
      </div>

      {platform && (
        <>
          <label style={{ marginTop: 10 }}>Credential</label>
          {fields.map((f) => (
            <input
              key={f}
              type="password"
              autoComplete="off"
              value={cred[f] ?? ""}
              placeholder={f}
              onChange={(e) => setCred((c) => ({ ...c, [f]: e.target.value }))}
              style={{ marginBottom: 6 }}
            />
          ))}
          <div className="fld-hint">
            Sealed with AES-256-GCM on arrival. It is never shown again, logged, or returned.
          </div>
        </>
      )}

      {error && (
        <div className="op-flash" style={{ position: "static", background: "#fee2e2", color: "#991b1b", marginTop: 8 }}>
          {error}
        </div>
      )}

      <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
        <button className="op-act" disabled={!ready || register.isPending} onClick={() => void submit()}>
          {register.isPending ? "Registering…" : "Register"}
        </button>
        <button className="op-act" onClick={onDone}>Cancel</button>
      </div>
    </div>
  );
}
