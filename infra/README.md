# infra

Deployment and operations for the AIOS platform. **Not implemented yet.**

## Plan

- **Docker Compose** for local and production: frontend, backend, workers, Redis
- **Caddy** reverse proxy with automatic TLS
- **CI**: lint, tests, the RLS gate, and build checks
- Secrets kept out of the repo; each environment supplies its own

## Layout (when built)

```
infra/
├── docker/         # Dockerfiles + compose files
├── caddy/          # Caddyfile + TLS config
└── ci/             # pipeline definitions
```
