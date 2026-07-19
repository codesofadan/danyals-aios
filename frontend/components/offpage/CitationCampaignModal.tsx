"use client";

import { useEffect, useMemo, useState } from "react";
import { useClients } from "@/lib/hooks/clients";
import {
  useBusinessProfiles,
  useCreateBusinessProfile,
  useCreateCitationCampaign,
  useDirectories,
} from "@/lib/hooks/offpage";
import {
  AUTOMATABLE_TIERS,
  TIER_META,
  type BusinessMarket,
  type CitationCampaignResult,
  type DirectoryTier,
} from "@/lib/offpage";

const MARKETS: BusinessMarket[] = ["US", "UK", "CA", "AU"];

export default function CitationCampaignModal({ onClose }: { onClose: () => void }) {
  const clientsQ = useClients();
  const [clientId, setClientId] = useState("");
  const profilesQ = useBusinessProfiles(clientId || undefined);
  const profiles = profilesQ.data ?? [];
  const [profileId, setProfileId] = useState("");

  // A fresh client with no profile falls straight into the "create one" form.
  useEffect(() => {
    if (!clientId) return;
    if (profiles.length > 0 && !profileId) setProfileId(profiles[0].id);
  }, [clientId, profiles, profileId]);

  const [showNewProfile, setShowNewProfile] = useState(false);
  const [businessName, setBusinessName] = useState("");
  const [addressLine1, setAddressLine1] = useState("");
  const [city, setCity] = useState("");
  const [region, setRegion] = useState("");
  const [postalCode, setPostalCode] = useState("");
  const [phone, setPhone] = useState("");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [market, setMarket] = useState<BusinessMarket>("US");

  const createProfile = useCreateBusinessProfile();
  const createCampaign = useCreateCitationCampaign();

  const [markets, setMarkets] = useState<Set<BusinessMarket>>(new Set(["US", "GLOBAL"]));
  const [tiers, setTiers] = useState<Set<DirectoryTier>>(new Set(AUTOMATABLE_TIERS));
  const [result, setResult] = useState<CitationCampaignResult | null>(null);

  const previewQ = useDirectories({ market: Array.from(markets), tier: Array.from(tiers) });
  const previewCount = previewQ.data?.length ?? 0;

  const canSaveProfile = businessName.trim().length > 1 && addressLine1.trim().length > 1 && city.trim().length > 0;
  const canDispatch = !!clientId && !!profileId && markets.size > 0 && tiers.size > 0;

  function toggle<T>(set: Set<T>, value: T, setSet: (s: Set<T>) => void) {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    setSet(next);
  }

  function saveProfile(e: React.FormEvent) {
    e.preventDefault();
    if (!canSaveProfile || !clientId) return;
    createProfile.mutate(
      {
        clientId, businessName: businessName.trim(), addressLine1: addressLine1.trim(),
        city: city.trim(), region: region.trim(), postalCode: postalCode.trim(),
        phone: phone.trim(), websiteUrl: websiteUrl.trim(), market,
      },
      {
        onSuccess: (row) => {
          setProfileId(row.id);
          setShowNewProfile(false);
        },
      },
    );
  }

  function dispatch() {
    if (!canDispatch) return;
    createCampaign.mutate(
      {
        clientId, businessProfileId: profileId,
        markets: Array.from(markets), tiers: Array.from(tiers),
      },
      { onSuccess: (body) => setResult(body) },
    );
  }

  const clientOptions = useMemo(() => clientsQ.data ?? [], [clientsQ.data]);

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-h">
          <div>
            <div className="modal-t">Build citations</div>
            <div className="modal-s">
              Queue a submission campaign — direct API, aggregator push, or the self-hosted
              Playwright bot, by directory tier. Manual-only directories never queue.
            </div>
          </div>
          <button type="button" className="modal-x" onClick={onClose} aria-label="Close">
            <span className="material-symbols-rounded">close</span>
          </button>
        </div>

        {result ? (
          <div className="wiz-body">
            <div className="op-flash" style={{ position: "static" }}>
              <span className="material-symbols-rounded">task_alt</span>
              Queued {result.queued} directories · {result.alreadyQueued} already in flight ·{" "}
              {result.skippedManualOnly} manual-only skipped
            </div>
            <div className="fld">
              <label>Estimated cost (R5 pre-check — each row still cost-gates individually)</label>
              <div className="op-strong">${result.estimatedCost.toFixed(4)}</div>
            </div>
            <div className="modal-f">
              <button className="primary-btn" onClick={onClose}>Done</button>
            </div>
          </div>
        ) : (
          <div className="wiz-body">
            <div className="fld">
              <label>Client</label>
              <select value={clientId} onChange={(e) => { setClientId(e.target.value); setProfileId(""); setShowNewProfile(false); }}>
                <option value="">Choose a client…</option>
                {clientOptions.map((c) => (
                  <option key={c.id} value={c.id}>{c.cn}</option>
                ))}
              </select>
            </div>

            {clientId && !showNewProfile && (
              <div className="fld">
                <label>Business profile (canonical NAP)</label>
                {profiles.length > 0 ? (
                  <select value={profileId} onChange={(e) => setProfileId(e.target.value)}>
                    {profiles.map((p) => (
                      <option key={p.id} value={p.id}>{p.label} — {p.businessName}, {p.city}</option>
                    ))}
                  </select>
                ) : (
                  <div className="op-muted">No business profile yet for this client.</div>
                )}
                <button type="button" className="ghostbtn" style={{ marginTop: 8 }} onClick={() => setShowNewProfile(true)}>
                  <span className="material-symbols-rounded">add_business</span>
                  {profiles.length > 0 ? "Add another location" : "Add the business profile"}
                </button>
              </div>
            )}

            {showNewProfile && (
              <form className="wiz-body" style={{ padding: 0 }} onSubmit={saveProfile}>
                <div className="fld-row">
                  <div className="fld">
                    <label>Business name</label>
                    <input value={businessName} onChange={(e) => setBusinessName(e.target.value)} placeholder="Acme Dental" />
                  </div>
                  <div className="fld">
                    <label>Market</label>
                    <select value={market} onChange={(e) => setMarket(e.target.value as BusinessMarket)}>
                      {MARKETS.map((m) => <option key={m} value={m}>{m}</option>)}
                    </select>
                  </div>
                </div>
                <div className="fld">
                  <label>Address</label>
                  <input value={addressLine1} onChange={(e) => setAddressLine1(e.target.value)} placeholder="123 Main St" />
                </div>
                <div className="fld-row">
                  <div className="fld">
                    <label>City</label>
                    <input value={city} onChange={(e) => setCity(e.target.value)} placeholder="Bellevue" />
                  </div>
                  <div className="fld">
                    <label>Region / state</label>
                    <input value={region} onChange={(e) => setRegion(e.target.value)} placeholder="WA" />
                  </div>
                  <div className="fld">
                    <label>Postal code</label>
                    <input value={postalCode} onChange={(e) => setPostalCode(e.target.value)} placeholder="98004" />
                  </div>
                </div>
                <div className="fld-row">
                  <div className="fld">
                    <label>Phone</label>
                    <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="555-0100" />
                  </div>
                  <div className="fld">
                    <label>Website</label>
                    <input value={websiteUrl} onChange={(e) => setWebsiteUrl(e.target.value)} placeholder="https://acme.example" />
                  </div>
                </div>
                <div className="modal-f">
                  <button type="button" className="ghostbtn" onClick={() => setShowNewProfile(false)}>Cancel</button>
                  <button type="submit" className="primary-btn" disabled={!canSaveProfile || createProfile.isPending}>
                    {createProfile.isPending ? "Saving…" : "Save profile"}
                  </button>
                </div>
              </form>
            )}

            {clientId && profileId && !showNewProfile && (
              <>
                <div className="fld">
                  <label>Markets</label>
                  <div className="op-toolset">
                    {[...MARKETS, "GLOBAL" as BusinessMarket].map((m) => (
                      <button
                        type="button" key={m}
                        className={markets.has(m) ? "op-act update" : "ghostbtn"}
                        onClick={() => toggle(markets, m, setMarkets)}
                      >
                        {m}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="fld">
                  <label>Automatable tiers</label>
                  <div className="op-toolset">
                    {AUTOMATABLE_TIERS.map((t) => (
                      <button
                        type="button" key={t}
                        className={tiers.has(t) ? "op-act update" : "ghostbtn"}
                        onClick={() => toggle(tiers, t, setTiers)}
                      >
                        {TIER_META[t].label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="op-muted">
                  {previewCount} directories match this market/tier combination (some may already be
                  in flight for this client — the exact count is confirmed on dispatch).
                </div>
                <div className="modal-f">
                  <button type="button" className="ghostbtn" onClick={onClose}>Cancel</button>
                  <button className="primary-btn" onClick={dispatch} disabled={!canDispatch || createCampaign.isPending}>
                    <span className="material-symbols-rounded">rocket_launch</span>
                    {createCampaign.isPending ? "Queuing…" : "Queue campaign"}
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
