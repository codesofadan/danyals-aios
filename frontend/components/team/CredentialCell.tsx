"use client";

import { useState } from "react";
import { useRevealCredentials, useSetPassword, type MemberCredentials } from "@/lib/hooks/team";

// A small copy-to-clipboard button with a 1.2s "copied" tick.
function CopyBtn({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="cred-copy"
      title={`Copy ${label}`}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
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
 * Reveal + copy + reset a member's login credentials, on demand. Nothing is
 * fetched until the admin clicks "Show login" (passwords aren't rendered for the
 * whole roster at once). The password comes from the server's AES-256-GCM sealed
 * copy; an account provisioned before the feature shows "not captured" with a
 * one-click Reset to set a sharable password.
 */
export default function CredentialCell({ userId }: { userId: string }) {
  const reveal = useRevealCredentials();
  const setPw = useSetPassword();
  const [creds, setCreds] = useState<MemberCredentials | null>(null);
  const [open, setOpen] = useState(false);

  const busy = reveal.isPending || setPw.isPending;
  const err = (reveal.error ?? setPw.error) as Error | undefined;

  if (!open) {
    return (
      <button
        type="button"
        className="cred-show"
        onClick={() => {
          setOpen(true);
          reveal.mutate(userId, { onSuccess: setCreds });
        }}
      >
        <span className="material-symbols-rounded">visibility</span> Show login
      </button>
    );
  }

  return (
    <div className="cred-box">
      {busy && !creds ? (
        <div className="cred-muted">Loading…</div>
      ) : err && !creds ? (
        <div className="cred-muted cred-err">{err.message}</div>
      ) : creds ? (
        <>
          <div className="cred-row">
            <span className="cred-k">User</span>
            <span className="cred-v">{creds.username ?? creds.email}</span>
            <CopyBtn value={creds.username ?? creds.email} label="username" />
          </div>
          <div className="cred-row">
            <span className="cred-k">Pass</span>
            {creds.password ? (
              <>
                <span className="cred-v cred-pw">{creds.password}</span>
                <CopyBtn value={creds.password} label="password" />
              </>
            ) : (
              <span className="cred-v cred-na">not captured — reset to set one</span>
            )}
          </div>
          <div className="cred-actions">
            <button
              type="button"
              className="cred-link"
              onClick={() => setPw.mutate({ userId }, { onSuccess: setCreds })}
              disabled={busy}
            >
              <span className="material-symbols-rounded">autorenew</span>
              {setPw.isPending ? "Resetting…" : creds.password ? "Reset" : "Set password"}
            </button>
            <button type="button" className="cred-link" onClick={() => setOpen(false)}>
              <span className="material-symbols-rounded">visibility_off</span> Hide
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
