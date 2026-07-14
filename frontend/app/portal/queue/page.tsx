"use client";

import TopBar from "@/components/TopBar";
import MyQueue from "@/components/portal/MyQueue";
import { usePortal } from "@/components/portal/PortalContext";

export default function QueuePage() {
  const { myTasks, advance } = usePortal();
  return (
    <>
      <TopBar eyebrow="Team Portal · My Queue" title="My Queue" searchPlaceholder="Search my tasks…" />
      <div className="tw portal">
        <section className="card">
          <MyQueue tasks={myTasks} onAdvance={advance} />
        </section>
      </div>
    </>
  );
}
