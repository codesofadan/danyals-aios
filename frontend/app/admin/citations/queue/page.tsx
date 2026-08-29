"use client";

import TopBar from "@/components/TopBar";
import "../../web2/offpage.css";
import CitationQueue from "@/components/offpage/CitationQueue";

// The human work queue. This replaces `tools/finish_citation.py` — a desktop script that
// read an exported JSON of every directory login for a campaign and printed one shared
// password for all of them. Credentials left the platform as a file, and the work it did
// was invisible: nothing recorded who did what, how long it took, or whether it worked.
export default function CitationQueuePage() {
  return (
    <>
      <TopBar
        eyebrow="Admin · SEO Engine"
        title="Citation queue"
        searchPlaceholder="Search the queue…"
      />
      <section className="card">
        <div className="card-h">
          <div>
            <div className="ct">Work one listing at a time</div>
            <div className="cs">
              Every field is pre-filled and the form is one click away. Finishing requires
              the listing&apos;s public URL — we fetch it and check the business is on the
              page before it counts as live.
            </div>
          </div>
        </div>
        <CitationQueue />
      </section>
    </>
  );
}
