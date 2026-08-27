import TopBar from "@/components/TopBar";
import "../content.css";
import ContentJobDetail from "@/components/content/ContentJobDetail";

export default async function ContentJobPage({
  params,
}: {
  params: Promise<{ code: string }>;
}) {
  const { code } = await params;
  return (
    <>
      <TopBar eyebrow="Work · Content" title={code} hideSearch />
      <div className="main-pad" style={{ padding: "0 26px 26px" }}>
        <ContentJobDetail code={code} />
      </div>
    </>
  );
}
