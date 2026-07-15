"use client";

import { useEffect, useRef, useState } from "react";
import anime from "animejs";
import { offpageKpis } from "@/lib/offpage";
import BacklinksTab from "./BacklinksTab";
import CitationsTab from "./CitationsTab";
import Web2Tab from "./Web2Tab";
import BacklinkScatter from "@/components/charts/BacklinkScatter";

type TabKey = "backlinks" | "citations" | "web2";

const TABS: { key: TabKey; label: string; icon: string }[] = [
  { key: "backlinks", label: "Backlinks", icon: "hub" },
  { key: "citations", label: "Citations / NAP", icon: "storefront" },
  { key: "web2", label: "Web 2.0", icon: "rocket_launch" },
];

type Kpi = { icon: string; label: string; value: number; delta: string; dir: "up" | "down"; note: string; hero?: boolean };

const KPIS: Kpi[] = [
  { icon: "public", label: "Referring domains", value: offpageKpis.referringDomains, delta: "5.2%", dir: "up", note: "live profile", hero: true },
  { icon: "add_link", label: "New links (30d)", value: offpageKpis.newLinks30d, delta: "18", dir: "up", note: "DataForSEO alerts" },
  { icon: "link_off", label: "Lost links (30d)", value: offpageKpis.lostLinks30d, delta: "6", dir: "down", note: "flagged for recovery" },
  { icon: "gpp_bad", label: "Toxic / spam flagged", value: offpageKpis.toxicFlagged, delta: "2", dir: "down", note: "in disavow review" },
];

function useCountUp(target: number) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      node.textContent = target.toLocaleString();
      return;
    }
    const obj = { n: 0 };
    const a = anime({
      targets: obj, n: target, duration: 1400, easing: "easeOutExpo",
      update: () => { node.textContent = Math.round(obj.n).toLocaleString(); },
    });
    return () => a.pause();
  }, [target]);
  return ref;
}

function KpiTile({ k }: { k: Kpi }) {
  const ref = useCountUp(k.value);
  return (
    <div className={k.hero ? "kpi hero" : "kpi"}>
      <div className="ic"><span className="material-symbols-rounded">{k.icon}</span></div>
      <div className="lab">{k.label}</div>
      <div className="val"><span ref={ref}>0</span></div>
      <div className="sub">
        <span className={`delta ${k.dir}`}>
          <span className="material-symbols-rounded">{k.dir === "up" ? "trending_up" : "trending_down"}</span>
          {k.delta}
        </span>{" "}
        {k.note}
      </div>
    </div>
  );
}

export default function OffpageWorkspace() {
  const [tab, setTab] = useState<TabKey>("backlinks");

  return (
    <>
      <section className="kpis">
        {KPIS.map((k) => <KpiTile key={k.label} k={k} />)}
      </section>

      {/* Quality gate — the off-page contract: human-approved, diversified, never spam. */}
      <section className="op-gate">
        <div className="op-gate-ic"><span className="material-symbols-rounded">verified_user</span></div>
        <div className="op-gate-body">
          <div className="op-gate-t">Quality gate &amp; diversification</div>
          <div className="op-gate-d">
            Every placement is <b>human-approved</b> before it ships. Platforms and anchors are deliberately
            varied — <b>never link spam</b>. Toxic inbound links are surfaced for a disavow review, not auto-actioned.
          </div>
        </div>
        <div className="op-gate-chips">
          <span className="op-gchip"><span className="material-symbols-rounded">how_to_reg</span>Manual approval</span>
          <span className="op-gchip"><span className="material-symbols-rounded">shuffle</span>Diversified anchors</span>
          <span className="op-gchip"><span className="material-symbols-rounded">block</span>No link spam</span>
        </div>
      </section>

      <section className="card">
        <div className="card-h">
          <div>
            <div className="ct">Off-page Workspace</div>
            <div className="cs">Backlink monitoring, local citations &amp; Web 2.0 placements — one place.</div>
          </div>
          <div className="tools">
            <div className="seg" role="tablist" aria-label="Off-page sections">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  role="tab"
                  aria-selected={tab === t.key}
                  className={tab === t.key ? "on" : undefined}
                  onClick={() => setTab(t.key)}
                >
                  <span className="material-symbols-rounded op-tab-ic">{t.icon}</span>
                  {t.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div role="tabpanel">
          {tab === "backlinks" && <BacklinksTab />}
          {tab === "citations" && <CitationsTab />}
          {tab === "web2" && <Web2Tab />}
        </div>
      </section>

      {tab === "backlinks" && (
        <div className="row-single">
          <BacklinkScatter />
        </div>
      )}
    </>
  );
}
