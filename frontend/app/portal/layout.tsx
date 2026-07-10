import type { Metadata } from "next";
import { PortalProvider } from "@/components/portal/PortalContext";
import TeamSidebar from "@/components/portal/TeamSidebar";
import "./portal.css";

export const metadata: Metadata = {
  title: "AIOS · Team Portal",
  description: "Your workspace — the tasks assigned to you, deliverables, review gate and access.",
};

// The team member portal — a completely separate shell from the admin
// dashboard. Its own sidebar, its own signed-in identity, its own data
// scope. Admin modules are never reachable from here.
export default function PortalLayout({ children }: { children: React.ReactNode }) {
  return (
    <PortalProvider>
      <TeamSidebar />
      <main className="main">{children}</main>
    </PortalProvider>
  );
}
