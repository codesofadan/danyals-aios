"use client";

import { useEffect, useState } from "react";
import { useSaveWeb2ClientIdentity, useWeb2ClientIdentity } from "@/lib/hooks/offpage";

/**
 * One client's standing publishing identity — set once, reused by every signup after.
 *
 * WHY THIS IS A PER-CLIENT RECORD AND NOT A FIELD ON EACH ACCOUNT. Building accounts
 * for 20-50 clients is not 20-50 repetitions of a form; it is one standing fact per
 * client that every platform signup then reuses: who the account is, where its
 * verification mail lands, and whether we can read that mailbox.
 *
 * WHY THE CLIENT'S OWN MAILBOX. Minting an alias per (platform, client) on one agency
 * catch-all gives every account a shared prefix, a shared client hash and a shared
 * registrant domain — so a platform that suspends ONE account can enumerate every other
 * client we run. Registering on the client's own domain removes that join entirely.
 */
function lines(value: string): string[] {
  return value.split("\n").map((l) => l.trim()).filter(Boolean).slice(0, 12);
}

export default function Web2ClientIdentityPanel({ clientId }: { clientId?: string }) {
  const q = useWeb2ClientIdentity(clientId);
  const save = useSaveWeb2ClientIdentity(clientId);

  const [handleBase, setHandleBase] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [imapHost, setImapHost] = useState("");
  const [imapUser, setImapUser] = useState("");
  const [imapPassword, setImapPassword] = useState("");
  const [proof, setProof] = useState("");
  const [uniqueData, setUniqueData] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  // Load the stored identity into the form whenever the client changes.
  useEffect(() => {
    const d = q.data;
    setHandleBase(d?.handleBase ?? "");
    setContactEmail(d?.contactEmail ?? "");
    setImapHost(d?.imapHost ?? "");
    setImapUser(d?.imapUser ?? "");
    setImapPassword("");
    setProof((d?.proofPoints ?? []).join("\n"));
    setUniqueData((d?.uniqueData ?? []).join("\n"));
    setError("");
    setSaved(false);
  }, [q.data, clientId]);

  if (!clientId) {
    return (
      <div className="fld-hint" style={{ margin: "10px 0" }}>
        Pick a client above to set the identity its accounts are created under.
      </div>
    );
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSaved(false);
    try {
      await save.mutateAsync({
        handleBase: handleBase.trim(),
        contactEmail: contactEmail.trim(),
        imapHost: imapHost.trim(),
        imapUser: imapUser.trim(),
        // Blank leaves any existing sealed password alone — the server treats an empty
        // field as "unchanged", so editing the handle cannot drop a working mailbox.
        ...(imapPassword.trim() ? { imapPassword: imapPassword.trim() } : {}),
        proofPoints: lines(proof),
        uniqueData: lines(uniqueData),
      });
      setImapPassword("");
      setSaved(true);
    } catch (err) {
      setError((err as Error)?.message ?? "Could not save the identity.");
    }
  }

  const ready = q.data?.mailboxReady;

  return (
    <details className="fld-hint" style={{ margin: "10px 0" }} open={!q.data?.contactEmail}>
      <summary style={{ cursor: "pointer" }}>
        Publishing identity for this client{" "}
        {q.data?.contactEmail ? (
          <span style={{ color: ready ? "var(--ok)" : "#92400e" }}>
            — {q.data.contactEmail}
            {ready ? " · mailbox readable" : " · mailbox not readable"}
          </span>
        ) : (
          <span style={{ color: "#92400e" }}>— not set</span>
        )}
      </summary>

      <form onSubmit={submit} style={{ marginTop: 10, display: "grid", gap: 10 }}>
        <div className="fld">
          <label>Handle base — the brand stem account names are built from</label>
          <input
            value={handleBase}
            onChange={(e) => setHandleBase(e.target.value)}
            placeholder="leedsdrainageco"
          />
          <div className="fld-hint">
            Type the client&rsquo;s brand. A generated handle carries a platform prefix and
            a hash of the client id — the two things that let one suspended account point
            to all the others.
          </div>
        </div>

        <div className="fld">
          <label>Client email — where platform verification mail is sent</label>
          <input
            value={contactEmail}
            onChange={(e) => setContactEmail(e.target.value)}
            placeholder="web@clientdomain.com"
          />
          <div className="fld-hint">
            Must be on the <b>client&rsquo;s own domain</b>. The agency catch-all is refused
            here: one shared domain is what turns a single ban into every client&rsquo;s ban.
          </div>
        </div>

        <div className="fld">
          <label>Mailbox access (optional) — lets us confirm signups for you</label>
          <div style={{ display: "grid", gap: 8, gridTemplateColumns: "1fr 1fr" }}>
            <input
              value={imapHost}
              onChange={(e) => setImapHost(e.target.value)}
              placeholder="imap.clientdomain.com"
              aria-label="IMAP host"
            />
            <input
              value={imapUser}
              onChange={(e) => setImapUser(e.target.value)}
              placeholder="web@clientdomain.com"
              aria-label="IMAP user"
            />
          </div>
          <input
            type="password"
            value={imapPassword}
            onChange={(e) => setImapPassword(e.target.value)}
            placeholder={
              q.data?.imapPasswordHeld ? "•••••••• (stored — leave blank to keep)" : "mailbox password"
            }
            aria-label="IMAP password"
            style={{ marginTop: 8 }}
          />
          <div className="fld-hint">
            With this, the account builder reads the confirmation email and finishes the
            signup itself. Without it, everything still works — you just click the
            confirmation link yourself.
          </div>
        </div>

        <div className="fld">
          <label>Proof &amp; first-hand experience — one per line</label>
          <textarea
            rows={3}
            value={proof}
            onChange={(e) => setProof(e.target.value)}
            placeholder={"Real projects, results, credentials.\ne.g. Cleared 400 drains in 2025\ne.g. 25-year workmanship warranty"}
          />
          <div className="fld-hint">
            Stored once per client. Every campaign grounds its articles against these, so
            you never retype them — a draft written without them holds at review with
            [NEEDS:] gaps and cannot publish.
          </div>
        </div>

        <div className="fld">
          <label>What only this client knows — one per line</label>
          <textarea
            rows={2}
            value={uniqueData}
            onChange={(e) => setUniqueData(e.target.value)}
            placeholder={"The insight nobody else can write.\ne.g. The named bottleneck was the real one 3 times in 10"}
          />
        </div>

        {error && (
          <div className="login-error" role="alert">
            <span className="material-symbols-rounded">error</span>
            {error}
          </div>
        )}
        {saved && !error && (
          <div className="fld-hint" style={{ color: "var(--ok)" }}>Identity saved.</div>
        )}

        <div>
          <button className="primary-btn" type="submit" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save identity"}
          </button>
        </div>
      </form>
    </details>
  );
}
