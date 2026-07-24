"use client";

// Shared, dashboard-wide "API spend is halted" banner. Mounted once in the admin
// shell so EVERY admin page surfaces the global kill-switch state; individual paid
// CTAs additionally disable themselves off the same `useSpendHalted` signal. Renders
// nothing when spend is live, so it costs nothing in the normal case.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSpendHalted } from "@/lib/hooks/cost";

export default function SpendHaltBanner() {
  const { halted } = useSpendHalted();
  const pathname = usePathname();
  // The Cost Controls page renders its own detailed halt banner + the toggle, so
  // suppress the shared one there to avoid a duplicate.
  if (!halted || pathname?.startsWith("/admin/cost")) return null;

  return (
    <div
      role="alert"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        margin: "0 0 16px",
        padding: "12px 18px",
        borderRadius: 14,
        background: "color-mix(in srgb, var(--crit) 14%, transparent)",
        border: "1px solid color-mix(in srgb, var(--crit) 42%, transparent)",
        color: "var(--crit)",
      }}
    >
      <span className="material-symbols-rounded" style={{ fontSize: 24, flex: "none" }}>
        block
      </span>
      <div style={{ flex: 1, minWidth: 0, fontSize: 13.5, lineHeight: 1.4 }}>
        <b style={{ fontWeight: 800 }}>API spend is halted.</b>{" "}
        <span style={{ color: "color-mix(in srgb, var(--crit) 82%, var(--ink))", fontWeight: 500 }}>
          Every paid feature is paused platform-wide (audits, content, policy ask, keyword
          and rank tools). Paid actions are disabled until spend resumes.
        </span>
      </div>
      <Link
        href="/admin/cost"
        style={{
          flex: "none",
          fontSize: 12,
          fontWeight: 800,
          color: "var(--crit)",
          textDecoration: "none",
          border: "1px solid color-mix(in srgb, var(--crit) 42%, transparent)",
          borderRadius: 9,
          padding: "6px 12px",
          whiteSpace: "nowrap",
        }}
      >
        Manage
      </Link>
    </div>
  );
}
