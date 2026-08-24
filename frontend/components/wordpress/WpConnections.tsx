"use client";

// ============================================================
// AIOS · WordPress Connections manager
// A table of EVERY client joined with its WordPress connection status. Per row:
// site URL, auth method, a status pill, a "Test connection" button, and an Edit
// modal to set the site URL + auth method + the plugin key OR username/password.
// The sealed credential never crosses the wire - the form only SENDS a secret; a
// blank secret on save keeps the stored one.
// ============================================================

import { useMemo, useState } from "react";
import {
  useDeleteWpConnection,
  useSaveWpConnection,
  useTestWpConnection,
  useWpConnections,
} from "@/lib/hooks/wordpress";
import {
  WP_AUTH_HINT,
  WP_AUTH_LABEL,
  WP_AUTH_METHODS,
  type WpAuthMethod,
  type WpConnection,
  type WpConnectionInput,
  wpStatusPill,
} from "@/lib/wordpress";

const CARD = "var(--card, #fff)";
const LINE = "var(--line, #E8D2D7)";
const INK = "var(--ink, #241015)";
const BLUSH = "var(--blush, #F8ECEE)";
const MAROON = "var(--maroon, #6E1423)";

const PILL_TONE: Record<string, { bg: string; fg: string }> = {
  ok: { bg: "#E7F6EC", fg: "#137333" },
  warn: { bg: "#FEF3E0", fg: "#8A5B00" },
  bad: { bg: "#FDE7E9", fg: "#B01B2E" },
  idle: { bg: "#EEE9EA", fg: "#6B5860" },
};

function StatusPill({ status, configured }: { status: string; configured: boolean }) {
  const pill = wpStatusPill(status, configured);
  const tone = PILL_TONE[pill.tone];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "3px 10px",
        borderRadius: 999,
        fontSize: 12.5,
        fontWeight: 700,
        background: tone.bg,
        color: tone.fg,
        whiteSpace: "nowrap",
      }}
    >
      <span style={{ width: 7, height: 7, borderRadius: 999, background: tone.fg }} />
      {pill.label}
    </span>
  );
}

// --- the Edit modal --------------------------------------------------------- #
function EditModal({
  conn,
  onClose,
}: {
  conn: WpConnection;
  onClose: () => void;
}) {
  const save = useSaveWpConnection();
  const del = useDeleteWpConnection();
  const [siteUrl, setSiteUrl] = useState(conn.siteUrl);
  const [authMethod, setAuthMethod] = useState<WpAuthMethod>(conn.authMethod);
  const [username, setUsername] = useState(conn.username);
  const [apiKey, setApiKey] = useState("");
  const [password, setPassword] = useState("");


  const onSave = () => {
    const input: WpConnectionInput = { siteUrl: siteUrl.trim(), authMethod };
    if (authMethod === "plugin") {
      if (apiKey.trim()) input.apiKey = apiKey.trim();
    } else {
      input.username = username.trim();
      if (password.trim()) input.password = password.trim();
    }
    save.mutate(
      { clientId: conn.clientId, input },
      { onSuccess: () => onClose() },
    );
  };

  const onDelete = () => {
    if (!window.confirm(`Remove the WordPress connection for ${conn.clientName}?`)) return;
    del.mutate(conn.clientId, { onSuccess: () => onClose() });
  };

  const fieldStyle: React.CSSProperties = {
    width: "100%",
    padding: "10px 12px",
    borderRadius: 10,
    border: `1px solid ${LINE}`,
    fontSize: 14,
    color: INK,
    background: CARD,
    marginTop: 6,
  };
  const labelStyle: React.CSSProperties = { fontSize: 13, fontWeight: 700, color: INK };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Edit WordPress connection for ${conn.clientName}`}
      onMouseDown={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 200,
        background: "rgba(36,16,21,0.42)",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        padding: "6vh 16px",
        overflowY: "auto",
      }}
    >
      <div
        onMouseDown={(e) => e.stopPropagation()}
        style={{
          width: "min(560px, 100%)",
          background: CARD,
          borderRadius: 16,
          border: `1px solid ${LINE}`,
          boxShadow: "0 24px 60px rgba(63,14,24,0.24)",
          padding: 22,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12 }}>
          <div>
            <div style={{ fontSize: 12, fontWeight: 700, color: MAROON, letterSpacing: 0.3 }}>
              WordPress connection
            </div>
            <h2 style={{ fontSize: 22, fontWeight: 800, color: INK, margin: "2px 0 0" }}>{conn.clientName}</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            style={{ border: "none", background: "transparent", cursor: "pointer", fontSize: 22, color: INK }}
          >
            <span className="material-symbols-rounded">close</span>
          </button>
        </div>

        <div style={{ marginTop: 18, display: "grid", gap: 16 }}>
          <label style={{ display: "block" }}>
            <span style={labelStyle}>Site URL</span>
            <input
              style={fieldStyle}
              value={siteUrl}
              onChange={(e) => setSiteUrl(e.target.value)}
              placeholder="https://clientsite.com"
              autoComplete="off"
              inputMode="url"
            />
          </label>

          <label style={{ display: "block" }}>
            <span style={labelStyle}>Auth method</span>
            <select
              style={fieldStyle}
              value={authMethod}
              onChange={(e) => setAuthMethod(e.target.value as WpAuthMethod)}
            >
              {WP_AUTH_METHODS.map((m) => (
                <option key={m} value={m}>
                  {WP_AUTH_LABEL[m]}
                </option>
              ))}
            </select>
            <div style={{ fontSize: 12.5, color: "#6B5860", marginTop: 6, lineHeight: 1.5 }}>
              {WP_AUTH_HINT[authMethod]}
            </div>
          </label>

          {authMethod === "plugin" ? (
            <label style={{ display: "block" }}>
              <span style={labelStyle}>Plugin API key</span>
              <input
                style={fieldStyle}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={conn.configured ? "•••••••• (leave blank to keep the stored key)" : "Paste the AIOS Publisher shared key"}
                type="password"
                autoComplete="new-password"
              />
            </label>
          ) : (
            <>
              <label style={{ display: "block" }}>
                <span style={labelStyle}>WordPress username</span>
                <input
                  style={fieldStyle}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="editor-login"
                  autoComplete="off"
                />
              </label>
              <label style={{ display: "block" }}>
                <span style={labelStyle}>{authMethod === "app_password" ? "Application password" : "Password"}</span>
                <input
                  style={fieldStyle}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={conn.configured ? "•••••••• (leave blank to keep the stored secret)" : "Paste the password"}
                  type="password"
                  autoComplete="new-password"
                />
              </label>
            </>
          )}

          {(save.isError || del.isError) && (
            <div style={{ fontSize: 13, color: "#B01B2E", fontWeight: 600 }}>
              Could not save. Check the details and try again.
            </div>
          )}

          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginTop: 4 }}>
            <button
              type="button"
              onClick={onDelete}
              disabled={del.isPending || !conn.configured}
              style={{
                border: "none",
                background: "transparent",
                color: conn.configured ? "#B01B2E" : "#B7A9AD",
                cursor: conn.configured ? "pointer" : "not-allowed",
                fontSize: 13.5,
                fontWeight: 700,
              }}
            >
              {del.isPending ? "Removing…" : "Remove connection"}
            </button>
            <div style={{ display: "flex", gap: 10 }}>
              <button
                type="button"
                onClick={onClose}
                style={{
                  padding: "10px 16px",
                  borderRadius: 10,
                  border: `1px solid ${LINE}`,
                  background: CARD,
                  color: INK,
                  fontSize: 14,
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={onSave}
                disabled={save.isPending || !siteUrl.trim()}
                style={{
                  padding: "10px 18px",
                  borderRadius: 10,
                  border: "none",
                  background: MAROON,
                  color: "#fff",
                  fontSize: 14,
                  fontWeight: 800,
                  cursor: save.isPending || !siteUrl.trim() ? "not-allowed" : "pointer",
                  opacity: save.isPending || !siteUrl.trim() ? 0.6 : 1,
                }}
              >
                {save.isPending ? "Saving…" : "Save connection"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// --- a single row's Test button + transient result -------------------------- #
function TestButton({ conn }: { conn: WpConnection }) {
  const test = useTestWpConnection();
  const result = test.data;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <button
        type="button"
        onClick={() => test.mutate(conn.clientId)}
        disabled={test.isPending || !conn.configured}
        title={conn.configured ? "Probe the live site" : "Add a credential first"}
        style={{
          padding: "6px 12px",
          borderRadius: 8,
          border: `1px solid ${LINE}`,
          background: CARD,
          color: conn.configured ? INK : "#B7A9AD",
          fontSize: 13,
          fontWeight: 700,
          cursor: test.isPending || !conn.configured ? "not-allowed" : "pointer",
          whiteSpace: "nowrap",
        }}
      >
        {test.isPending ? "Testing…" : "Test connection"}
      </button>
      {result && (
        <span
          title={result.detail}
          style={{ fontSize: 12.5, fontWeight: 700, color: result.ok ? "#137333" : "#B01B2E", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
        >
          {result.ok ? "✓ " : "✕ "}
          {result.detail}
        </span>
      )}
    </div>
  );
}

// --- the screen ------------------------------------------------------------- #
export default function WpConnections() {
  const { data, isLoading, isError, refetch } = useWpConnections();
  const [editing, setEditing] = useState<WpConnection | null>(null);

  const rows = useMemo(() => data ?? [], [data]);
  const connectedCount = rows.filter((r) => r.configured).length;

  const th: React.CSSProperties = {
    textAlign: "left",
    padding: "10px 14px",
    fontSize: 12,
    fontWeight: 700,
    color: "#6B5860",
    letterSpacing: 0.3,
    textTransform: "uppercase",
    borderBottom: `1px solid ${LINE}`,
  };
  const td: React.CSSProperties = { padding: "12px 14px", fontSize: 14, color: INK, borderBottom: `1px solid ${LINE}`, verticalAlign: "middle" };

  return (
    <div className="main-pad" style={{ padding: "22px 26px" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 16,
          marginBottom: 18,
          flexWrap: "wrap",
        }}
      >
        <div style={{ maxWidth: 640 }}>
          <p style={{ fontSize: 14, color: "#5B4A4F", lineHeight: 1.55, margin: 0 }}>
            Connect each client&rsquo;s WordPress site once. Approved content is published
            straight to the right client&rsquo;s site using the auth method you set here.
            Credentials are sealed on the server and never shown again.
          </p>
        </div>
        {!isLoading && !isError && (
          <div style={{ fontSize: 13, fontWeight: 700, color: MAROON, whiteSpace: "nowrap" }}>
            {connectedCount} / {rows.length} clients connected
          </div>
        )}
      </div>

      <div style={{ background: CARD, border: `1px solid ${LINE}`, borderRadius: 14, overflow: "hidden" }}>
        {isLoading ? (
          <div style={{ padding: 40, textAlign: "center", color: "#6B5860", fontSize: 14 }}>
            Loading connections…
          </div>
        ) : isError ? (
          <div style={{ padding: 40, textAlign: "center" }}>
            <div style={{ fontSize: 14, color: "#B01B2E", fontWeight: 700 }}>Could not load WordPress connections.</div>
            <button
              type="button"
              onClick={() => void refetch()}
              style={{ marginTop: 12, padding: "8px 16px", borderRadius: 8, border: `1px solid ${LINE}`, background: CARD, color: INK, fontWeight: 700, cursor: "pointer" }}
            >
              Retry
            </button>
          </div>
        ) : rows.length === 0 ? (
          <div style={{ padding: 44, textAlign: "center", color: "#6B5860" }}>
            <div style={{ fontSize: 15, fontWeight: 800, color: INK }}>No clients yet</div>
            <div style={{ fontSize: 13.5, marginTop: 6 }}>Add a client first, then connect its WordPress site here.</div>
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 820 }}>
              <thead style={{ background: BLUSH }}>
                <tr>
                  <th style={th}>Client</th>
                  <th style={th}>Site URL</th>
                  <th style={th}>Auth method</th>
                  <th style={th}>Status</th>
                  <th style={{ ...th, textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((conn) => (
                  <tr key={conn.clientId}>
                    <td style={{ ...td, fontWeight: 700 }}>{conn.clientName}</td>
                    <td style={td}>
                      {conn.siteUrl ? (
                        <a href={conn.siteUrl} target="_blank" rel="noopener noreferrer" style={{ color: MAROON, textDecoration: "none" }}>
                          {conn.siteUrl.replace(/^https?:\/\//, "")}
                        </a>
                      ) : (
                        <span style={{ color: "#B7A9AD" }}>— not set —</span>
                      )}
                    </td>
                    <td style={td}>{conn.configured || conn.siteUrl ? WP_AUTH_LABEL[conn.authMethod] : <span style={{ color: "#B7A9AD" }}>—</span>}</td>
                    <td style={td}>
                      <StatusPill status={conn.status} configured={conn.configured} />
                    </td>
                    <td style={{ ...td, textAlign: "right" }}>
                      <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 12 }}>
                        <TestButton conn={conn} />
                        <button
                          type="button"
                          onClick={() => setEditing(conn)}
                          style={{
                            padding: "6px 14px",
                            borderRadius: 8,
                            border: "none",
                            background: MAROON,
                            color: "#fff",
                            fontSize: 13,
                            fontWeight: 800,
                            cursor: "pointer",
                          }}
                        >
                          {conn.configured || conn.siteUrl ? "Edit" : "Connect"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {editing && <EditModal conn={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}
