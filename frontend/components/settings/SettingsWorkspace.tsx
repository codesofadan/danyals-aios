"use client";

import AccountSettings from "./AccountSettings";

export default function SettingsWorkspace() {
  return (
    <section className="card settings-card">
      <div className="card-h">
        <div>
          <div className="ct">Settings</div>
          <div className="cs">Your account — profile &amp; notification preferences.</div>
        </div>
      </div>

      <div className="tw-panel">
        <AccountSettings />
      </div>
    </section>
  );
}
