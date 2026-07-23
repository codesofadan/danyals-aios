import type { Metadata } from "next";
import FreeAuditFlow from "@/components/free-audit/FreeAuditFlow";
import "./freeaudit.css";

export const metadata: Metadata = {
  title: "Free SEO Audit · AIOS",
  description: "Get a free, instant SEO audit of your website — technical health and on-page fixes, scored and explained.",
};

// Public, shareable lead-gen page — standalone, outside every app shell
// (like /login). Prospects land here, run a real free audit against the
// FastAPI public funnel (POST /api/v1/public/audits + token poll), and are
// funneled toward the agency's Fiverr gigs.
export default function FreeAuditPage() {
  return <FreeAuditFlow />;
}
