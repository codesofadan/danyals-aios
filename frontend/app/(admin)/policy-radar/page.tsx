import TopBar from "@/components/TopBar";
import "./policy.css";
import PolicyStats from "@/components/policy/PolicyStats";
import PolicyWorkspace from "@/components/policy/PolicyWorkspace";

export default function PolicyRadar() {
  return (
    <>
      <TopBar
        eyebrow="Intelligence · Policy Radar"
        title="Policy Radar"
        searchPlaceholder="Search sources, KB entries, recommendations…"
      />

      <PolicyStats />

      <PolicyWorkspace />
    </>
  );
}
