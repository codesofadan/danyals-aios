"use client";

// Error boundary for the client portal. Keeps `client/layout.tsx` — and therefore the
// navigation — alive, so a crash on one screen does not strand the user. See
// `components/ui/SegmentError.tsx` for why per-area boundaries exist at all.

import SegmentError from "@/components/ui/SegmentError";

export default function ClientError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <SegmentError
      area="client"
      headline="This page didn't load."
      detail="Your reports, audits and requests are safe — this is a display problem on our side, not a change to your data. Use the menu to move to another page while we look into it."
      error={error}
      reset={reset}
    />
  );
}
