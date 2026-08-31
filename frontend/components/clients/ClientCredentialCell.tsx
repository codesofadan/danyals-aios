"use client";

import { useState } from "react";
import { copyText } from "@/lib/clipboard";
import { genPortalLogin, genPortalPassword } from "@/lib/portalCredentials";
import {
  useProvisionPortalLogin,
  useRevealPortalCredentials,
  useSetPortalPassword,
  type PortalCredentials,
} from "@/lib/hooks/clients";
import type { ClientRecord } from "@/lib/data";

function CopyBtn({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="cred-copy"
      title={`Copy ${label}`}
      onClick={async () => {
        try {
          await copyText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        } catch {
          /* clipboard blocked — no-op */
        }
      }}
    >
      <span className="material-symbols-rounded">{copied ? "check" : "content_copy"}</span>
    </button>
  );
}

/**
 * Reveal / repair a CLIENT's portal login, on demand.
 *
 * QA found two failures this closes. Clients could not sign in, because a login
 * that failed to provision left the client row behind with no credential and only
 * a dismissible warning. And an admin could not look one up, because the password
 * was believed unrecoverable — it never was: `provision_user` seals an
 * AES-256-GCM copy beside the argon2id hash, and nothing had ever read it back.
 *
 * Three states, all reachable:
 *   - a login with a captured password  -> show + copy + reset
 *   - a login with none captured        -> "not captured", reset to issue one
 *   - NO login at all                   -> provision one (the repair path)
 *
 * Nothing is fetched until the operator clicks, so the directory never holds a
 * table of plaintext passwords it was not asked for.
 */
export default function ClientCredentialCell({ client }: { client: ClientRecord }) {
  const reveal = useRevealPortalCredentials();
  const setPw = useSetPortalPassword();
  const provision = useProvisionPortalLogin();
  const [creds, setCreds] = useState<PortalCredentials[] | null>(null);
  const [open, setOpen] = useState(false);

  const busy = reveal.isPending || setPw.isPending || provision.isPending;
  const err = (reveal.error ?? setPw.error ?? provision.error) as Error | undefined;

  function load() {
    reveal.mutate(client.id, { onSuccess: setCreds });
  }

  function handleProvision() {
    const username = client.portal?.admin || genPortalLogin(client.contact.name, client.cn);
    provision.mutate(
      {
        clientId: client.id,
        email: client.contact.email,
        name: client.contact.name,
        username,
        password: genPortalPassword(),
      },
      { onSuccess: load },
    );
  }

  if (!open) {
    return (
      <button
        type="button"
        className="cred-show"
        title={`Show ${client.cn}'s portal login`}
        onClick={() => {
          setOpen(true);
          load();
        }}
      >
        <span className="material-symbols-rounded">key</span> Show login
      </button>
    );
  }

  return (
    <div className="cred-box">
      {busy && !creds ? (
        <div className="cred-muted">Loading…</div>
      ) : err && !creds ? (
        <div className="cred-muted cred-err">{err.message}</div>
      ) : creds && creds.length === 0 ? (
        <>
          <div className="cred-muted cred-err">
            No portal login — this client cannot sign in.
          </div>
          <div className="cred-actions">
            <button type="button" className="cred-link" onClick={handleProvision} disabled={busy}>
              <span className="material-symbols-rounded">person_add</span>
              {provision.isPending ? "Creating…" : "Create portal login"}
            </button>
            <button type="button" className="cred-link" onClick={() => setOpen(false)}>
              <span className="material-symbols-rounded">visibility_off</span> Hide
            </button>
          </div>
        </>
      ) : creds ? (
        <>
          {creds.map((c) => (
            <div key={c.id}>
              <div className="cred-row">
                <span className="cred-k">User</span>
                <span className="cred-v">{c.username ?? c.email}</span>
                <CopyBtn value={c.username ?? c.email} label="portal username" />
              </div>
              <div className="cred-row">
                <span className="cred-k">Pass</span>
                {c.password ? (
                  <>
                    <span className="cred-v cred-pw">{c.password}</span>
                    <CopyBtn value={c.password} label="portal password" />
                  </>
                ) : (
                  <span className="cred-v cred-na">not captured — reset to issue a new one</span>
                )}
              </div>
              <div className="cred-actions">
                <button
                  type="button"
                  className="cred-link"
                  onClick={() =>
                    setPw.mutate(
                      { clientId: client.id, userId: c.id },
                      {
                        onSuccess: (next) =>
                          setCreds((prev) =>
                            (prev ?? []).map((row) => (row.id === next.id ? next : row)),
                          ),
                      },
                    )
                  }
                  disabled={busy}
                >
                  <span className="material-symbols-rounded">autorenew</span>
                  {setPw.isPending ? "Resetting…" : c.password ? "Reset" : "Set password"}
                </button>
              </div>
            </div>
          ))}
          {err && <div className="cred-muted cred-err">{err.message}</div>}
          <div className="cred-actions">
            <button type="button" className="cred-link" onClick={() => setOpen(false)}>
              <span className="material-symbols-rounded">visibility_off</span> Hide
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
