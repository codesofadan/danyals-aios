"use client";

import { DATASET_META } from "@/lib/reports";
import { useReportTypes } from "@/lib/hooks/reports";

export default function ReportTypes() {
  const typesQ = useReportTypes();
  const reportTypes = typesQ.data ?? [];
  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">What gets synced</div>
          <div className="cs">Three datasets pushed to every workbook</div>
        </div>
        <div className="tools">
          <span className="pill-tag"><span className="material-symbols-rounded">description</span>3 tabs</span>
        </div>
      </div>

      <div className="rp-types">
        {reportTypes.map((r) => {
          const m = DATASET_META[r.key];
          return (
            <div className="rp-type" key={r.key}>
              <div className="rp-type-ic" style={{ color: m.c, background: `${m.c}1f` }}>
                <span className="material-symbols-rounded">{m.icon}</span>
              </div>
              <div className="rp-type-main">
                <div className="rp-type-t">{r.title}</div>
                <div className="rp-type-d">{r.desc}</div>
                <div className="rp-type-cols">
                  <span className="material-symbols-rounded">view_column</span>
                  <span className="rp-mono">{r.columns}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="rp-conn-foot">
        <span className="material-symbols-rounded">palette</span>
        The reporting engine applies each agency&apos;s branding to the shared sheet.
      </div>
    </section>
  );
}
