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
  /** The address the extension must be paired against — stated by the server that
   *  minted the token, never guessed. (The 2026-09-01 outage: extension on :8000,
   *  dashboard on :8099, and no surface anywhere could say so.) */
  apiBase: string;
  warning: string;
};

type PairingInfo = {
  apiBase: string;
  allowedExtensionOrigins: string[];
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
    // "Last seen" should move while an operator tests a fresh pairing next door.
    refetchInterval: 30_000,
  });

  const pairingQ = useQuery({
    queryKey: ["extension-pairing-info"],
    queryFn: () => api.get<PairingInfo>("/extension/pairing-info"),
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
            <div className="ct">Install &amp; connect</div>
            <div className="cs">
              The Citation Assistant lives in Chrome and works{" "}
              <a className="op-url" href="/admin/citations/queue">the citation queue</a> from a
              side panel beside each directory&apos;s form.
            </div>
          </div>
        </div>
        <ol style={{ margin: "6px 0 0 18px", fontSize: 13.5, lineHeight: 1.7 }}>
          <li>
            Build it once: run <code>Build-Extension.bat</code> (Windows) or{" "}
            <code>cd extension &amp;&amp; npm install &amp;&amp; npm run build</code>, then{" "}
            <code>chrome://extensions</code> → Developer mode → Load unpacked →{" "}
            <b>the <code>extension/dist</code> folder</b> (not <code>extension/</code>).
          </li>
          <li>
            Copy the API address below and create a token in the next card — paste both
            into the extension&apos;s side panel.
          </li>
          <li>
            If pairing fails, the panel runs a connection check and tells you which of
            the four things broke (server unreachable / blocked by the browser / bad
            token / expired) and what to do. For the &quot;blocked by the browser&quot; case, the
            panel shows this device&apos;s id — an admin adds{" "}
            <code>EXTENSION_ORIGINS=chrome-extension://&lt;that id&gt;</code> to{" "}
            <code>backend/.env</code> and restarts the API.
            {(pairingQ.data?.allowedExtensionOrigins.length ?? 0) > 0 && (
              <> Currently allow-listed: <code>{pairingQ.data!.allowedExtensionOrigins.join(", ")}</code>.</>
            )}
          </li>
        </ol>
      </section>

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
          <div className="op-note crit" style={{ marginTop: 10 }}>
            Couldn&apos;t create a token — {(mint.error as Error).message}
          </div>
        )}

        <div className="op-muted" style={{ marginTop: 12, fontSize: 12.5 }}>
          API address to paste into the panel beside the token:{" "}
          {pairingQ.isLoading ? (
            <em>asking the server…</em>
          ) : pairingQ.data?.apiBase ? (
            <code className="op-token" style={{ display: "inline", margin: 0 }}>
              {pairingQ.data.apiBase}
            </code>
          ) : (
            <em>
              unavailable — ask an admin; a guessed address is how pairing fails silently
            </em>
          )}
        </div>

        {minted && (
          // .op-note, never .status-pill: this is a sentence plus a secret, and the pill's
          // capitalize+nowrap once rendered the warning Title-Cased on one unwrappable line.
          <div className="op-note warn" style={{ marginTop: 12 }}>
            <b>{minted.warning}</b>
            <span className="op-token">{minted.token}</span>
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
              Open the extension&apos;s side panel and paste the token with this address:{" "}
              <code>{minted.apiBase}</code>. It expires {when(minted.expiresAt)} — about one
              shift — and can reach the citation queue and nothing else.
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

        {revoke.isError && (
          <div className="op-note crit" style={{ marginBottom: 8 }}>
            Couldn&apos;t revoke that device — {(revoke.error as Error).message}
          </div>
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
              {/* Minted but never authenticated is the exact signature of a pairing
                  that failed in the browser — amber, because waiting won't fix it. */}
              {!t.lastUsedAt && !dead && <span className="status-pill warn">never connected</span>}
              <span className="op-muted" style={{ fontSize: 12 }}>
                {t.lastUsedAt ? `last seen ${when(t.lastUsedAt)}` : "no successful request yet"} ·
                expires {when(t.expiresAt)}
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
