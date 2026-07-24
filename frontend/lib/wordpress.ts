// ============================================================
// AIOS · multi-client WordPress Connections types
// Backs the admin WordPress screen off GET/PUT/DELETE/POST /wp-connections.
// The wire shape is the backend WpConnectionResponse (by_alias): the sealed
// credential is NEVER on the wire - only masked metadata + a `configured` flag.
// ============================================================

export type WpAuthMethod = "plugin" | "xmlrpc" | "app_password";

/** One client's connection state (GET /wp-connections → WpConnection[]). A client
 * with no connection row yet reads as an `unconfigured` placeholder. */
export type WpConnection = {
  clientId: string;
  clientName: string;
  siteUrl: string;
  authMethod: WpAuthMethod;
  username: string;
  /** 'unconfigured' | 'unknown' | 'connected' | 'failed'. */
  status: string;
  /** whether a sealed credential is stored (the secret itself never crosses the wire). */
  configured: boolean;
  lastTestedAt: string | null;
};

/** PUT body (WpConnectionUpsert). The secret fields are OPTIONAL: omit them on a
 * metadata-only edit and the stored credential is kept. */
export type WpConnectionInput = {
  siteUrl: string;
  authMethod: WpAuthMethod;
  apiKey?: string;
  username?: string;
  password?: string;
};

/** POST /wp-connections/{id}/test → the connectivity verdict. */
export type WpTestResult = {
  ok: boolean;
  detail: string;
  status: string;
  lastTestedAt: string | null;
};

export const WP_AUTH_METHODS: WpAuthMethod[] = ["plugin", "xmlrpc", "app_password"];

export const WP_AUTH_LABEL: Record<WpAuthMethod, string> = {
  plugin: "AIOS Publisher plugin",
  xmlrpc: "XML-RPC",
  app_password: "Application Password (REST)",
};

export const WP_AUTH_HINT: Record<WpAuthMethod, string> = {
  plugin:
    "The host-independent primary. Needs the AIOS Publisher plugin installed on the site and its shared API key.",
  xmlrpc:
    "Works on hostile managed hosts that strip auth headers or disable Application Passwords. Uses a WordPress username + password.",
  app_password:
    "The WP REST API over an Application Password (a WordPress username + the generated app password).",
};

export type WpPillTone = "ok" | "warn" | "bad" | "idle";
export type WpStatusPill = { label: string; tone: WpPillTone };

/** Map the raw status + configured flag to the pill the table renders. */
export function wpStatusPill(status: string, configured: boolean): WpStatusPill {
  if (status === "connected") return { label: "Connected", tone: "ok" };
  if (status === "failed") return { label: "Failed", tone: "bad" };
  if (!configured || status === "unconfigured") return { label: "Not set up", tone: "idle" };
  return { label: "Untested", tone: "warn" };
}
