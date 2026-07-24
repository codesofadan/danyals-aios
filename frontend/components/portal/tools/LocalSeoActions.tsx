"use client";

import { useState } from "react";
import { useAddGbpProfile } from "@/lib/hooks/tools";
import { ActionCard, ClientSelect, PermNote, ToolActionResult } from "./shared";
import type { ToolActionProps } from "./registry";

/** Local SEO — add a Google Business Profile location for a client
 *  (POST /local-seo/profiles). The profile is the anchor map-pack rank tracking,
 *  NAP alignment and the completeness audit all hang off. */
export default function LocalSeoActions({ accent }: ToolActionProps) {
  const [clientId, setClientId] = useState("");
  const [locationLabel, setLocationLabel] = useState("");
  const [category, setCategory] = useState("");
  const [napPhone, setNapPhone] = useState("");
  const [website, setWebsite] = useState("");
  const add = useAddGbpProfile();

  const canRun = !!clientId && locationLabel.trim().length > 1 && !add.isPending;
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canRun) return;
    add.mutate(
      {
        client_id: clientId,
        location_label: locationLabel.trim(),
        primary_category: category.trim() || undefined,
        nap_phone: napPhone.trim() || undefined,
        website_uri: website.trim() || undefined,
      },
      {
        onSuccess: () => {
          setLocationLabel("");
          setCategory("");
          setNapPhone("");
          setWebsite("");
        },
      },
    );
  };

  return (
    <ActionCard
      title="Add a GBP location"
      subtitle="Register a Google Business Profile to track map-pack rank & NAP."
      icon="storefront"
      accent={accent}
      paidAction
    >
      <form onSubmit={submit}>
        <ClientSelect value={clientId} onChange={setClientId} />
        <div className="fld">
          <label>Location label</label>
          <input
            placeholder="NorthPeak Dental — Karachi Clifton"
            value={locationLabel}
            onChange={(e) => setLocationLabel(e.target.value)}
          />
        </div>
        <div className="fld-row">
          <div className="fld">
            <label>Primary category (optional)</label>
            <input placeholder="Dentist" value={category} onChange={(e) => setCategory(e.target.value)} />
          </div>
          <div className="fld">
            <label>Phone (optional)</label>
            <input placeholder="+92 21 111 2222" value={napPhone} onChange={(e) => setNapPhone(e.target.value)} />
          </div>
        </div>
        <div className="fld">
          <label>Website (optional)</label>
          <input
            placeholder="https://northpeakdental.com"
            value={website}
            onChange={(e) => setWebsite(e.target.value)}
          />
        </div>
        <button type="submit" className="primary-btn wide" disabled={!canRun}>
          <span className="material-symbols-rounded">add_business</span>
          {add.isPending ? "Adding…" : "Add GBP location"}
        </button>
      </form>
      <ToolActionResult
        error={add.error}
        success={add.isSuccess ? "GBP location added — track a keyword's map-pack rank against it next." : null}
      />
      <PermNote>Adding a profile needs owner / admin / manager access.</PermNote>
    </ActionCard>
  );
}
