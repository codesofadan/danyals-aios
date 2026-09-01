"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

// The queue page and the extension are two halves of ONE product, and for a while
// neither mentioned the other: the extension was discoverable only by noticing a
// third tab in Settings. This callout closes the loop — and reads pairing HEALTH
// from the tokens list, because a minted-but-never-connected device is the exact
// signature of the pairing failure that ate the evening of 2026-09-01.

type TokenRow = {
  id: string;
  deviceLabel: string;
  expiresAt: string;
  revoked: boolean;
  lastUsedAt: string | null;
};

function minutesAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "just now";
  const m = Math.round(ms / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} m ago`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
}

export default function ExtensionCallout() {
  const tokensQ = useQuery({
    queryKey: ["extension-tokens"],
    queryFn: () => api.get<TokenRow[]>("/extension/tokens"),
    refetchInterval: 30_000,
  });

  // Silence on error: this is an accelerator's status line, never a blocker for the
  // queue itself, which works fully in the browser.
  if (tokensQ.isError || tokensQ.isLoading) return null;

  const now = Date.now();
  const active = (tokensQ.data ?? []).filter(
    (t) => !t.revoked && new Date(t.expiresAt).getTime() > now,
  );
  const seen = active.filter((t) => t.lastUsedAt);
  const lastSeen = seen
    .map((t) => t.lastUsedAt as string)
    .sort()
    .at(-1);

  if (active.length === 0) {
    return (
      <div className="op-note warn" style={{ marginBottom: 12 }}>
        <b>Work faster in the browser.</b> The Citation Assistant extension opens each
        form, fills every field it has a verified spec for, and copies the rest — from
        a side panel next to the page. Pair it under{" "}
        <a className="op-url" href="/admin/settings?tab=extension">Settings → Extension</a>.
        (The queue works fine without it; the extension just shrinks the minutes.)
      </div>
    );
  }

  if (seen.length === 0) {
    return (
      <div className="op-note warn" style={{ marginBottom: 12 }}>
        <b>Extension paired but never connected</b> — a token exists and no request has
        ever authenticated with it, which usually means the pairing failed in the
        browser. Open the extension&apos;s side panel and follow its connection verdict, or
        re-pair from{" "}
        <a className="op-url" href="/admin/settings?tab=extension">Settings → Extension</a>.
      </div>
    );
  }

  return (
    <div className="op-muted" style={{ marginBottom: 12, fontSize: 12.5 }}>
      <span className="status-pill ok">extension paired</span>{" "}
      last seen {lastSeen ? minutesAgo(lastSeen) : "recently"} —{" "}
      <a className="op-url" href="/admin/settings?tab=extension">manage devices</a>
    </div>
  );
}
