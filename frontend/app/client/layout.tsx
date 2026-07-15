import type { Metadata } from "next";
import { ClientProvider } from "@/components/client/ClientContext";
import ClientSidebar from "@/components/client/ClientSidebar";
import AuthGuard from "@/components/auth/AuthGuard";
import "./client.css";

export const metadata: Metadata = {
  title: "AIOS · Client Dashboard",
  description: "Your SEO dashboard — reports, graphs, milestones and requests. Provisioned by your agency.",
};

// The client-facing dashboard — a completely separate shell from both the
// admin dashboard and the team portal. Its own sidebar, its own signed-in
// client identity, and a data scope limited to exactly what the admin
// granted. Admin and team modules are never reachable from here.
export default function ClientLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard role="client">
      <ClientProvider>
        <ClientSidebar />
        <main className="main">{children}</main>
      </ClientProvider>
    </AuthGuard>
  );
}
