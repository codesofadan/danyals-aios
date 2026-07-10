import { TIERS, TIER_BY_KEY, type TierClient, type TierKey } from "@/lib/tiers";

type Props = {
  clients: TierClient[];
  onSwitch: (id: string, tier: TierKey) => void;
};

// Per-client tier assignment. The segmented switcher re-dials the preset
// and the parent recomputes monthly cost + KPI counts in local state.
export default function ClientAssignment({ clients, onSwitch }: Props) {
  return (
    <div className="tbl-wrap tr-assign">
      <table className="tbl">
        <thead>
          <tr>
            <th>Client</th>
            <th>Current tier</th>
            <th className="num">Monthly cost</th>
            <th>Switch preset</th>
          </tr>
        </thead>
        <tbody>
          {clients.map((c) => {
            const tier = TIER_BY_KEY[c.tier];
            return (
              <tr key={c.id}>
                <td>
                  <div className="tr-cli">
                    <span className="tr-av" style={{ background: c.c }}>{c.init}</span>
                    <div>
                      <div className="tr-cli-name">{c.cn}</div>
                      <div className="tr-cli-sub">{c.industry}</div>
                    </div>
                  </div>
                </td>
                <td>
                  <span
                    className="tier-chip tr-tier-pill"
                    style={{ color: tier.c, background: `${tier.c}1f` }}
                  >
                    {tier.name}
                  </span>
                </td>
                <td className="num tr-cost">
                  {tier.price === 0 ? <span className="tr-free">$0</span> : `$${tier.price}`}
                </td>
                <td>
                  <div className="seg tr-seg" role="group" aria-label={`Set tier for ${c.cn}`}>
                    {TIERS.map((t) => (
                      <button
                        key={t.key}
                        className={c.tier === t.key ? "on" : ""}
                        aria-pressed={c.tier === t.key}
                        onClick={() => onSwitch(c.id, t.key)}
                        style={c.tier === t.key ? { background: t.c } : undefined}
                      >
                        {t.key === "free" ? "Free" : t.key === "semi" ? "Semi" : "Fully"}
                      </button>
                    ))}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
