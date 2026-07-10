"use client";

import { useState } from "react";
import { workspaceDefaults, TIMEZONES, LANGUAGES, BRAND_COLORS, type WorkspaceSettingsData } from "@/lib/data";
import { SettingGroup, SettingRow, SavedFlash } from "./controls";

type LogFn = (action: string, target: string, meta?: string) => void;

export default function WorkspaceSettings({ onLog }: { onLog: LogFn }) {
  const [w, setW] = useState<WorkspaceSettingsData>(workspaceDefaults);
  const [saved, setSaved] = useState(false);

  function set<K extends keyof WorkspaceSettingsData>(key: K, value: WorkspaceSettingsData[K]) {
    setW((prev) => ({ ...prev, [key]: value }));
  }

  function save() {
    setSaved(true);
    setTimeout(() => setSaved(false), 1800);
    onLog("updated workspace settings", w.agencyName, "Workspace");
  }

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">tune</span>
          Agency identity, regional defaults &amp; branding
        </div>
      </div>

      <SettingGroup title="General" icon="corporate_fare">
        <div className="fld-grid">
          <div className="fld"><label htmlFor="ws-name">Agency name</label><input id="ws-name" value={w.agencyName} onChange={(e) => set("agencyName", e.target.value)} /></div>
          <div className="fld"><label htmlFor="ws-mail">Support email</label><input id="ws-mail" type="email" value={w.supportEmail} onChange={(e) => set("supportEmail", e.target.value)} /></div>
          <div className="fld">
            <label htmlFor="ws-tz">Timezone</label>
            <select id="ws-tz" value={w.timezone} onChange={(e) => set("timezone", e.target.value)}>
              {TIMEZONES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div className="fld">
            <label htmlFor="ws-lang">Language</label>
            <select id="ws-lang" value={w.language} onChange={(e) => set("language", e.target.value)}>
              {LANGUAGES.map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
          </div>
        </div>
      </SettingGroup>

      <SettingGroup title="Defaults" icon="settings_suggest">
        <SettingRow icon="calendar_view_week" title="Week starts on" desc="First day of the week across dashboards & reports.">
          <div className="seg">
            {(["Monday", "Sunday"] as const).map((d) => (
              <button key={d} className={w.weekStart === d ? "on" : undefined} onClick={() => set("weekStart", d)}>{d}</button>
            ))}
          </div>
        </SettingRow>
        <SettingRow icon="workspace_premium" title="Default subscription tier" desc="Pre-selected plan when onboarding a new client.">
          <select className="mini-select w" value={w.defaultTier} onChange={(e) => set("defaultTier", e.target.value as WorkspaceSettingsData["defaultTier"])}>
            {(["Starter", "Growth", "Scale"] as const).map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </SettingRow>
        <SettingRow icon="palette" title="Brand accent" desc="Primary accent used across the workspace UI.">
          <div className="swatches">
            {BRAND_COLORS.map((c) => (
              <button
                key={c}
                className={`swatch${w.brandColor === c ? " on" : ""}`}
                style={{ background: c }}
                onClick={() => set("brandColor", c)}
                aria-label={`Brand color ${c}`}
                aria-pressed={w.brandColor === c}
              />
            ))}
          </div>
        </SettingRow>
      </SettingGroup>

      <div className="set-actions end">
        <SavedFlash show={saved} />
        <button className="primary-btn" onClick={save}>
          <span className="material-symbols-rounded">save</span>Save changes
        </button>
      </div>

      <div className="danger-zone">
        <div className="dz-h">
          <span className="material-symbols-rounded">warning</span>
          Danger zone
        </div>
        <div className="set-list">
          <SettingRow danger icon="restart_alt" title="Reset all settings to defaults" desc="Restore every setting on this page to its shipped default. Credentials are unaffected.">
            <button className="danger-btn" onClick={() => { setW(workspaceDefaults); onLog("reset workspace settings to defaults", "Workspace", "Danger zone"); }}>Reset</button>
          </SettingRow>
          <SettingRow danger icon="delete_forever" title="Purge activity log" desc="Permanently delete the recorded audit trail of admin actions.">
            <button className="danger-btn" onClick={() => onLog("purged the activity log", "Activity log", "Danger zone")}>Purge</button>
          </SettingRow>
        </div>
      </div>
    </div>
  );
}
