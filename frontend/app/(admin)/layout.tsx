import Sidebar from "@/components/Sidebar";
import AuthGuard from "@/components/auth/AuthGuard";

// Admin / super-admin shell — the full agency dashboard. Team members
// never see this; their portal has its own shell under /portal. Gated: a
// valid "admin" session is required or you're bounced to the login page.
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard role="admin">
      <Sidebar />
      <main className="main">{children}</main>
    </AuthGuard>
  );
}
