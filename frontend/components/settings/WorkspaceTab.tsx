"use client";

// Agency workspace settings (owner/admin). GET/PUT /settings/workspace had zero
// callers; the stored row drives client defaults (tier) and the report header
// identity (name, brand colour).

import { useEffect, useState } from "react";
import type { WorkspaceSettingsData } from "@/lib/data";
import { useSaveWorkspaceSettings, useWorkspaceSettings } from "@/lib/hooks/settings";
import QueryGuard from "@/components/ui/QueryGuard";
import { SelectField, TextField } from "@/components/ui/Field";
import { useToast, describeError } from "@/components/ui/Toast";

export default function WorkspaceTab() {
  const q = useWorkspaceSettings();
  const save = useSaveWorkspaceSettings();
  const toast = useToast();
  const [form, setForm] = useState<WorkspaceSettingsData | null>(null);

  // Seed the form once from the server row; edits then live locally until Save.
  useEffect(() => {
    if (q.data && form === null) setForm(q.data);
  }, [q.data, form]);

  const set = <K extends keyof WorkspaceSettingsData>(k: K, v: WorkspaceSettingsData[K]) =>
    setForm((f) => (f ? { ...f, [k]: v } : f));

  return (
    <QueryGuard queries={[q]} label="the workspace settings" minHeight={180}>
      {form && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate(form, {
              onSuccess: () => toast.success("Workspace settings saved"),
              onError: (err: unknown) => toast.error("Couldn't save", describeError(err)),
            });
          }}
          style={{ maxWidth: 640 }}
        >
          <div className="fld-row">
            <TextField label="Agency name" required value={form.agencyName} onChange={(e) => set("agencyName", e.target.value)} />
            <TextField label="Support email" required type="email" value={form.supportEmail} onChange={(e) => set("supportEmail", e.target.value)} />
          </div>
          <div className="fld-row" style={{ marginTop: 10 }}>
            <TextField label="Timezone" value={form.timezone} onChange={(e) => set("timezone", e.target.value)} hint="IANA name, e.g. America/Chicago" />
            <TextField label="Language" value={form.language} onChange={(e) => set("language", e.target.value)} />
          </div>
          <div className="fld-row" style={{ marginTop: 10 }}>
            <SelectField label="Week starts on" value={form.weekStart} onChange={(e) => set("weekStart", e.target.value as WorkspaceSettingsData["weekStart"])}>
              <option value="Monday">Monday</option>
              <option value="Sunday">Sunday</option>
            </SelectField>
            <SelectField label="Default client tier" value={form.defaultTier} onChange={(e) => set("defaultTier", e.target.value as WorkspaceSettingsData["defaultTier"])} hint="Pre-selected when a new client is created.">
              <option value="Starter">Starter</option>
              <option value="Growth">Growth</option>
              <option value="Scale">Scale</option>
            </SelectField>
            <TextField label="Brand colour" value={form.brandColor} onChange={(e) => set("brandColor", e.target.value)} hint="Hex, e.g. #432B52" />
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 16, alignItems: "center" }}>
            <button type="submit" className="primary-btn" disabled={save.isPending}>
              {save.isPending ? "Saving…" : "Save workspace settings"}
            </button>
            {q.data && form !== q.data && JSON.stringify(form) !== JSON.stringify(q.data) ? (
              <button type="button" className="ghostbtn" onClick={() => setForm(q.data!)}>Discard changes</button>
            ) : null}
          </div>
        </form>
      )}
    </QueryGuard>
  );
}
