/** @type {import('next').NextConfig} */

// Same-origin transport in dev: the browser calls the RELATIVE `/api/v1/*`
// (NEXT_PUBLIC_API_BASE_URL default, see lib/api.ts) and Next proxies it to the
// FastAPI backend, so there is no CORS preflight and no cross-origin port footgun.
// Override BACKEND_ORIGIN for a non-default backend host/port.
// NOTE (prod topology): the shipped Caddyfile serves the API on its OWN subdomain
// (cross-origin). Phase D must pick one topology — either keep this proxy and add a
// frontend Caddy block, or drop the proxy and set API_CORS_ORIGINS on the backend.
const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
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
