import { Suspense } from "react";
import TopBar from "@/components/TopBar";
import "../content.css";
import NewContentFlow from "@/components/content/flow/NewContentFlow";

export default function NewContentPage() {
  return (
    <>
      <TopBar eyebrow="Content" title="New content" hideSearch />
      <div className="main-pad" style={{ padding: "0 26px 26px" }}>
        {/* useSearchParams needs a Suspense boundary to stay prerenderable. */}
        <Suspense fallback={<div style={{ padding: 40, color: "var(--muted)" }}>Loading…</div>}>
          <NewContentFlow />
        </Suspense>
      </div>
    </>
  );
}
