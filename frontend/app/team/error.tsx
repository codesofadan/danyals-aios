"use client";

// Error boundary for the team portal. Keeps `team/layout.tsx` — and therefore the
// navigation — alive, so a crash on one screen does not strand the user. See
// `components/ui/SegmentError.tsx` for why per-area boundaries exist at all.

import SegmentError from "@/components/ui/SegmentError";

export default function TeamError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <SegmentError
      area="team"
      headline="This screen failed to render."
      detail="Your queue and its state are unchanged. The failure is in drawing this page; the rest of the portal still works."
      error={error}
      reset={reset}
    />
  );
}
