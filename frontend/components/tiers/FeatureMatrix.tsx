import { featureAreas, TIERS, MODE_META } from "@/lib/tiers";

// Feature-area × tier matrix — the cost dial expressed as presets.
// Rows are the 7 gated areas; cells show the delivery mode per tier.
export default function FeatureMatrix() {
  return (
    <div className="tbl-wrap tr-matrix">
      <table className="tbl">
        <thead>
          <tr>
            <th>Feature area</th>
            {TIERS.map((t) => (
              <th key={t.key} className="tr-mcol">
                <span className="tr-mdot" style={{ background: t.c }} />
                {t.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {featureAreas.map((a) => (
            <tr key={a.id}>
              <td>
                <div className="tr-area">
                  <span className="tr-area-ic"><span className="material-symbols-rounded">{a.icon}</span></span>
                  <div>
                    <div className="tr-area-name"><b>{a.id}</b> · {a.name}</div>
                    <div className="tr-area-desc">{a.desc}</div>
                  </div>
                </div>
              </td>
              {TIERS.map((t) => {
                const m = MODE_META[a.modes[t.key]];
                return (
                  <td key={t.key} className="tr-mcell">
                    <span className={`tr-mode ${m.cls}`}>{m.label}</span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
