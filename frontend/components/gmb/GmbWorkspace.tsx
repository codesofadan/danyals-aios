"use client";

// GMB workspace: composer + policy-checked review list. Mirrors ContentWorkspace.
// Generation is synchronous server-side (a keyless/dial-off deploy degrades to a
// stored draft); publishing to Google is dormant and degrades honestly.

import { useState } from "react";
import {
  useCreateGmbPost,
  useGmbPosts,
  useGmbStats,
  usePublishGmbPost,
  useReviewGmbPost,
  type CreateGmbPostInput,
} from "@/lib/hooks/gmb";
import type { GmbPublishResult } from "@/lib/gmb";
import GmbComposer from "./GmbComposer";
import GmbReview from "./GmbReview";

function Kpi({ label, value }: { label: string; value: number }) {
  return (
    <div className="gmb-kpi">
      <div className="gmb-kpi-n">{value}</div>
      <div className="gmb-kpi-l">{label}</div>
    </div>
  );
}

export default function GmbWorkspace() {
  const postsQ = useGmbPosts();
  const statsQ = useGmbStats();
  const createPost = useCreateGmbPost();
  const reviewPost = useReviewGmbPost();
  const publishPost = usePublishGmbPost();

  const posts = postsQ.data ?? [];
  const stats = statsQ.data;
  const [publishResult, setPublishResult] = useState<GmbPublishResult | null>(null);

  function handleCreate(input: CreateGmbPostInput) {
    createPost.mutate(input);
  }
  function handleReview(code: string, action: "approve" | "reject") {
    reviewPost.mutate({ code, action });
  }
  function handlePublish(code: string) {
    publishPost.mutate(code, { onSuccess: (res) => setPublishResult(res) });
  }

  const createErr = createPost.error instanceof Error ? createPost.error.message : null;
  const reviewErr = reviewPost.error instanceof Error ? reviewPost.error.message : null;
  const actionErr = createErr ?? reviewErr;
  const busy = reviewPost.isPending || publishPost.isPending;

  return (
    <>
      {postsQ.isError && (
        <div className="cs" role="alert" style={{ color: "var(--warn)", marginBottom: 8 }}>
          Couldn&apos;t load GMB posts — {(postsQ.error as Error)?.message ?? "try again"}.
        </div>
      )}
      {actionErr && (
        <div className="cs" role="alert" style={{ color: "var(--warn)", marginBottom: 8 }}>
          {createErr ? "Couldn't generate the post" : "Couldn't apply the review"} — {actionErr}.
        </div>
      )}

      {stats && (
        <div className="gmb-kpis">
          <Kpi label="Total posts" value={stats.total} />
          <Kpi label="Awaiting review" value={stats.awaitingReview} />
          <Kpi label="Approved" value={stats.approved} />
          <Kpi label="Needs fixes" value={stats.needsFix} />
        </div>
      )}

      <div className="gmb-grid">
        <GmbComposer onCreate={handleCreate} pending={createPost.isPending} />
        <GmbReview
          posts={posts}
          onReview={handleReview}
          onPublish={handlePublish}
          publishResult={publishResult}
          busy={busy}
        />
      </div>
    </>
  );
}
