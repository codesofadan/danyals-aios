import TopBar from "@/components/TopBar";
import ClientGrowth from "@/components/clients/ClientGrowth";
import SubscriptionStatus from "@/components/clients/SubscriptionStatus";
import ClientDirectory from "@/components/clients/ClientDirectory";
import SupportActivity from "@/components/clients/SupportActivity";

export default function ClientInfo() {
  return (
    <>
      <TopBar
        eyebrow="Agency · Client Management"
        title="Client Info"
        searchPlaceholder="Search clients, contacts, tickets…"
      />

      <div className="row">
        <ClientGrowth />
        <SubscriptionStatus />
      </div>

      <ClientDirectory />

      <div className="row-single">
        <SupportActivity />
      </div>
    </>
  );
}
