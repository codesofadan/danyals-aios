import TopBar from "@/components/TopBar";
import ClientDetail from "@/components/clients/ClientDetail";

export default async function ClientPage({ params }: { params: Promise<{ clientId: string }> }) {
  const { clientId } = await params;
  return (
    <>
      <TopBar eyebrow="Clients" title="Client" hideSearch />
      <div className="main-pad" style={{ padding: "0 26px 26px" }}>
        <ClientDetail clientId={clientId} />
      </div>
    </>
  );
}
