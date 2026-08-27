import AuditDetail from "@/components/audit/AuditDetail";
import "../audit.css";
import "./altitude.css";

export const metadata = { title: "Audit · AIOS" };

export default async function AuditDetailPage({
  params,
}: {
  params: Promise<{ auditId: string }>;
}) {
  const { auditId } = await params;
  return <AuditDetail auditId={auditId} />;
}
