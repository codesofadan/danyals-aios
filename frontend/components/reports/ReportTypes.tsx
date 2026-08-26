"use client";

import { DATASET_META } from "@/lib/reports";
import { useReportTypes } from "@/lib/hooks/reports";
import EmptyState from "@/components/ui/EmptyState";
import QueryGuard from "@/components/ui/QueryGuard";

// The datasets the sync writes into every client workbook, read live from
// GET /reports/types.
//
// The card used to assert "3 tabs" as a literal in the header while the body
// mapped over whatever the endpoint returned — so a failed or empty read printed
// a confident "3 tabs" over nothing at all, and a fourth dataset would have gone
// uncounted. The count is derived now, and it is shown ONLY when the list is
// really loaded: "0 tabs" beside a failed read is the same untruth pointing the
// other way.
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
          {typesQ.data && (
            <span className="pill-tag">
              <span className="material-symbols-rounded">description</span>
              {reportTypes.length} tab{reportTypes.length === 1 ? "" : "s"}
            </span>
          )}
        </div>
      </div>

      <QueryGuard queries={[typesQ]} label="the dataset list" minHeight={140}>
        {reportTypes.length === 0 ? (
          <EmptyState
            icon="description"
            title="No datasets configured"
            hint="Nothing is being written to the client workbooks yet."
          />
        ) : (
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
        )}
      </QueryGuard>

      <div className="rp-conn-foot">
        <span className="material-symbols-rounded">palette</span>
        The reporting engine applies each agency&apos;s branding to the shared sheet.
      </div>
    </section>
  );
}
