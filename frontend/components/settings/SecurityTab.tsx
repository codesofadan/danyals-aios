"use client";

// Agency security policy (owner/admin). GET/PUT /settings/security had zero
// callers. HONESTY NOTE, stated on the screen: the row is STORED policy - the
// sign-in path does not read it yet, so a toggle here records intent rather
// than changing what the login form enforces today.

import { useEffect, useState } from "react";
import type { SecurityPolicy } from "@/lib/data";
import { useSaveSecurityPolicy, useSecurityPolicy } from "@/lib/hooks/settings";
import QueryGuard from "@/components/ui/QueryGuard";
import { TextField } from "@/components/ui/Field";
import { useToast, describeError } from "@/components/ui/Toast";

const FLAGS: { key: keyof SecurityPolicy; label: string; desc: string }[] = [
  { key: "enforce2FA", label: "Require two-factor", desc: "Every staff sign-in must present a second factor." },
  { key: "strongPasswords", label: "Strong passwords", desc: "Length + mixed-character rules on new passwords." },
  { key: "singleSession", label: "Single session", desc: "A new sign-in ends the previous session." },
  { key: "ipAllowlist", label: "IP allowlist", desc: "Sign-ins only from the allow-listed addresses." },
  { key: "auditLogging", label: "Audit logging", desc: "Record every sign-in and privileged action." },
];

export default function SecurityTab() {
  const q = useSecurityPolicy();
  const save = useSaveSecurityPolicy();
  const toast = useToast();
  const [form, setForm] = useState<SecurityPolicy | null>(null);

  useEffect(() => {
    if (q.data && form === null) setForm(q.data);
  }, [q.data, form]);

  const setNum = (k: keyof SecurityPolicy) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const n = parseInt(e.target.value, 10);
    setForm((f) => (f ? { ...f, [k]: Number.isFinite(n) ? n : 0 } : f));
  };

  return (
    <QueryGuard queries={[q]} label="the security policy" minHeight={180}>
      {form && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(form, {
              onSuccess: () => toast.success("Security policy saved"),
              onError: (err: unknown) => toast.error("Couldn't save", describeError(err)),
            });
          }}
          style={{ maxWidth: 640 }}
        >
          <div className="cs" style={{ marginBottom: 14 }}>
            This is the STORED policy. The sign-in path does not read it yet — saving records
            the agency&apos;s intended rules; wiring enforcement is tracked backend work.
          </div>
          {FLAGS.map((f) => (
            <label key={f.key} style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "10px 0", borderBottom: "1px solid var(--line)", cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={Boolean(form[f.key])}
                onChange={(e) => setForm((p) => (p ? { ...p, [f.key]: e.target.checked } : p))}
                style={{ marginTop: 3 }}
              />
              <span>
                <span style={{ display: "block", fontWeight: 700, fontSize: 13.5 }}>{f.label}</span>
                <span className="cs">{f.desc}</span>
              </span>
            </label>
          ))}
          <div className="fld-row" style={{ marginTop: 14 }}>
            <TextField label="Min password length" type="number" min={8} max={64} value={String(form.minPassLength)} onChange={setNum("minPassLength")} />
            <TextField label="Rotation (days)" type="number" min={0} value={String(form.rotationDays)} onChange={setNum("rotationDays")} hint="0 = never" />
            <TextField label="Session timeout (min)" type="number" min={1} value={String(form.sessionTimeout)} onChange={setNum("sessionTimeout")} />
          </div>
          <button type="submit" className="primary-btn" style={{ marginTop: 16 }} disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save security policy"}
          </button>
        </form>
      )}
    </QueryGuard>
  );
}
