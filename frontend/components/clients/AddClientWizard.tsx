"use client";

import { useEffect, useRef, useState } from "react";
import { reportBundles, type SubTier } from "@/lib/data";
import type { NewClientInput } from "@/lib/hooks/clients";
import { genPortalLogin, genPortalPassword } from "@/lib/portalCredentials";
import type { BusinessMarket } from "@/lib/offpage";
import { SettingRow, Switch } from "@/components/settings/controls";
import nap from "@/components/offpage/Wave4.module.css";

const MARKETS: BusinessMarket[] = ["US", "UK", "CA", "AU", "GLOBAL"];

/** Split pasted seed terms into a clean, de-duplicated list.
 *
 * Operators paste from a sheet or a doc, so newlines AND commas both separate.
 * Blanks and duplicates are dropped here rather than sent for the server to
 * clean up, and the cap matches the API's own bound (200) so a paste of a whole
 * spreadsheet is truncated visibly here instead of 422-ing on submit. */
function parseSeeds(raw: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of raw.split(/[\n,]/)) {
    const term = part.trim();
    if (!term) continue;
    const key = term.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(term);
    if (out.length >= 200) break;
  }
  return out;
}

export default function AddClientWizard({ onClose, onAdd }: { onClose: () => void; onAdd: (c: NewClientInput) => void }) {
  const [cn, setCn] = useState("");
  const [industry, setIndustry] = useState("");
  // Whether audits run this client's LOCAL pipeline - the Google Business Profile
  // lookup, citation discovery and the LOC-* checks. Defaults off: nobody has been
  // asked yet, and a missing local section an operator can switch on beats billing
  // a SaaS client for Places + citation lookups that find nothing.
  const [isLocalBusiness, setIsLocalBusiness] = useState(false);
  // Seed terms for the client's keyword BANK. The content module targets terms
  // from the bank, so a client created without one starts empty and every content
  // run invents its own targets - which is how content and rank tracking end up
  // chasing different keywords for the same client. Optional: research fills the
  // bank out later, and these are stored as bare seeds with no invented metrics.
  const [keywordSeeds, setKeywordSeeds] = useState("");
  // Plan is a free monthly $ amount the admin types (any value); the SubTier enum
  // label is derived from it purely for categorisation/colour.
  const [mrr, setMrr] = useState<number>(690);
  const tier: SubTier = mrr < 500 ? "Starter" : mrr < 1000 ? "Growth" : "Scale";
  const [contactName, setContactName] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  // The client's own NAP, captured up front so the first citation campaign has a real
  // name/address to submit (no "No business profile yet"). Entirely optional - the
  // section can be left blank and filled in later from the Edit modal.
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

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    const t = timers.current;
    return () => {
      window.removeEventListener("keydown", onKey);
      t.forEach(clearTimeout);
    };
  }, [onClose]);

  // Generated ONCE per open, not inside finish(): the operator has to be able to read
  // and hand over the password, and a value regenerated on every render could not be
  // trusted to match what was actually sent. The server hashes exactly this string.
  const [adminPass] = useState(genPortalPassword);
  const [bundleKey, setBundleKey] = useState<string>(reportBundles[0]?.key ?? "");

  const emailValid = /\S+@\S+\.\S+/.test(contactEmail);
  const nameValid = cn.trim().length > 1;
  const contactValid = contactName.trim().length > 1;

  const napFilled = [napBusiness, napAddress, napCity, napPhone, napWebsite, napCategory, napDescription]
    .some((v) => v.trim().length > 0);

  function finish() {
    if (!nameValid || !contactValid || !emailValid) return;
    const adminLogin = genPortalLogin(contactName, cn);
    onAdd({
      cn: cn.trim(),
      industry: industry.trim() || "General",
      isLocalBusiness,
      // One term per line or comma-separated - operators paste from a sheet, so
      // both separators are accepted and blanks/dupes are dropped here rather
      // than sent for the server to clean up.
      keywords: parseSeeds(keywordSeeds),
      // The NAP city is the market these terms are for when there is one; the
      // bank keys on (client, keyword, geo) so this keeps two markets distinct.
      keywordGeo: napCity.trim(),
      tier,
      mrr,
      contactName: contactName.trim(),
      contactEmail: contactEmail.trim(),
      adminLogin,
      adminPass,
      bundle: reportBundles.find((b) => b.key === bundleKey)?.label ?? "Custom",
      // A client created with no grants signs in to a dashboard of padlocks and
      // nothing else. Defaulting to a real bundle is why this picker exists; it can
      // be changed any time from the directory's Reports action.
      reports: reportBundles.find((b) => b.key === bundleKey)?.grants ?? [],
      // Only send a NAP when the operator actually entered one; the backend also
      // ignores a wholly empty profile, so this is belt-and-braces.
      nap: napFilled
        ? {
            businessName: napBusiness.trim() || cn.trim(),
            addressLine1: napAddress.trim(),
            city: napCity.trim(),
            region: napRegion.trim(),
            postalCode: napPostal.trim(),
            market: napMarket,
            phone: napPhone.trim(),
            websiteUrl: napWebsite.trim(),
            primaryCategory: napCategory.trim(),
            description: napDescription.trim(),
          }
        : undefined,
    });
  }

  return (
    <div className="tw">
      <div className="modal-scrim" onClick={onClose}>
        <div className="modal wide wiz" onClick={(e) => e.stopPropagation()}>
          <div className="modal-h">
            <div>
              <div className="modal-t">Add client</div>
              <div className="modal-s">Who is the client and their primary contact?</div>
            </div>
            <button type="button" className="modal-x" onClick={onClose} aria-label="Close">
              <span className="material-symbols-rounded">close</span>
            </button>
          </div>

          <form className="wiz-body" onSubmit={(e) => { e.preventDefault(); finish(); }}>
            <div className="fld">
              <label>Client / company name</label>
              <input value={cn} onChange={(e) => setCn(e.target.value)} placeholder="e.g. Harbor Dental Group" autoFocus />
            </div>
            <div className="fld-row">
              <div className="fld">
                <label>Industry</label>
                <input value={industry} onChange={(e) => setIndustry(e.target.value)} placeholder="e.g. Healthcare" />
              </div>
              <div className="fld">
                <label>Monthly plan ($)</label>
                <input
                  type="number"
                  min={0}
                  step={10}
                  value={mrr}
                  onChange={(e) => setMrr(Math.max(0, Math.round(Number(e.target.value) || 0)))}
                  aria-label="Monthly plan amount in dollars"
                  placeholder="Any amount, e.g. 750"
                />
              </div>
            </div>
            {/* Last of the account fields, beside Industry: this is the same kind of
                claim about the business, and it is deliberately NOT part of the NAP
                block below - the backend never reads it from the address, so an
                operator who fills the NAP in later still keeps their local checks. */}
            <div className="set-list" style={{ marginBottom: 14 }}>
              <SettingRow
                icon="location_on"
                title="Local business"
                desc="Audits for this client include the Google Business Profile lookup, citation discovery and the local-pack checks. Leave it off for SaaS or e-commerce clients with no Google Business Profile - those lookups are billed and find nothing."
              >
                <Switch checked={isLocalBusiness} onChange={setIsLocalBusiness} label="Local business" />
              </SettingRow>
            </div>

            {/* The keyword bank the CONTENT module writes against. Captured here
                because onboarding's "Build keyword seed list" step was a checklist
                tickbox with no data behind it, so the bank stayed empty. */}
            <div className="fld">
              <label>
                Seed keywords <span className={nap.optTag}>optional</span>
              </label>
              <textarea
                rows={3}
                value={keywordSeeds}
                onChange={(e) => setKeywordSeeds(e.target.value)}
                placeholder={"emergency dentist, teeth whitening, invisalign"}
              />
              <div className={nap.napSub} style={{ marginTop: 6 }}>
                One per line, or comma-separated. These start the client&apos;s keyword
                bank, which is what content pages are written against. Saved as
                plain terms - volume and difficulty come from research later.
              </div>
            </div>

            <div className="fld">
              <label>Primary contact name</label>
              <input value={contactName} onChange={(e) => setContactName(e.target.value)} placeholder="e.g. Dr. Sana Malik" />
            </div>
            <div className="fld">
              <label>Contact email</label>
              <input type="email" value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} placeholder="sana@harbordental.com" />
            </div>

            <div className={nap.napBlock}>
              <div className={nap.napHead}>
                <span className="material-symbols-rounded">storefront</span>
                <div>
                  <div className={nap.napTitle}>Business profile / NAP <span className={nap.optTag}>optional</span></div>
                  <div className={nap.napSub}>Captured once so the first citation campaign has a real name, address &amp; phone to submit. Fill it in later from the Edit modal if you prefer.</div>
                </div>
              </div>
              <div className="fld-row">
                <div className="fld">
                  <label>Business name</label>
                  <input value={napBusiness} onChange={(e) => setNapBusiness(e.target.value)} placeholder={cn || "Harbor Dental Group"} />
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
            </div>

            <div className="fld">
              <label>Report access</label>
              <select value={bundleKey} onChange={(e) => setBundleKey(e.target.value)}>
                {reportBundles.map((b) => (
                  <option key={b.key} value={b.key}>{b.label} — {b.tagline}</option>
                ))}
                <option value="">No reports yet — grant them later</option>
              </select>
              <div className="wiz-hint">
                What this client sees when they sign in. Change it any time from the
                directory&apos;s <b>Reports</b> action.
              </div>
            </div>

            <div className="wiz-creds">
              <div className="wiz-creds-h">
                <span className="material-symbols-rounded">key</span>
                <div>
                  <div className="wiz-creds-t">Portal login</div>
                  <div className="wiz-creds-s">
                    A portal login is created for {contactName.trim() || "the primary contact"} as
                    part of this step. The username and password appear once the client
                    exists &mdash; and stay available from <b>Show login</b> on the client&apos;s row.
                  </div>
                </div>
              </div>
            </div>

            <div className="modal-f">
              <button type="button" className="ghostbtn" onClick={onClose}>Cancel</button>
              <button type="submit" className="primary-btn" disabled={!nameValid || !contactValid || !emailValid}>
                <span className="material-symbols-rounded">send</span>Create client
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
