import TopBar from "@/components/TopBar";
import StatTiles from "@/components/StatTiles";
import AuditVolumeChart from "@/components/charts/AuditVolumeChart";
import ClientProgress from "@/components/charts/ClientProgress";
import TrafficChart from "@/components/charts/TrafficChart";
import TeamTracking from "@/components/charts/TeamTracking";

export default function CommandCenter() {
  return (
    <>
      <TopBar
        eyebrow="SEO Automation · Agency Overview"
        title="Command Center"
        searchPlaceholder="Search clients, sites, audits…"
      />

      <StatTiles />

      <div className="row">
        <AuditVolumeChart />
        <ClientProgress />
      </div>

      <div className="row b">
        <TrafficChart />
        <TeamTracking />
      </div>
    </>
  );
}
