# AIOS frontend image — Next.js 15 standalone build.
# Build context is ./frontend:
#     docker build -f frontend/Dockerfile -t aios-web ./frontend
#
# The browser calls RELATIVE /api/v1/* and Next's rewrite proxy forwards it to the
# backend (next.config.mjs BACKEND_ORIGIN). That destination is resolved at BUILD
# time, so BACKEND_ORIGIN is a build ARG — it defaults to the compose service
# `http://api:8000`, which is stable inside the stack.

# ---- deps -------------------------------------------------------------------
FROM node:20-alpine AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ---- builder ----------------------------------------------------------------
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG BACKEND_ORIGIN=http://api:8000
# Where the BROWSER fetches large binary files (audit PDFs, deliverables) from.
# Empty = same-origin /api/v1 through the Next rewrite proxy — correct for JSON,
# but the proxy is pathologically slow on multi-MB binaries, so deployments set
# this to the API's PUBLIC origin (e.g. http://<host>:8000/api/v1) to stream
# files directly. Baked at build time (NEXT_PUBLIC_*).
ARG NEXT_PUBLIC_FILE_BASE_URL=
ENV BACKEND_ORIGIN=$BACKEND_ORIGIN NEXT_PUBLIC_FILE_BASE_URL=$NEXT_PUBLIC_FILE_BASE_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build
# This app ships no public/ dir; `next` doesn't require one. Guarantee it exists
# so the runtime `COPY --from=builder /app/public` below never fails (empty is fine).
RUN mkdir -p /app/public

# ---- runtime (standalone) ---------------------------------------------------
FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001
# standalone bundles node_modules + server.js; static + public are copied beside it.
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
