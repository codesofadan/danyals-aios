"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

// Pairing a browser extension to the citation queue.
//
// This screen exists because the extension is otherwise unusable: the mint endpoint is
// staff-authenticated, so without a dashboard surface the only way to pair a device is to
// hand-craft an API call. The README told operators to come here; for a while, here was
// nowhere.
//
// The token is shown ONCE. That is the GitHub-PAT model the platform already uses for
// skill tokens — only a sha256 is stored, so it genuinely cannot be shown again, and
// saying so at the moment it appears is the difference between an operator copying it and
// an operator having to mint a second one.

type MintedToken = {
  id: string;
  token: string;
  scopes: string[];
  expiresAt: string;
  deviceLabel: string;
  warning: string;
};

type TokenRow = {
  id: string;
  prefix: string;
  scopes: string[];
  deviceLabel: string;
  expiresAt: string;
  revoked: boolean;
  lastUsedAt: string | null;
};

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function isExpired(iso: string): boolean {
  const d = new Date(iso);
  return !Number.isNaN(d.getTime()) && d.getTime() <= Date.now();
}

export default function ExtensionTab() {
  const qc = useQueryClient();
  const [label, setLabel] = useState("");
  const [minted, setMinted] = useState<MintedToken | null>(null);
  const [copied, setCopied] = useState(false);

  const tokensQ = useQuery({
    queryKey: ["extension-tokens"],
    queryFn: () => api.get<TokenRow[]>("/extension/tokens"),
  });

  const mint = useMutation({
    mutationFn: (deviceLabel: string) =>
      api.post<MintedToken>("/extension/tokens", { deviceLabel, scopes: ["citation_queue"] }),
    onSuccess: (t) => {
      setMinted(t);
      setCopied(false);
      setLabel("");
      qc.invalidateQueries({ queryKey: ["extension-tokens"] });
    },
  });

  const revoke = useMutation({
    mutationFn: (id: string) => api.post<void>(`/extension/tokens/${id}/revoke`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["extension-tokens"] }),
  });

  const rows = tokensQ.data ?? [];

  return (
    <div>
      <section className="card" style={{ marginBottom: 16 }}>
        <div className="card-h">
          <div>
            <div className="ct">Pair a device</div>
            <div className="cs">
              The Citation Assistant fills a directory&apos;s form from the client&apos;s
              canonical NAP while you review and submit it yourself. Give the device a name
              you&apos;ll recognise, so you can revoke the right one later.
            </div>
          </div>
        </div>
        <div className="op-toolset" style={{ gap: 8, flexWrap: "wrap" }}>
          <input
            className="op-input"
            style={{ minWidth: 260 }}
            placeholder="e.g. Danyal MacBook / Chrome"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
          <button
            className="primary-btn"
            onClick={() => mint.mutate(label.trim())}
            disabled={mint.isPending}
          >
            <span className="material-symbols-rounded">key</span>
            {mint.isPending ? "Creating…" : "Create a token"}
          </button>
        </div>
        {mint.isError && (
          <div className="status-pill op-crit" style={{ display: "block", marginTop: 10, padding: 10 }}>
            {(mint.error as Error).message}
          </div>
        )}

        {minted && (
          <div
            className="status-pill warn"
            style={{ display: "block", marginTop: 12, padding: 12 }}
          >
            <b>{minted.warning}</b>
            <div
              style={{
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                wordBreak: "break-all",
                margin: "8px 0",
                userSelect: "all",
              }}
            >
              {minted.token}
            </div>
            <button
              className="ghostbtn"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(minted.token);
                  setCopied(true);
                } catch {
                  setCopied(false);
                }
              }}
            >
              <span className="material-symbols-rounded">{copied ? "check" : "content_copy"}</span>
              {copied ? "Copied" : "Copy"}
            </button>
            <div className="op-muted" style={{ marginTop: 8, fontSize: 12 }}>
              Paste it into the extension&apos;s side panel. It expires {when(minted.expiresAt)} —
              about one shift — and can reach the citation queue and nothing else.
            </div>
          </div>
        )}
      </section>

      <section className="card">
        <div className="card-h">
          <div>
            <div className="ct">Paired devices</div>
            <div className="cs">
              Revoke one you no longer use. Changing your password or being suspended
              already revokes every device you have paired.
            </div>
          </div>
        </div>

        {tokensQ.isLoading && <div className="op-muted">Loading…</div>}
        {tokensQ.isError && (
          <div className="op-muted">
            Couldn&apos;t load your devices — {(tokensQ.error as Error).message}
          </div>
        )}
        {!tokensQ.isLoading && !tokensQ.isError && rows.length === 0 && (
          <div className="op-muted">No devices paired yet.</div>
        )}

        {rows.map((t) => {
          const dead = t.revoked || isExpired(t.expiresAt);
          return (
            <div
              key={t.id}
              style={{
                display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap",
                padding: "10px 0", borderTop: "1px solid var(--line)",
              }}
            >
              <span style={{ fontWeight: 600, minWidth: 180 }}>
                {t.deviceLabel || "unnamed device"}
              </span>
              <span className="op-muted" style={{ fontFamily: "ui-monospace, monospace" }}>
                {t.prefix}…
              </span>
              <span className={`status-pill ${dead ? "mut" : "ok"}`}>
                {t.revoked ? "revoked" : isExpired(t.expiresAt) ? "expired" : "active"}
              </span>
              <span className="op-muted" style={{ fontSize: 12 }}>
                {t.lastUsedAt ? `last used ${when(t.lastUsedAt)}` : "never used"} · expires{" "}
                {when(t.expiresAt)}
              </span>
              {!dead && (
                <button
                  className="ghostbtn"
                  style={{ marginLeft: "auto" }}
                  onClick={() => revoke.mutate(t.id)}
                  disabled={revoke.isPending}
                >
                  Revoke
                </button>
              )}
            </div>
          );
        })}
      </section>
    </div>
  );
}
