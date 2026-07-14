"use client";

import TopBar from "@/components/TopBar";
import ReviewCheckpoint from "@/components/portal/ReviewCheckpoint";
import { usePortal } from "@/components/portal/PortalContext";

export default function ReviewPage() {
  const { me, myTasks, review } = usePortal();
  return (
    <>
      <TopBar eyebrow="Team Portal · Review Gate" title="Review" searchPlaceholder="Search review items…" />
      <div className="tw portal">
        <section className="card">
          <ReviewCheckpoint me={me} tasks={myTasks} onReview={review} />
        </section>
      </div>
    </>
  );
}
