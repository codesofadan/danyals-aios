"use client";

import { useClients } from "@/lib/hooks/clients";
import CopyButton from "@/components/CopyButton";

export default function ClientCredentials() {
  // The client directory is live (GET /clients). The portal password is generated
  // and shown ONCE at client creation (Clients → Add client, step 3) and emailed —
  // the backend never stores it in readable form and exposes no client-credential
  // write endpoint. So this tab is an honest READ-ONLY reference of the real portal
  // login for each account; it deliberately has no editable password / 2FA / Save.
  const clientsQ = useClients();
  const clients = clientsQ.data ?? [];

  const muted: React.CSSProperties = { padding: "2.5rem 1rem", textAlign: "center", color: "var(--muted)" };
  if (clientsQ.isLoading && clients.length === 0) return <div className="panel-in"><div style={muted}>Loading client portals…</div></div>;
  if (clientsQ.isError && clients.length === 0)
    return <div className="panel-in"><div style={muted}>Couldn&apos;t load clients — {(clientsQ.error as Error)?.message ?? "try again"}.</div></div>;

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">key</span>
          {clients.length} client portals · the admin login for each account
        </div>
        <div className="sec-note inline">
          <span className="material-symbols-rounded">lock</span>
          The portal password is shown once at client creation and emailed — it is never stored in readable form, so it can&apos;t be revealed here.
        </div>
      </div>

      <div className="cc-list">
        {clients.map((c) => (
          <div className="cc-card" key={c.id}>
            <div className="cc-top">
              <div className="cc-who">
                <span className="av sq" style={{ background: c.contact.c }}>{c.contact.init}</span>
                <div>
                  <div className="cc-name">{c.cn}</div>
                  <div className="cc-meta">{c.industry} · {c.tier} plan · {c.sites} site{c.sites > 1 ? "s" : ""}</div>
                </div>
              </div>
              <div className="cc-2fa">
                <span className="cc-2fa-l">Portal 2FA</span>
                {c.portal.twoFA ? (
                  <span className="fa-badge on"><span className="material-symbols-rounded">verified_user</span>On</span>
                ) : (
                  <span className="fa-badge off"><span className="material-symbols-rounded">gpp_maybe</span>Off</span>
                )}
              </div>
            </div>

            <div className="cc-fields">
              <div className="fld">
                <label htmlFor={`u-${c.id}`}>Portal username / login email</label>
                <div className="pass-field">
                  <input id={`u-${c.id}`} value={c.portal.admin} readOnly spellCheck={false} />
                  <CopyButton value={c.portal.admin} label="portal login" className="pf-btn" />
                </div>
              </div>
              <div className="fld">
                <label>Seats</label>
                <input value={`${c.portal.seats} provisioned`} readOnly />
              </div>
              <div className="fld">
                <label>Last portal sign-in</label>
                <input value={c.portal.lastLogin} readOnly />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
