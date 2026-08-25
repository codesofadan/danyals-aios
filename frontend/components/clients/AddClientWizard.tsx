"use client";

import { useEffect, useRef, useState } from "react";
import { reportBundles, type SubTier } from "@/lib/data";
import CopyButton from "@/components/CopyButton";
import type { NewClientInput } from "@/lib/hooks/clients";
import type { BusinessMarket } from "@/lib/offpage";
import nap from "@/components/offpage/Wave4.module.css";

const MARKETS: BusinessMarket[] = ["US", "UK", "CA", "AU", "GLOBAL"];

const ADJ = ["Solar", "Rapid", "Cobalt", "Lunar", "Amber", "Quartz", "Nimbus", "Vivid", "Onyx", "Cedar", "Zephyr", "Crimson"];
const NOUN = ["Falcon", "Harbor", "Cipher", "Meadow", "Quasar", "Lynx", "Beacon", "Vertex", "Willow", "Ember", "Comet", "Delta"];
const SYM = "!@#$%&*?";


// Crypto-random index — this password is the REAL stored portal credential (the
// server hashes exactly what the wizard generates), so Math.random isn't enough.
function rand(n: number): number {
  const buf = new Uint32Array(1);
  crypto.getRandomValues(buf);
  return buf[0] % n;
}

function pick<T>(arr: T[]): T { return arr[rand(arr.length)]; }

// Mirrors the server's shape: Adjective-Noun####$xxxxxx (4 digits + symbol + 6 hex).
function genPassword(): string {
  const digits = String(1000 + rand(9000));
  const sym = SYM[rand(SYM.length)];
  const tail = Array.from({ length: 6 }, () => "0123456789abcdef"[rand(16)]).join("");
  return `${pick(ADJ)}-${pick(NOUN)}${digits}${sym}${tail}`;
}

// Portal login as `<first-name>@aios.com`, from the contact's name (falls back to
// the company name). Never the client's own email/domain - it's an AIOS portal login.
function genLogin(contactName: string, client: string): string {
  const source = contactName.trim() || client.trim();
  const first = source.split(/\s+/)[0].toLowerCase().replace(/[^a-z0-9]/g, "");
  return `${first || "client"}@aios.com`;
}

export default function AddClientWizard({ onClose, onAdd }: { onClose: () => void; onAdd: (c: NewClientInput) => void }) {
  const [cn, setCn] = useState("");
  const [industry, setIndustry] = useState("");
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
  const [adminPass] = useState(genPassword);
  const [bundleKey, setBundleKey] = useState<string>(reportBundles[0]?.key ?? "");

  const emailValid = /\S+@\S+\.\S+/.test(contactEmail);
  const nameValid = cn.trim().length > 1;
  const contactValid = contactName.trim().length > 1;

  const napFilled = [napBusiness, napAddress, napCity, napPhone, napWebsite, napCategory, napDescription]
    .some((v) => v.trim().length > 0);

  function finish() {
    if (!nameValid || !contactValid || !emailValid) return;
    const adminLogin = genLogin(contactName, cn);
    onAdd({
      cn: cn.trim(),
      industry: industry.trim() || "General",
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
                    Copy these now and send them to the client — the password is generated
                    here and stored only as a hash, so it cannot be shown again.
                  </div>
                </div>
              </div>
              <div className="wiz-cred-row">
                <span className="wiz-cred-k">Username</span>
                <code className="wiz-cred-v">{genLogin(contactName, cn)}</code>
                <CopyButton value={genLogin(contactName, cn)} label="portal username" />
              </div>
              <div className="wiz-cred-row">
                <span className="wiz-cred-k">Password</span>
                <code className="wiz-cred-v">{adminPass}</code>
                <CopyButton value={adminPass} label="portal password" />
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
