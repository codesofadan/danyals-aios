"use client";

// ============================================================
// AIOS · team-portal tool ACTIONS — shared primitives
// Small building blocks every per-tool action panel reuses, so the eight panels
// stay visually consistent (card chrome, client picker, result banner) without a
// per-panel copy. Styling reuses the app's existing card / fld / primary-btn
// classes; the result banner is inline-styled so no new global CSS is needed.
// ============================================================

import { ApiError } from "@/lib/api";
import { useClients } from "@/lib/hooks/clients";
import { useSpendHalted } from "@/lib/hooks/cost";

/** The action card shell — a `.card` with a title/subtitle header + an accent icon.
 * A panel that fires a PAID/metered provider call passes `paidAction`: when the
 * agency-global API-spend halt is engaged this shows a halt banner and disables the
 * whole panel (a `<fieldset disabled>` covers every button + input at once), so the
 * CTA can't fire and fail while spend is paused. */
export function ActionCard({
  title,
  subtitle,
  icon,
  accent,
  paidAction = false,
  children,
}: {
  title: string;
  subtitle: string;
  icon: string;
  accent: string;
  paidAction?: boolean;
  children: React.ReactNode;
}) {
  const { halted } = useSpendHalted();
  const blocked = paidAction && halted;
  return (
    <section className="card tool-action-card">
      <div className="card-h">
        <div>
          <div className="ct">{title}</div>
          <div className="cs">{subtitle}</div>
        </div>
        <div className="tools">
          <span className="material-symbols-rounded" style={{ color: accent, fontSize: 22 }}>
            {icon}
          </span>
        </div>
      </div>
      {blocked && (
        <div
          role="alert"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginTop: 12,
            padding: "10px 12px",
            borderRadius: 10,
            fontSize: 13.5,
            fontWeight: 500,
            color: "var(--crit, #B4232A)",
            background: "color-mix(in srgb, var(--crit, #B4232A) 12%, transparent)",
          }}
        >
          <span className="material-symbols-rounded">block</span>
          API spend is halted. This paid action is paused until spend resumes in Cost Controls.
        </div>
      )}
      <fieldset disabled={blocked} style={{ border: 0, margin: 0, padding: 0, minInlineSize: 0 }}>
        {children}
      </fieldset>
    </section>
  );
}

/** A labelled client picker backed by GET /clients. Renders a graceful
 * loading / empty option so it never shows a bare, broken select. */
export function ClientSelect({
  value,
  onChange,
  label = "Client",
  allowNone = false,
}: {
  value: string;
  onChange: (id: string) => void;
  label?: string;
  allowNone?: boolean;
}) {
  const clientsQ = useClients();
  const clients = clientsQ.data ?? [];
  return (
    <div className="fld">
      <label>{label}</label>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {allowNone && <option value="">Agency-wide (no client)</option>}
        {clients.length === 0 ? (
          <option value="" disabled={!allowNone}>
            {clientsQ.isLoading ? "Loading clients…" : "No clients yet"}
          </option>
        ) : (
          !allowNone && !value && <option value="">Choose a client…</option>
        )}
        {clients.map((c) => (
          <option key={c.id} value={c.id}>
            {c.cn}
          </option>
        ))}
      </select>
    </div>
  );
}

const BANNER_BASE: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  marginTop: 12,
  padding: "10px 12px",
  borderRadius: 10,
  fontSize: 13.5,
  fontWeight: 500,
  lineHeight: 1.35,
};

/** Success / error banner for an action. A 403 is rewritten to a plain-language
 * permission message rather than the raw backend string. */
export function ToolActionResult({
  error,
  success,
}: {
  error?: unknown;
  success?: string | null;
}) {
  if (success) {
    return (
      <div
        role="status"
        style={{
          ...BANNER_BASE,
          color: "var(--ok, #1B7A44)",
          background: "color-mix(in srgb, var(--ok, #1B7A44) 12%, transparent)",
        }}
      >
        <span className="material-symbols-rounded">check_circle</span>
        {success}
      </div>
    );
  }
  if (!error) return null;
  const msg =
    error instanceof ApiError && error.status === 403
      ? "You don't have permission to run this — ask a lead (owner / admin / manager)."
      : error instanceof ApiError && error.status === 402
        ? error.message // budget refusal names both numbers; show it verbatim
        : error instanceof Error
          ? error.message
          : "Something went wrong — please try again.";
  return (
    <div
      role="alert"
      style={{
        ...BANNER_BASE,
        color: "var(--warn, #A96913)",
        background: "color-mix(in srgb, var(--warn, #A96913) 12%, transparent)",
      }}
    >
      <span className="material-symbols-rounded">error</span>
      {msg}
    </div>
  );
}

/** A muted, informational line naming who can run an action (not a gate — the
 * backend is authoritative; this just sets expectations up front). */
export function PermNote({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="fld-hint"
      style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 10, opacity: 0.8 }}
    >
      <span className="material-symbols-rounded" style={{ fontSize: 16 }}>
        info
      </span>
      <span>{children}</span>
    </div>
  );
}
