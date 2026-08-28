"use client";

// The DETAIL archetype's frame: identity header + actions + tabbed concerns.
//
// The product had exactly ONE detail route (/admin/audit/[auditId]) while the
// backend exposes per-entity endpoints for clients, tasks, leads, members,
// milestones and content jobs - everything else was a list plus a modal. This
// shell is what makes adding a detail page mechanical: identity at the top,
// actions in the header (never buried in a tab), one tab per concern, the URL
// owning the tab so any view is linkable.

import type { ReactNode } from "react";
import TabBar, { useUrlTab, type TabDef } from "./TabBar";

export default function DetailShell({
  eyebrow,
  title,
  statusPill,
  facts,
  actions,
  tabs,
  children,
}: {
  /** The entity kind: "Content job", "Client". */
  eyebrow: string;
  title: string;
  /** Rendered beside the title - use the status pill WITH its meaning. */
  statusPill?: ReactNode;
  /** Key facts as label/value pairs, rendered as a compact strip. */
  facts?: { label: string; value: ReactNode }[];
  actions?: ReactNode;
  tabs: TabDef[];
  /** Renders the ACTIVE tab's content. */
  children: (activeTab: string) => ReactNode;
}) {
  const [active, setTab] = useUrlTab(tabs);
  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: "var(--s-7)",
          flexWrap: "wrap",
        }}
      >
        <div>
          <div
            style={{
              fontSize: "var(--fs-xs)",
              fontWeight: 700,
              letterSpacing: ".08em",
              textTransform: "uppercase",
              color: "var(--muted)",
            }}
          >
            {eyebrow}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "var(--s-5)", flexWrap: "wrap" }}>
            <h1 style={{ margin: 0, fontSize: "var(--fs-xl)", fontWeight: 800 }}>{title}</h1>
            {statusPill}
          </div>
          {facts && facts.length > 0 ? (
            <div
              style={{
                display: "flex",
                gap: "var(--s-8)",
                flexWrap: "wrap",
                marginTop: "var(--s-4)",
              }}
            >
              {facts.map((f) => (
                <div key={f.label}>
                  <div style={{ fontSize: "var(--fs-xs)", color: "var(--muted)" }}>{f.label}</div>
                  <div style={{ fontSize: "var(--fs-sm)", fontWeight: 700 }}>{f.value}</div>
                </div>
              ))}
            </div>
          ) : null}
        </div>
        {actions ? <div style={{ display: "flex", gap: "var(--s-4)" }}>{actions}</div> : null}
      </div>
      <div style={{ margin: "var(--s-7) 0" }}>
        <TabBar tabs={tabs} active={active} onSelect={setTab} />
      </div>
      <div role="tabpanel">{children(active)}</div>
    </div>
  );
}
