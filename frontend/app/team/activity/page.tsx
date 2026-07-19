"use client";

import TopBar from "@/components/TopBar";
import MyActivity from "@/components/portal/MyActivity";
import { usePortal } from "@/components/portal/PortalContext";

export default function ActivityPage() {
  const { me, myTasks } = usePortal();
  return (
    <>
      <TopBar eyebrow="Team Portal · Activity" title="Activity" searchPlaceholder="Search activity…" />
      <div className="tw portal">
        <section className="card">
          <MyActivity me={me} myTasks={myTasks} />
        </section>
      </div>
    </>
  );
}
