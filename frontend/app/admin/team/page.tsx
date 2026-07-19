import TopBar from "@/components/TopBar";
import TeamStats from "@/components/team/TeamStats";
import TeamWorkspace from "@/components/team/TeamWorkspace";

export default function TeamManagement() {
  return (
    <>
      <TopBar
        eyebrow="Agency · Team Management"
        title="Team Management"
        searchPlaceholder="Search members, tasks, roles…"
      />

      <TeamStats />

      <TeamWorkspace />
    </>
  );
}
