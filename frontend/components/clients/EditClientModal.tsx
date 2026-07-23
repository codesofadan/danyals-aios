"use client";

import { useEffect, useState } from "react";
import { TIER_PRICE, type ClientRecord, type SubStatus, type SubTier } from "@/lib/data";
import {
  useClientBusinessProfile, useSaveClientBusinessProfile, type ClientUpdate,
} from "@/lib/hooks/clients";
import type { BusinessMarket } from "@/lib/offpage";
import nap from "@/components/offpage/Wave4.module.css";

const TIERS: SubTier[] = ["Starter", "Growth", "Scale"];
const MARKETS: BusinessMarket[] = ["US", "UK", "CA", "AU", "GLOBAL"];
const STATUSES: { key: SubStatus; label: string }[] = [
  { key: "active", label: "Active" },
  { key: "trial", label: "Trial" },
  { key: "past_due", label: "Past due" },
  { key: "paused", label: "Paused" },
];

// Edit a client's core account fields → PATCH /clients/{id}. Only the fields that
// actually changed are sent (the backend applies a partial update), so an unchanged
// form saves nothing.
export default function EditClientModal({
  client,
  busy,
  error,
  onClose,
  onSave,
}: {
  client: ClientRecord;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSave: (changes: ClientUpdate) => void;
}) {
  const [cn, setCn] = useState(client.cn);
  const [industry, setIndustry] = useState(client.industry);
  const [tier, setTier] = useState<SubTier>(client.tier);
  const [status, setStatus] = useState<SubStatus>(client.status);
  const [mrr, setMrr] = useState(String(client.mrr));

  // The client's own NAP (client_business_profiles, 0051): loaded independently and
  // saved with its own action (a separate PUT), so a NAP edit never depends on an
  // account-field change and vice versa.
  const napQ = useClientBusinessProfile(client.id);
  const saveNap = useSaveClientBusinessProfile();
  const [napBusiness, setNapBusiness] = useState("");
  const [napAddress, setNapAddress] = useState("");
  const [napCity, setNapCity] = useState("");
  const [napRegion, setNapRegion] = useState("");
  const [napPostal, setNapPostal] = useState("");
  const [napMarket, setNapMarket] = useState<BusinessMarket>("US");
  const [napPhone, setNapPhone] = useState("");
  const [napWebsite, setNapWebsite] = useState("");
  const [napCategory, setNapCategory] = useState("");
  const [napDescription, setNapDescription] = useState("");
  const [napSaved, setNapSaved] = useState(false);

  // Prefill the NAP fields once the stored profile loads.
  useEffect(() => {
    const p = napQ.data;
    if (!p) return;
    setNapBusiness(p.businessName);
    setNapAddress(p.addressLine1);
    setNapCity(p.city);
    setNapRegion(p.region);
    setNapPostal(p.postalCode);
    setNapMarket(p.market);
    setNapPhone(p.phone);
    setNapWebsite(p.websiteUrl);
    setNapCategory(p.primaryCategory);
    setNapDescription(p.description);
  }, [napQ.data]);

  function saveBusinessProfile() {
    if (saveNap.isPending) return;
    saveNap.mutate(
      {
        clientId: client.id,
        nap: {
          businessName: napBusiness.trim(), addressLine1: napAddress.trim(),
          city: napCity.trim(), region: napRegion.trim(), postalCode: napPostal.trim(),
          market: napMarket, phone: napPhone.trim(), websiteUrl: napWebsite.trim(),
          primaryCategory: napCategory.trim(), description: napDescription.trim(),
        },
      },
      {
        onSuccess: () => {
          setNapSaved(true);
          window.setTimeout(() => setNapSaved(false), 2600);
        },
      },
    );
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const nameValid = cn.trim().length > 1;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!nameValid || busy) return;
    // Diff against the original so we only PATCH what changed.
    const changes: ClientUpdate = {};
    if (cn.trim() !== client.cn) changes.cn = cn.trim();
    if (industry.trim() !== client.industry) changes.industry = industry.trim();
    if (tier !== client.tier) changes.tier = tier;
    if (status !== client.status) changes.status = status;
    const mrrNum = Math.max(0, Math.round(Number(mrr)) || 0);
    if (mrrNum !== client.mrr) changes.mrr = mrrNum;
    if (Object.keys(changes).length === 0) { onClose(); return; }
    onSave(changes);
  }

  return (
    <div className="tw">
      <div className="modal-scrim" onClick={onClose}>
        <form className="modal wiz" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
          <div className="modal-h">
            <div>
              <div className="modal-t">Edit client</div>
              <div className="modal-s">Update {client.cn}&apos;s account details.</div>
            </div>
            <button type="button" className="modal-x" onClick={onClose} aria-label="Close">
              <span className="material-symbols-rounded">close</span>
            </button>
          </div>

          <div className="wiz-body">
            <div className="fld">
              <label>Client / company name</label>
              <input value={cn} onChange={(e) => setCn(e.target.value)} autoFocus />
            </div>
            <div className="fld-row">
              <div className="fld">
                <label>Industry</label>
                <input value={industry} onChange={(e) => setIndustry(e.target.value)} placeholder="e.g. Healthcare" />
              </div>
              <div className="fld">
                <label>Plan tier</label>
                <div className="tpl-select">
                  <span className="material-symbols-rounded tpl-ic">workspace_premium</span>
                  <select value={tier} onChange={(e) => setTier(e.target.value as SubTier)} aria-label="Plan tier">
                    {TIERS.map((t) => (
                      <option key={t} value={t}>{t} — ${TIER_PRICE[t]}/mo</option>
                    ))}
                  </select>
                </div>
              </div>
            </div>
            <div className="fld-row">
              <div className="fld">
                <label>Subscription status</label>
                <div className="tpl-select">
                  <span className="material-symbols-rounded tpl-ic">toggle_on</span>
                  <select value={status} onChange={(e) => setStatus(e.target.value as SubStatus)} aria-label="Subscription status">
                    {STATUSES.map((s) => (
                      <option key={s.key} value={s.key}>{s.label}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="fld">
                <label>MRR ($ / month)</label>
                <input type="number" min={0} value={mrr} onChange={(e) => setMrr(e.target.value)} placeholder="290" />
              </div>
            </div>

            <div className={nap.napBlock}>
              <div className={nap.napHead}>
                <span className="material-symbols-rounded">storefront</span>
                <div>
                  <div className={nap.napTitle}>Business profile / NAP</div>
                  <div className={nap.napSub}>
                    The canonical name, address &amp; phone citations submit against. Saved
                    separately from the account fields above.
                  </div>
                </div>
              </div>
              {napQ.isLoading ? (
                <div className="op-muted">Loading business profile…</div>
              ) : (
                <>
                  <div className="fld-row">
                    <div className="fld">
                      <label>Business name</label>
                      <input value={napBusiness} onChange={(e) => setNapBusiness(e.target.value)} placeholder={client.cn} />
                    </div>
                    <div className="fld">
                      <label>Primary category</label>
                      <input value={napCategory} onChange={(e) => setNapCategory(e.target.value)} placeholder="Dentist" />
                    </div>
                  </div>
                  <div className="fld">
                    <label>Address</label>
                    <input value={napAddress} onChange={(e) => setNapAddress(e.target.value)} placeholder="123 Main St" />
                  </div>
                  <div className="fld-row">
                    <div className="fld">
                      <label>City</label>
                      <input value={napCity} onChange={(e) => setNapCity(e.target.value)} placeholder="Bellevue" />
                    </div>
                    <div className="fld">
                      <label>Region / state</label>
                      <input value={napRegion} onChange={(e) => setNapRegion(e.target.value)} placeholder="WA" />
                    </div>
                    <div className="fld">
                      <label>Postal code</label>
                      <input value={napPostal} onChange={(e) => setNapPostal(e.target.value)} placeholder="98004" />
                    </div>
                    <div className="fld">
                      <label>Market</label>
                      <select value={napMarket} onChange={(e) => setNapMarket(e.target.value as BusinessMarket)} aria-label="Market">
                        {MARKETS.map((m) => <option key={m} value={m}>{m}</option>)}
                      </select>
                    </div>
                  </div>
                  <div className="fld-row">
                    <div className="fld">
                      <label>Phone</label>
                      <input value={napPhone} onChange={(e) => setNapPhone(e.target.value)} placeholder="555-0100" />
                    </div>
                    <div className="fld">
                      <label>Website</label>
                      <input value={napWebsite} onChange={(e) => setNapWebsite(e.target.value)} placeholder="https://harbordental.com" />
                    </div>
                  </div>
                  <div className="fld">
                    <label>Description</label>
                    <input value={napDescription} onChange={(e) => setNapDescription(e.target.value)} placeholder="Family &amp; cosmetic dentistry in Bellevue, WA" />
                  </div>
                  <div className="modal-f" style={{ marginTop: 4 }}>
                    <button type="button" className="ghostbtn" onClick={saveBusinessProfile} disabled={saveNap.isPending}>
                      <span className="material-symbols-rounded">save</span>
                      {saveNap.isPending ? "Saving…" : "Save business profile"}
                    </button>
                    {napSaved && (
                      <span className={nap.napFlash}>
                        <span className="material-symbols-rounded">task_alt</span>NAP saved.
                      </span>
                    )}
                    {saveNap.error instanceof Error && (
                      <span className="op-muted">Couldn&apos;t save - {saveNap.error.message}</span>
                    )}
                  </div>
                </>
              )}
            </div>

            {error && (
              <div className="login-error" role="alert">
                <span className="material-symbols-rounded">error</span>{error}
              </div>
            )}

            <div className="modal-f">
              <button type="button" className="ghostbtn" onClick={onClose}>Cancel</button>
              <button type="submit" className="primary-btn" disabled={!nameValid || busy}>
                <span className="material-symbols-rounded">save</span>
                {busy ? "Saving…" : "Save changes"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
