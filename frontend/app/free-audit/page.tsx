import type { Metadata } from "next";
import FreeAuditFlow from "@/components/free-audit/FreeAuditFlow";
import "./freeaudit.css";

export const metadata: Metadata = {
  title: "Free SEO Audit · Xegents",
  description: "Get a free, instant SEO audit of your website — technical health and on-page fixes, scored and explained.",
};

// Public, shareable lead-gen page — standalone, outside every app shell
// (like /login). Prospects land here, run a free audit, and are funneled
// toward the agency's Fiverr gigs. All simulated client-side until the
// FastAPI /audits backend exists.
export default function FreeAuditPage() {
  return <FreeAuditFlow />;
}
