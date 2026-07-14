import Sidebar from "@/components/Sidebar";

// Admin / super-admin shell — the full agency dashboard. Team members
// never see this; their portal has its own shell under /portal.
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Sidebar />
      <main className="main">{children}</main>
    </>
  );
}
