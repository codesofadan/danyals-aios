import TopBar from "@/components/TopBar";
import "../../../web2/offpage.css";
import ClientCitationsReport from "@/components/offpage/ClientCitationsReport";

export const metadata = { title: "Citations report · AIOS" };

// The client-facing citations report: fetch-verified live URLs (the deliverable),
// what's still in motion, and what was not built with reasons. Reached from the
// Citations workspace and the campaign board.
export default async function CitationReportPage({
  params,
}: {
  params: Promise<{ clientId: string }>;
}) {
  const { clientId } = await params;
  return (
    <>
      <TopBar
        eyebrow="Admin · SEO Engine"
        title="Citations report"
        searchPlaceholder="Search directories…"
      />
      <ClientCitationsReport clientId={clientId} />
    </>
  );
}
