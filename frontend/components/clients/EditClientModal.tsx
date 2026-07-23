"use client";

import { useEffect, useState } from "react";
import { TIER_PRICE, type ClientRecord, type SubStatus, type SubTier } from "@/lib/data";
import type { ClientUpdate } from "@/lib/hooks/clients";

const TIERS: SubTier[] = ["Starter", "Growth", "Scale"];
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
