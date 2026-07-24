import Sidebar from "@/components/Sidebar";
import AuthGuard from "@/components/auth/AuthGuard";
import SpendHaltBanner from "@/components/SpendHaltBanner";

// Admin / super-admin shell — the full agency dashboard. Team members
// never see this; their portal has its own shell under /team. Gated: a
// valid "admin" session is required or you're bounced to the login page.
// SpendHaltBanner surfaces the global API-spend kill-switch on every admin page.
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard role="admin">
      <Sidebar />
      <main className="main">
        <SpendHaltBanner />
        {children}
      </main>
    </AuthGuard>
  );
}
