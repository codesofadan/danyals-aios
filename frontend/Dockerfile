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
ENV BACKEND_ORIGIN=$BACKEND_ORIGIN NEXT_TELEMETRY_DISABLED=1
RUN npm run build

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
