# db

Database schema and migrations for the AIOS platform. **Not implemented yet.**

## Plan

- **Postgres (via Supabase)** for identity, secrets / key vault, clients, sites, and the knowledge base
- **Google Sheets** as the operational store for audit and content run data (SheetStore)
- Row-level security (FORCE RLS) enforced, with a CI gate that fails if a table is unprotected
- Migrations tracked in this folder

## Layout (when built)

```
db/
├── migrations/     # ordered SQL / Supabase migrations
├── schema.sql      # current schema snapshot
└── seed/           # seed + fixture data
```

See `../context/AIOS-Data-Flow-Structure.pdf` for how data moves through the system.
