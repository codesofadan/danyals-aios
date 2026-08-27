"use client";

// Every LIST and WORKSPACE opens the same way: what this screen is, in one
// line, and the module's verb on the right. Before this, each page hand-rolled
// its own header block and half of them had no stated purpose at all - a screen
// that cannot say what it is for makes the operator derive it from the table.

import type { ReactNode } from "react";

export default function PageHeader({
  title,
  purpose,
  actions,
}: {
  title: string;
  /** One honest sentence: what this screen is for. */
  purpose: string;
  /** The module's verb(s): "Run audit", "New content". */
  actions?: ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        gap: "var(--s-7)",
        flexWrap: "wrap",
        marginBottom: "var(--s-7)",
      }}
    >
      <div style={{ maxWidth: 640 }}>
        <h1 style={{ margin: 0, fontSize: "var(--fs-xl)", fontWeight: 800 }}>{title}</h1>
        <p style={{ margin: "var(--s-2) 0 0", fontSize: "var(--fs-sm)", color: "var(--body)" }}>
          {purpose}
        </p>
      </div>
      {actions ? <div style={{ display: "flex", gap: "var(--s-4)" }}>{actions}</div> : null}
    </div>
  );
}
