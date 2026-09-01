"use client";

import { useEffect, useMemo, useState } from "react";
import { useClients } from "@/lib/hooks/clients";
import {
  useBusinessProfiles,
  useCitationEngineStatus,
  useSpecBoard,
  useCitationGap,
  useCitationQueue,
  useCreateBusinessProfile,
  useCreateCitationCampaign,
  useDirectories,
  useEnsureBusinessProfile,
} from "@/lib/hooks/offpage";
import {
  AUTOMATABLE_TIERS,
  TIER_META,
  type BusinessMarket,
  type CitationCampaignResult,
  type DirectoryTier,
} from "@/lib/offpage";

const MARKETS: BusinessMarket[] = ["US", "UK", "CA", "AU"];

export default function CitationCampaignModal({ onClose, initialClientId }: { onClose: () => void; initialClientId?: string }) {
  const clientsQ = useClients();
  // Pre-select the client the operator was just analysing (from the gap panel), so the
  // campaign is scoped to that client's missing directories instead of re-picking.
  const [clientId, setClientId] = useState(initialClientId ?? "");
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
  // Richer identity beyond NAP (0060) — what a real directory form also asks for.
  const [tagline, setTagline] = useState("");
  const [description, setDescription] = useState("");
  const [email, setEmail] = useState("");
  const [logoUrl, setLogoUrl] = useState("");
  const [facebookUrl, setFacebookUrl] = useState("");
  const [instagramUrl, setInstagramUrl] = useState("");
  const [linkedinUrl, setLinkedinUrl] = useState("");
  const [yearFounded, setYearFounded] = useState("");
  const [paymentTypes, setPaymentTypes] = useState("");
  const [serviceArea, setServiceArea] = useState("");

  const createProfile = useCreateBusinessProfile();
  const createCampaign = useCreateCitationCampaign();
  const ensureProfile = useEnsureBusinessProfile();

  // Derive a submission profile from the client's OWN NAP (captured at creation), so the
  // operator does not have to re-key an address the wizard already collected. On success
  // the derived profile becomes the selected one.
  function deriveFromSavedNap() {
    if (!clientId || ensureProfile.isPending) return;
    ensureProfile.mutate(clientId, { onSuccess: (row) => setProfileId(row.id) });
  }
  // (its isError is rendered beside the button below)

  const [markets, setMarkets] = useState<Set<BusinessMarket>>(new Set(["US", "GLOBAL"]));
  const [tiers, setTiers] = useState<Set<DirectoryTier>>(new Set(AUTOMATABLE_TIERS));
  const [includeMarketplaces, setIncludeMarketplaces] = useState(false);
  const [result, setResult] = useState<CitationCampaignResult | null>(null);

  const previewQ = useDirectories({ market: Array.from(markets), tier: Array.from(tiers) });
  const previewCount = previewQ.data?.length ?? 0;

  // THE APPROVAL LIST. When the client has been audited, the gap's `missing` set (in
  // build order, vertical/authority/marketplace rules already applied) is shown as
  // selectable rows — the choice the backend's directoryIds field always supported and
  // the UI never offered. Without an audit, the markets/tiers flow below still works.
  const gapQ = useCitationGap(clientId || undefined);
  const missing = useMemo(() => gapQ.data?.missing ?? [], [gapQ.data?.missing]);
  const [deselected, setDeselected] = useState<Set<string>>(new Set());
  const selected = useMemo(
    () => missing.filter((d) => !deselected.has(d.id)),
    [missing, deselected],
  );
  const engineQ = useCitationEngineStatus();
  const queueBoardQ = useCitationQueue();
  const specBoardQ = useSpecBoard();
  // Directory ids with an ACTIVE earned spec — the bot really will attempt these.
  const activeSpecDirs = useMemo(
    () =>
      new Set(
        (specBoardQ.data?.specs ?? []).filter((sp) => sp.active).map((sp) => sp.directoryId),
      ),
    [specBoardQ.data],
  );

  // The honest split: where each selected directory will actually go. Derived from
  // the engine board (transport) — the earned-spec whitelist decides the bot rows,
  // and with it empty every bot-tier row is your team's work.
  const split = useMemo(() => {
    const engines = new Map((engineQ.data?.engines ?? []).map((e) => [e.key, e.connected]));
    const specCount = engineQ.data?.machineSubmittableDirectories ?? 0;
    let auto = 0;
    let team = 0;
    const held: { name: string; why: string }[] = [];
    for (const d of selected) {
      const method = d.submitMethod || "";
      if (method === "api:data_axle") {
        if (engines.get("data_axle")) auto += 1;
        else held.push({ name: d.name, why: "needs a lead-approved price (Data Axle rate not on file)" });
      } else if (method === "api:apple_business") {
        if (engines.get("apple_business")) auto += 1;
        else team += 1; // keyless → routed to the operator queue
      } else if (method.startsWith("api:")) {
        team += 1; // gbp & friends: no engine written → queue
      } else if (activeSpecDirs.has(d.id)) {
        auto += 1; // an EARNED spec: the bot really attempts this one
      } else {
        team += 1; // bot tiers without an earned spec are queue work
      }
    }
    return { auto, team, held, specCount };
  }, [selected, engineQ.data, activeSpecDirs]);

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
    const year = parseInt(yearFounded, 10);
    createProfile.mutate(
      {
        clientId, businessName: businessName.trim(), addressLine1: addressLine1.trim(),
        city: city.trim(), region: region.trim(), postalCode: postalCode.trim(),
        phone: phone.trim(), websiteUrl: websiteUrl.trim(), market,
        // Richer identity beyond NAP (0060) — sent only when filled.
        tagline: tagline.trim(), description: description.trim(), email: email.trim(),
        logoUrl: logoUrl.trim(), facebookUrl: facebookUrl.trim(),
        instagramUrl: instagramUrl.trim(), linkedinUrl: linkedinUrl.trim(),
        serviceArea: serviceArea.trim(),
        yearFounded: Number.isFinite(year) && year > 0 ? year : null,
        paymentTypes: paymentTypes.split(",").map((p) => p.trim()).filter(Boolean),
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
        includeMarketplaces,
        // Audit-first: build EXACTLY what the operator approved from the missing
        // list. Only when no audit backs the modal does the server's own selection
        // run unpinned.
        ...(missing.length > 0 ? { directoryIds: selected.map((d) => d.id) } : {}),
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
              <label>Strategy applied</label>
              <div className="op-muted">
                Vertical: <b>{result.resolvedVertical ?? "general only"}</b>
                {typeof result.capped === "number" && result.capped > 0 && <> · capped {result.capped} past ~45</>}
              </div>
              <div className="op-muted" style={{ marginTop: 2 }}>
                Excluded — off-vertical {result.excludedOffVertical ?? 0} · low-authority{" "}
                {result.excludedLowAuthority ?? 0} · marketplaces {result.excludedMarketplace ?? 0}
              </div>
            </div>
            <div className="fld">
              <label>Estimated cost (R5 pre-check — each row still cost-gates individually)</label>
              <div className="op-strong">${result.estimatedCost.toFixed(4)}</div>
            </div>
            <div className="op-muted" style={{ whiteSpace: "normal", marginTop: 6 }}>
              The Track board on the Citations page is already polling this build —
              close this and watch each directory settle there.
            </div>
            <div className="modal-f">
              <button className="primary-btn" onClick={onClose}>Done — go to the board</button>
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
                  <div className="op-muted">
                    No submission profile yet. Derive one from the client&apos;s saved NAP
                    (captured at creation), or add a location by hand below. If neither exists,
                    add the NAP first from Clients → Edit.
                  </div>
                )}
                <div className="op-toolset" style={{ marginTop: 8 }}>
                  {profiles.length === 0 && (
                    <button type="button" className="op-act update" onClick={deriveFromSavedNap} disabled={ensureProfile.isPending}>
                      <span className="material-symbols-rounded">auto_fix_high</span>
                      {ensureProfile.isPending ? "Deriving…" : "Use the client's saved NAP"}
                    </button>
                  )}
                  <button type="button" className="ghostbtn" onClick={() => setShowNewProfile(true)}>
                    <span className="material-symbols-rounded">add_business</span>
                    {profiles.length > 0 ? "Add another location" : "Add a location by hand"}
                  </button>
                </div>
                {ensureProfile.error instanceof Error && (
                  <div className="op-muted" style={{ marginTop: 6 }}>
                    Couldn&apos;t derive - {ensureProfile.error.message}. Add the client&apos;s NAP first (Clients &gt; Edit).
                  </div>
                )}
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

                {/* Richer identity beyond NAP (0060) — what a real directory form also asks for. */}
                <div className="fld">
                  <label>Tagline <span className="cs">(optional)</span></label>
                  <input value={tagline} onChange={(e) => setTagline(e.target.value)} placeholder="Gentle dentistry, done right" />
                </div>
                <div className="fld">
                  <label>Description <span className="cs">(optional)</span></label>
                  <textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)}
                    placeholder="A short business description directories publish alongside the listing." />
                </div>
                <div className="fld-row">
                  <div className="fld">
                    <label>Email <span className="cs">(optional)</span></label>
                    <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="hello@acme.example" />
                  </div>
                  <div className="fld">
                    <label>Year founded <span className="cs">(optional)</span></label>
                    <input value={yearFounded} onChange={(e) => setYearFounded(e.target.value.replace(/[^0-9]/g, ""))}
                      inputMode="numeric" placeholder="2011" />
                  </div>
                </div>
                <div className="fld-row">
                  <div className="fld">
                    <label>Logo URL <span className="cs">(optional)</span></label>
                    <input value={logoUrl} onChange={(e) => setLogoUrl(e.target.value)} placeholder="https://acme.example/logo.png" />
                  </div>
                  <div className="fld">
                    <label>Service area <span className="cs">(optional)</span></label>
                    <input value={serviceArea} onChange={(e) => setServiceArea(e.target.value)} placeholder="Greater Seattle" />
                  </div>
                </div>
                <div className="fld">
                  <label>Payment types <span className="cs">(optional, comma-separated)</span></label>
                  <input value={paymentTypes} onChange={(e) => setPaymentTypes(e.target.value)} placeholder="Visa, Mastercard, Cash" />
                </div>
                <div className="fld-row">
                  <div className="fld">
                    <label>Facebook <span className="cs">(optional)</span></label>
                    <input value={facebookUrl} onChange={(e) => setFacebookUrl(e.target.value)} placeholder="https://facebook.com/acme" />
                  </div>
                  <div className="fld">
                    <label>Instagram <span className="cs">(optional)</span></label>
                    <input value={instagramUrl} onChange={(e) => setInstagramUrl(e.target.value)} placeholder="https://instagram.com/acme" />
                  </div>
                  <div className="fld">
                    <label>LinkedIn <span className="cs">(optional)</span></label>
                    <input value={linkedinUrl} onChange={(e) => setLinkedinUrl(e.target.value)} placeholder="https://linkedin.com/company/acme" />
                  </div>
                </div>
                <div className="modal-f">
                  <button type="button" className="ghostbtn" onClick={() => setShowNewProfile(false)}>Cancel</button>
                  <button type="submit" className="primary-btn" disabled={!canSaveProfile || createProfile.isPending}>
                    {createProfile.isPending ? "Saving…" : "Save profile"}
                  </button>
                  {createProfile.isError && (
                    <div className="op-note crit" style={{ marginTop: 8 }}>
                      Couldn&apos;t save the profile — {(createProfile.error as Error)?.message ?? "try again"}.
                    </div>
                  )}
                </div>
              </form>
            )}

            {clientId && profileId && !showNewProfile && (
              <>
                <div className="fld">
                  <label>Markets</label>
                  <div className="op-toolset">
                    {(() => {
                      const allMarkets = [...MARKETS, "GLOBAL" as BusinessMarket];
                      const allOn = allMarkets.every((m) => markets.has(m));
                      return (
                        <button type="button"
                          className={allOn ? "op-act update" : "ghostbtn"}
                          onClick={() => setMarkets(allOn ? new Set() : new Set(allMarkets))}>
                          <span className="material-symbols-rounded">done_all</span> All markets
                        </button>
                      );
                    })()}
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
                    {(() => {
                      const allOn = AUTOMATABLE_TIERS.every((t) => tiers.has(t));
                      return (
                        <button type="button"
                          className={allOn ? "op-act update" : "ghostbtn"}
                          onClick={() => setTiers(allOn ? new Set() : new Set(AUTOMATABLE_TIERS))}>
                          <span className="material-symbols-rounded">done_all</span> All tiers
                        </button>
                      );
                    })()}
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
                <div className="fld">
                  <label>Lead-gen marketplaces</label>
                  <div className="op-toolset">
                    <button
                      type="button"
                      className={includeMarketplaces ? "op-act update" : "ghostbtn"}
                      onClick={() => setIncludeMarketplaces((v) => !v)}
                    >
                      <span className="material-symbols-rounded">
                        {includeMarketplaces ? "check_box" : "check_box_outline_blank"}
                      </span>
                      Include Angi, Zillow, Thumbtack &amp; similar
                    </button>
                  </div>
                  <div className="op-muted" style={{ marginTop: 4 }}>
                    Marketplaces give a citation but also rank for the client&apos;s keywords and
                    often charge — excluded by default; opt in deliberately.
                  </div>
                </div>
                {missing.length > 0 ? (
                  <div className="fld">
                    <label>
                      Choose the directories ({selected.length} of {missing.length} missing, in build order)
                    </label>
                    <div style={{ maxHeight: 240, overflowY: "auto", border: "1px solid var(--line)", borderRadius: 10, padding: 8 }}>
                      {missing.map((d) => {
                        const on = !deselected.has(d.id);
                        const method = d.submitMethod || "";
                        const badge =
                          method === "api:data_axle"
                            ? { label: "held — unpriced", cls: "warn" }
                            : activeSpecDirs.has(d.id)
                              ? { label: "bot — spec earned", cls: "ok" }
                              : { label: "your team", cls: "info" };
                        return (
                          <label key={d.id} style={{ display: "flex", gap: 8, alignItems: "center", padding: "3px 2px", cursor: "pointer" }}>
                            <input
                              type="checkbox"
                              checked={on}
                              onChange={() => {
                                const next = new Set(deselected);
                                if (on) next.add(d.id);
                                else next.delete(d.id);
                                setDeselected(next);
                              }}
                            />
                            <span className="op-strong" style={{ whiteSpace: "normal" }}>{d.name}</span>
                            <span className="op-muted" style={{ fontSize: 11 }}>{d.market} · {TIER_META[d.tier]?.label ?? d.tier}</span>
                            <span className={`status-pill ${badge.cls}`} style={{ marginLeft: "auto" }}>{badge.label}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                ) : (
                  <div className="op-muted" style={{ whiteSpace: "normal" }}>
                    {gapQ.isLoading
                      ? "Loading this client's missing directories…"
                      : "No audit backs this build yet — the server will select by market/tier with the strategy defaults. Run a citation audit first to choose exact directories."}{" "}
                    {previewQ.isLoading
                      ? "Counting matching directories…"
                      : previewQ.isError
                        ? ""
                        : `${previewCount} directories match this market/tier before vertical + authority filtering.`}
                  </div>
                )}

                {/* THE HONEST SPLIT — what will actually happen, said BEFORE the money
                    button, not discovered by polling nothing afterwards. */}
                {selected.length > 0 && (
                  <div className="op-note warn" style={{ marginTop: 8 }}>
                    <b>Ready to build {selected.length} directories:</b>
                    <div style={{ marginTop: 4 }}>
                      • <b>{split.auto}</b> will be attempted automatically.
                      {split.specCount === 0 && split.auto === 0 && (
                        <> No directory has an earned form spec yet — each one your team
                        finishes by hand can be taught to the bot afterwards.</>
                      )}
                    </div>
                    <div>
                      • <b>{split.team}</b> will go to your team&apos;s queue — every field
                      pre-filled, each verified live by fetching its URL before it counts.
                      {queueBoardQ.data?.medianSeconds != null ? (
                        <> Estimated operator time ~
                        {Math.round((split.team * queueBoardQ.data.medianSeconds) / 60)} min
                        at the measured median.</>
                      ) : (
                        <> Time not yet measured — the queue measures it as you work.</>
                      )}
                    </div>
                    {split.held.length > 0 && (
                      <div>
                        • <b>{split.held.length}</b> won&apos;t be attempted:{" "}
                        {split.held.slice(0, 3).map((h) => h.name).join(", ")}
                        {split.held.length > 3 ? "…" : ""} — {split.held[0].why}.
                      </div>
                    )}
                    <div style={{ marginTop: 4 }}>
                      Fees today: <b>$0.00</b> — no paid engine can run for this selection;
                      the response confirms the estimate, and each row still cost-gates
                      individually.
                    </div>
                  </div>
                )}
                {createCampaign.isError && (
                  <div className="op-note crit" style={{ marginTop: 8 }}>
                    Couldn&apos;t queue the campaign —{" "}
                    {(createCampaign.error as Error)?.message ?? "try again"}. Nothing was
                    queued and nothing was charged.
                  </div>
                )}
                <div className="modal-f">
                  <button type="button" className="ghostbtn" onClick={onClose}>Cancel</button>
                  <button
                    className="primary-btn"
                    onClick={dispatch}
                    disabled={!canDispatch || createCampaign.isPending || (missing.length > 0 && selected.length === 0)}
                  >
                    <span className="material-symbols-rounded">rocket_launch</span>
                    {createCampaign.isPending
                      ? "Queuing…"
                      : missing.length > 0
                        ? `Queue ${selected.length} directories`
                        : "Queue campaign"}
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
