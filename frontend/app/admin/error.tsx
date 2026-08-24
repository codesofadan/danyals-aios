"use client";

// Error boundary for the admin dashboard. Keeps `admin/layout.tsx` — and therefore the
// navigation — alive, so a crash on one screen does not strand the user. See
// `components/ui/SegmentError.tsx` for why per-area boundaries exist at all.

import SegmentError from "@/components/ui/SegmentError";

export default function AdminError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <SegmentError
      area="admin"
      headline="This screen failed to render."
      detail="The failure is in displaying this screen, not in the underlying records. The rest of the dashboard is unaffected — the sidebar still works."
      error={error}
      reset={reset}
    />
  );
}
