"use client";

import TopBar from "@/components/TopBar";
import MyAccess from "@/components/portal/MyAccess";
import { usePortal } from "@/components/portal/PortalContext";

export default function AccessPage() {
  const { me } = usePortal();
  return (
    <>
      <TopBar eyebrow="Team Portal · Access" title="My Access" searchPlaceholder="Search features…" />
      <div className="tw portal">
        <section className="card">
          <MyAccess me={me} />
        </section>
      </div>
    </>
  );
}
