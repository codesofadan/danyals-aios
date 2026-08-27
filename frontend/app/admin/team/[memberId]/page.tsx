import TopBar from "@/components/TopBar";
import MemberDetail from "@/components/team/MemberDetail";

export default async function MemberPage({ params }: { params: Promise<{ memberId: string }> }) {
  const { memberId } = await params;
  return (
    <>
      <TopBar eyebrow="Team" title="Member" hideSearch />
      <div className="main-pad" style={{ padding: "0 26px 26px" }}>
        <MemberDetail memberId={memberId} />
      </div>
    </>
  );
}
