"use client";

import type { CSSProperties } from "react";

// Honest "no current data" placeholder. Rendered wherever a view has no real
// data yet — because nothing has been created, the tenant is fresh, or the
// backend/integration for that surface isn't wired. NEVER show fabricated
// sample data in its place: an empty state is the truthful signal that a
// feature is idle or not connected, so we can tell what actually works.
export default function EmptyState({
  icon = "inbox",
  title = "No current data",
  hint,
  compact = false,
  style,
}: {
  icon?: string;
  title?: string;
  hint?: string;
  compact?: boolean;
  style?: CSSProperties;
}) {
  return (
    <div
      role="status"
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        gap: 6,
        padding: compact ? "20px 16px" : "40px 22px",
        color: "var(--mut, #8A85A0)",
        ...style,
      }}
    >
      <span className="material-symbols-rounded" style={{ fontSize: compact ? 26 : 34, opacity: 0.5 }}>
        {icon}
      </span>
      <div style={{ fontWeight: 700, fontSize: compact ? 13 : 14.5, color: "var(--ink, #241015)" }}>{title}</div>
      {hint && <div style={{ fontSize: 12.5, lineHeight: 1.5, maxWidth: 360 }}>{hint}</div>}
    </div>
  );
}
