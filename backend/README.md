# backend

FastAPI service for the AIOS platform. **Not implemented yet** - this folder is
a placeholder so the intended structure is clear to the team and to AI tools.

## Responsibility (planned)

- REST / JSON API consumed by `../frontend`
- Orchestrates the SEO modules: Audit, Content, Off-page, Portal, Policy Radar
- Job queue (Celery + Redis) for long-running work: crawls, content generation, publishing
- Talks to the audit engine, Claude, Serper, Google, and the Google Sheets store
- Auth, per-client key vault, and tier / role enforcement
- Per-client API budget caps and a daily spend-stop

## Stack (planned)

Python 3.11+, FastAPI, Celery, Redis, Supabase / SQLAlchemy, Anthropic SDK.

## Layout (when built)

```
backend/
├── app/            # FastAPI app, one router per module
├── workers/        # Celery tasks
├── integrations/   # Serper, Google, Sheets, Claude clients
└── tests/
```

See `../context/ARCHITECTURE-AND-PLAN.md` for the full design.
