"use client";

import { useState } from "react";
import Link from "next/link";
import type { CCGscSummary, CCGa4Summary } from "@/lib/hooks/commandCenter";
import { useClients } from "@/lib/hooks/clients";
import { useCreateGscProperty, useCreateGa4Property, connectAndRedirect } from "@/lib/hooks/siteAnalytics";

// Agency-wide GSC + GA4 snapshot for the admin dashboard, fed from
// GET /command-center (`gsc` / `ga4` — already-rolled-up agency totals). Real
// numbers once at least one property is connected; an honest "not connected
// yet" state (with an inline connect flow) otherwise — mirrors SpendSnapshot's
// placement/shape on the overview grid.
export default function SiteAnalyticsCard({ gsc, ga4 }: { gsc: CCGscSummary; ga4: CCGa4Summary }) {
  const [open, setOpen] = useState(false);
  const showConnect = gsc.placeholder && ga4.placeholder;

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Site Analytics · Search Console &amp; GA4</div>
          <div className="cs">
            {showConnect
              ? "No Google property connected yet"
              : `${gsc.connected}/${gsc.total} Search Console · ${ga4.connected}/${ga4.total} GA4 connected`}
          </div>
        </div>
        <div className="tools">
          <button type="button" className="ghostbtn" onClick={() => setOpen((v) => !v)}>
            {open ? "Close" : "Connect Google"}
            <span className="material-symbols-rounded">{open ? "expand_less" : "add_link"}</span>
          </button>
        </div>
      </div>

      <div className="ov-spend-head">
        <div>
          <span className="ov-spend-big">{gsc.clicks28d.toLocaleString()}</span>
          <span className="ov-spend-cap"> clicks · {gsc.impressions28d.toLocaleString()} impressions (28d)</span>
        </div>
      </div>
      <div className="ov-spend-head">
        <div>
          <span className="ov-spend-big">{ga4.sessions28d.toLocaleString()}</span>
          <span className="ov-spend-cap"> sessions · {ga4.users28d.toLocaleString()} users (28d)</span>
        </div>
      </div>

      {open && <ConnectForm onDone={() => setOpen(false)} />}

      {(gsc.placeholder || ga4.placeholder) && !open && (
        <div className="ov-spend-foot">
          <span>
            {gsc.total === 0 && ga4.total === 0
              ? "Connect a client's Search Console or GA4 property to light this up."
              : "Some properties are registered but not yet connected — finish the Google consent flow."}
          </span>
        </div>
      )}
    </section>
  );
}

function ConnectForm({ onDone }: { onDone: () => void }) {
  const clientsQ = useClients();
  const clients = clientsQ.data ?? [];
  const [clientId, setClientId] = useState("");
  const [kind, setKind] = useState<"gsc" | "ga4">("gsc");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [held, setHeld] = useState<string | null>(null);

  const createGsc = useCreateGscProperty();
  const createGa4 = useCreateGa4Property();

  const effectiveClientId = clientId || clients[0]?.id || "";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!effectiveClientId || !value.trim()) return;
    setBusy(true);
    setError(null);
    setHeld(null);
    try {
      const property =
        kind === "gsc"
          ? await createGsc.mutateAsync({ clientId: effectiveClientId, siteUrl: value.trim() })
          : await createGa4.mutateAsync({ clientId: effectiveClientId, propertyId: value.trim() });
      const result = await connectAndRedirect(kind, property.id);
      if (result.held) {
        setHeld(
          result.reason === "no_oauth_client"
            ? "Property registered — but no Google OAuth client is configured yet. Load GOOGLE_OAUTH_CLIENT_ID/SECRET, then connect from here."
            : `Property registered — held (${result.reason}).`,
        );
        setBusy(false);
      }
      // On success `connectAndRedirect` navigates the browser away, so nothing
      // further runs here in that path.
    } catch {
      setError("Couldn't register that property. Check the site URL / property ID and try again.");
      setBusy(false);
    }
  }

  return (
    <form className="co-form" onSubmit={submit} style={{ marginTop: 12 }}>
      <div className="fld">
        <label>Client</label>
        <select value={effectiveClientId} onChange={(e) => setClientId(e.target.value)} disabled={clients.length === 0}>
          {clients.length === 0 ? (
            <option value="">{clientsQ.isLoading ? "Loading clients…" : "No clients yet"}</option>
          ) : (
            clients.map((c) => <option key={c.id} value={c.id}>{c.cn}</option>)
          )}
        </select>
      </div>

      <div className="fld">
        <label>Property type</label>
        <div className="seg co-target-seg">
          <button type="button" className={kind === "gsc" ? "on" : ""} onClick={() => setKind("gsc")}>
            Search Console
          </button>
          <button type="button" className={kind === "ga4" ? "on" : ""} onClick={() => setKind("ga4")}>
            GA4
          </button>
        </div>
      </div>

      <div className="fld">
        <label>{kind === "gsc" ? "Site URL" : "GA4 property ID"}</label>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={kind === "gsc" ? "https://clientsite.com/" : "properties/123456789"}
        />
      </div>

      {error && <div className="login-error" role="alert"><span className="material-symbols-rounded">error</span>{error}</div>}
      {held && <div className="login-error" role="status"><span className="material-symbols-rounded">schedule</span>{held}</div>}

      <button className="primary-btn wide" type="submit" disabled={busy || !value.trim() || !effectiveClientId}>
        <span className="material-symbols-rounded">add_link</span>
        {busy ? "Connecting…" : "Register & connect"}
      </button>

      <div className="ov-spend-foot">
        <Link href="/admin/settings" className="ghostbtn" onClick={onDone}>
          Manage in Settings<span className="material-symbols-rounded">arrow_forward</span>
        </Link>
      </div>
    </form>
  );
}
