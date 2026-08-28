/** @type {import('next').NextConfig} */

// Same-origin transport in dev: the browser calls the RELATIVE `/api/v1/*`
// (NEXT_PUBLIC_API_BASE_URL default, see lib/api.ts) and Next proxies it to the
// FastAPI backend, so there is no CORS preflight and no cross-origin port footgun.
// Override BACKEND_ORIGIN for a non-default backend host/port.
// NOTE (prod topology): the shipped Caddyfile serves the API on its OWN subdomain
// (cross-origin). Phase D must pick one topology — either keep this proxy and add a
// frontend Caddy block, or drop the proxy and set API_CORS_ORIGINS on the backend.
// `.trim()` guards against a stray trailing space in BACKEND_ORIGIN (a classic
// `cmd /k "set VAR=%VAR% && ..."` footgun captures the space before `&&`), which
// would otherwise produce `http://host:8000 /api/v1/:path*` and fail rewrites
// with `TypeError: Invalid URL` — turning every proxied API call into a 500.
const BACKEND_ORIGIN = (process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000").trim();

// Old top-level paths, redirected after the go-live URL restructure: `/` is now
// the public free-audit landing page (was the admin dashboard), admin moved under
// `/admin/*`, and the team portal moved from `/portal` to `/team`. Keeps any
// existing bookmark/marketing link resolving instead of 404ing.
const OLD_ADMIN_PATHS = [
  "audit", "content", "off-page", "policy-radar", "clients", "milestones",
  "reports", "upsells", "tiers", "cost", "vault", "backups", "settings",
];

// --- Content Security Policy (P0-8) -----------------------------------------
// The app had NO CSP. That matters more here than in a typical dashboard because
// the access token is a 7-day bearer credential held in `localStorage`
// (lib/api.ts): any script that runs on this origin can read it and then use it
// from anywhere, for a week. Until the token gains a `jti` + denylist and a
// shorter TTL, the edge policy is the only thing narrowing that blast radius.
//
// What this policy actually buys, stated honestly:
//
//   connect-src 'self'   — the important one. Injected script may read the token
//                          but cannot POST it to an attacker-controlled host.
//   frame-ancestors      — no clickjacking; supersedes X-Frame-Options.
//   object-src / base-uri / form-action — closes plugin, <base>-hijack and
//                          form-exfiltration vectors.
//
// What it does NOT buy, and why:
//
//   script-src keeps 'unsafe-inline' (and 'unsafe-eval' in dev) because Next.js
//   injects inline bootstrap/hydration scripts. Removing it needs nonce-based
//   middleware, which forces every route to render dynamically and would give up
//   the fully-static build this app currently produces. That is a deliberate
//   trade, recorded in docs/implementation/IMPLEMENTATION_LOG.md — not an
//   oversight. So this policy mitigates EXFILTRATION, not injection.
//
//   img-src allows https: because the product legitimately renders images from
//   arbitrary client sites (WordPress media, audit screenshots, content
//   previews). That leaves an image-beacon side channel; closing it would break
//   real functionality, so it is accepted and named rather than hidden.
//
// fonts.googleapis.com / fonts.gstatic.com are the Material Symbols icon font.
// When that font is self-hosted (a separate planned change) both hosts should be
// dropped from style-src and font-src.
const isDev = process.env.NODE_ENV !== "production";

const CSP_DIRECTIVES = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com data:",
  "img-src 'self' data: blob: https:",
  // Same-origin only. `/api/v1/*` is same-origin via the rewrite proxy above; a
  // deployment that serves the API on its own subdomain must add that origin
  // here, or every request will be blocked.
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "frame-src 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "upgrade-insecure-requests",
].join("; ");

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CSP_DIRECTIVES },
  { key: "X-Content-Type-Options", value: "nosniff" },
  // Redundant with frame-ancestors for modern browsers; kept for older ones.
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // No feature of this app needs any of these.
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const nextConfig = {
  reactStrictMode: true,
  // Build directory, overridable per process. Defaults to Next's own ".next", so this
  // changes nothing for a normal run. It exists because two `next dev` servers started
  // from this same folder SHARE .next and corrupt each other's cache - the visible
  // symptom is a route that compiled fine suddenly serving /_not-found. Set
  // NEXT_DIST_DIR to give a second instance its own directory.
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  // Emit a self-contained server bundle (.next/standalone) for a small Docker
  // runtime image — ignored by `next dev`, only affects `next build`.
  output: "standalone",
  experimental: {
    // The /api/v1 rewrite proxy (next/dist/compiled/http-proxy) defaults to a
    // 30s proxyTimeout. Some backend calls are legitimately slow — content
    // research runs a live Anthropic web_search that takes ~40–60s — so a 30s
    // cut surfaced to the user as a bogus "internal server error" while the
    // backend was still working and would have returned a valid result. Raise
    // the upstream proxy timeout so those long synchronous calls complete.
    proxyTimeout: 180_000,
  },
  async redirects() {
    return [
      { source: "/free-audit", destination: "/", permanent: true },
      // --- The 2026-08-28 revert. A 2026-08-27 restructure renamed and
      // CONSOLIDATED the execution modules (WordPress and Web 2.0 became tabs
      // inside "Site Builder" and "Off-Page", audits and leads merged, a
      // "Search" module was added). The owner rejected that shape, so the old
      // URLs are canonical again and the restructure's URLs redirect back.
      // Anything bookmarked during the one day it was live still resolves.
      { source: "/admin/audits", destination: "/admin/audit", permanent: false },
      { source: "/admin/audits/:id", destination: "/admin/audit/:id", permanent: false },
      { source: "/admin/pipeline", destination: "/admin/leads", permanent: false },
      { source: "/admin/pipeline/:token", destination: "/admin/leads/:token", permanent: false },
      { source: "/admin/site-builder", destination: "/admin/wordpress", permanent: false },
      { source: "/admin/integrations", destination: "/admin/vault", permanent: false },
      { source: "/admin/off-page", destination: "/admin/web2", permanent: false },
      // Citations left the navigation with the revert; the module itself stays
      // locked (no verified aggregator), so its URL points at its nearest home.
      { source: "/admin/citations", destination: "/admin/web2", permanent: false },
      // The Search module is gone from the admin portal. Its five tool
      // workspaces remain reachable, RBAC-gated, at /team/tools/[slug].
      { source: "/admin/search", destination: "/team", permanent: false },
      { source: "/portal", destination: "/team", permanent: true },
      { source: "/portal/:path*", destination: "/team/:path*", permanent: true },
      ...OLD_ADMIN_PATHS.map((p) => ({
        source: `/${p}`,
        destination: `/admin/${p}`,
        permanent: true,
      })),
      ...OLD_ADMIN_PATHS.map((p) => ({
        source: `/${p}/:path*`,
        destination: `/admin/${p}/:path*`,
        permanent: true,
      })),
    ];
  },
  // Emitted by Next itself rather than only at the edge, so the policy travels
  // with the app in every deployment topology (Docker, Caddy, nginx, `next
  // start`) instead of depending on one reverse proxy being configured right.
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${BACKEND_ORIGIN}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
