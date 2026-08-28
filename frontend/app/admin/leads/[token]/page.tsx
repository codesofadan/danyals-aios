import TopBar from "@/components/TopBar";
import "../leads.css";
import LeadDetail from "@/components/leads/LeadDetail";

export default async function LeadPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return (
    <>
      <TopBar eyebrow="Clients · Pipeline" title="Lead" hideSearch />
      <div className="main-pad" style={{ padding: "0 26px 26px" }}>
        <LeadDetail token={token} />
      </div>
    </>
  );
}
