"use client";

import TopBar from "@/components/TopBar";
import DeliverPanel from "@/components/portal/DeliverPanel";
import { usePortal } from "@/components/portal/PortalContext";

export default function DeliverPage() {
  const { myTasks, advance } = usePortal();
  return (
    <>
      <TopBar eyebrow="Team Portal · Run & Deliver" title="Deliver" searchPlaceholder="Search jobs…" />
      <div className="tw portal">
        <section className="card">
          <DeliverPanel tasks={myTasks} onAdvance={advance} />
        </section>
      </div>
    </>
  );
}
