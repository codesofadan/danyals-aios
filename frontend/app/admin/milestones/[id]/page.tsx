import TopBar from "@/components/TopBar";
import "../milestones.css";
import MilestoneDetail from "@/components/milestones/MilestoneDetail";

export default async function MilestonePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <>
      <TopBar eyebrow="Clients · Milestones" title="Project" hideSearch />
      <div className="main-pad" style={{ padding: "0 26px 26px" }}>
        <MilestoneDetail id={id} />
      </div>
    </>
  );
}
