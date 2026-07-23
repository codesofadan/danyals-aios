import TopBar from "@/components/TopBar";
import "./policy.css";
import PolicyWorkspace from "@/components/policy/PolicyWorkspace";

export default function PolicyRadar() {
  return (
    <>
      <TopBar
        eyebrow="Intelligence · Policy Radar"
        title="Policy Radar"
        searchPlaceholder="Search KB entries, recommendations…"
      />

      <PolicyWorkspace />
    </>
  );
}
