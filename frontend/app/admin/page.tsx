"use client";

import TopBar from "@/components/TopBar";
import StatTiles from "@/components/StatTiles";
import CommandDigest from "@/components/overview/CommandDigest";
import SpendSnapshot from "@/components/overview/SpendSnapshot";
import SiteAnalyticsCard from "@/components/overview/SiteAnalyticsCard";
import AuditVolumeChart from "@/components/charts/AuditVolumeChart";
import ClientProgress from "@/components/charts/ClientProgress";
import TrafficChart from "@/components/charts/TrafficChart";
import TeamTracking from "@/components/charts/TeamTracking";
import { useCommandCenter } from "@/lib/hooks/commandCenter";

export default function CommandCenter() {
  // One aggregate read (GET /command-center) feeds every overview surface.
  const { data, isLoading, isError, error } = useCommandCenter();

  return (
    <>
      <TopBar
        title="Admin Dashboard"
        searchPlaceholder="Search clients, sites, audits…"
      />

      {isLoading && (
        <section className="card">
          <div className="card-h">
            <div>
              <div className="ct">Loading command center…</div>
              <div className="cs">Fetching audits, clients, team and spend</div>
            </div>
          </div>
        </section>
      )}

      {isError && !isLoading && (
        <section className="card">
          <div className="card-h">
            <div>
              <div className="ct">Couldn&apos;t load the dashboard</div>
              <div className="cs">{(error as Error)?.message ?? "Please try again."}</div>
            </div>
          </div>
        </section>
      )}

      {data && (
        <>
          <StatTiles tiles={data.statTiles} />

          <div className="row b">
            <CommandDigest digest={data.digest} />
            <SpendSnapshot spend={data.spend} />
          </div>

          <div className="row-single">
            <SiteAnalyticsCard gsc={data.gsc} ga4={data.ga4} />
          </div>

          <div className="row">
            <AuditVolumeChart audits={data.audits} />
            <ClientProgress clients={data.clients} />
          </div>

          <div className="row b">
            <TrafficChart traffic={data.traffic.points} />
            <TeamTracking team={data.team} />
          </div>
        </>
      )}
    </>
  );
}
