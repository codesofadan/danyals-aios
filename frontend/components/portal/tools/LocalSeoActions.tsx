"use client";

import { useState } from "react";
import { useAddGbpProfile } from "@/lib/hooks/tools";
import { ActionCard, ClientSelect, PermNote, ToolActionResult } from "./shared";
import type { ToolActionProps } from "./registry";

/** Local SEO — register a Google Business Profile location for a client. Map-pack
 *  rank tracking and NAP-consistency checks hang off the profile once it exists. */
export default function LocalSeoActions({ accent }: ToolActionProps) {
  const [clientId, setClientId] = useState("");
  const [locationLabel, setLocationLabel] = useState("");
  const [category, setCategory] = useState("");
  const [napName, setNapName] = useState("");
  const [napAddress, setNapAddress] = useState("");
  const [napPhone, setNapPhone] = useState("");
  const [website, setWebsite] = useState("");
  const add = useAddGbpProfile();

  const canSubmit = !!clientId && locationLabel.trim().length > 0 && !add.isPending;
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    add.mutate({
      client_id: clientId,
      location_label: locationLabel.trim(),
      primary_category: category.trim() || undefined,
      nap_name: napName.trim() || undefined,
      nap_address: napAddress.trim() || undefined,
      nap_phone: napPhone.trim() || undefined,
      website_uri: website.trim() || undefined,
    });
  };

  return (
    <ActionCard
      title="Add a GBP location"
      subtitle="Register a Google Business Profile location — local rank tracking hangs off it."
      icon="add_location_alt"
      accent={accent}
    >
      <form onSubmit={submit}>
        <div className="fld-row">
          <ClientSelect value={clientId} onChange={setClientId} />
          <div className="fld">
            <label>Location label</label>
            <input value={locationLabel} onChange={(e) => setLocationLabel(e.target.value)} placeholder="Downtown Austin office" />
          </div>
          <div className="fld">
            <label>Primary category (optional)</label>
            <input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Plumber" />
          </div>
        </div>
        <div className="fld-row" style={{ marginTop: 10 }}>
          <div className="fld">
            <label>Business name (optional)</label>
            <input value={napName} onChange={(e) => setNapName(e.target.value)} />
          </div>
          <div className="fld">
            <label>Address (optional)</label>
            <input value={napAddress} onChange={(e) => setNapAddress(e.target.value)} />
          </div>
          <div className="fld">
            <label>Phone (optional)</label>
            <input value={napPhone} onChange={(e) => setNapPhone(e.target.value)} />
          </div>
        </div>
        <div className="fld" style={{ marginTop: 10 }}>
          <label>Website (optional)</label>
          <input value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="https://client.com" />
        </div>
        <button type="button" className="primary-btn wide" style={{ marginTop: 12 }} onClick={submit} disabled={!canSubmit}>
          <span className="material-symbols-rounded">add_location_alt</span>
          {add.isPending ? "Adding…" : "Add location"}
        </button>
        <ToolActionResult error={add.error} success={add.data ? "Location profile created." : null} />
        <PermNote>Needs a lead role. The name/address/phone here is the NAP the consistency checks compare citations against.</PermNote>
      </form>
    </ActionCard>
  );
}
