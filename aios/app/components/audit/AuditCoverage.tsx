"use client";

import { auditTypes, financialAudit } from "@/lib/audit";

export default function AuditCoverage() {
  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Audit Coverage</div>
          <div className="cs">What the engine grades on a single URL — no logins required</div>
        </div>
        <div className="tools">
          <span className="panel-hint"><span className="material-symbols-rounded">bolt</span>Runs behind a cost gate</span>
        </div>
      </div>

      <div className="au-cov">
        {auditTypes.map((t) => (
          <div key={t.key} className="au-cov-card">
            <div className="au-cov-top">
              <span className="au-cov-ic" style={{ color: t.color, background: `color-mix(in srgb, ${t.color} 16%, transparent)` }}>
                <span className="material-symbols-rounded">{t.icon}</span>
              </span>
              <span className={`pill-tag sm ${t.paid ? "warn" : "ok"}`}>
                <span className="material-symbols-rounded">{t.paid ? "workspace_premium" : "check_circle"}</span>
                {t.paid ? "Paid data" : "Free tier"}
              </span>
            </div>
            <div className="au-cov-name">{t.label}</div>
            <div className="au-cov-blurb">{t.blurb}</div>
            <ul className="au-cov-list">
              {t.checks.map((c) => (
                <li key={c}><span className="material-symbols-rounded">done</span>{c}</li>
              ))}
            </ul>
          </div>
        ))}

        {/* Phase-2 locked card */}
        <div className="au-cov-card locked">
          <div className="au-cov-top">
            <span className="au-cov-ic muted"><span className="material-symbols-rounded">{financialAudit.icon}</span></span>
            <span className="au-cov-lock"><span className="material-symbols-rounded">lock</span>Phase 2</span>
          </div>
          <div className="au-cov-name">{financialAudit.label}</div>
          <div className="au-cov-blurb">{financialAudit.blurb}</div>
          <ul className="au-cov-list">
            {financialAudit.checks.map((c) => (
              <li key={c}><span className="material-symbols-rounded">lock</span>{c}</li>
            ))}
          </ul>
          <div className="au-cov-soon">Coming soon</div>
        </div>
      </div>
    </section>
  );
}
