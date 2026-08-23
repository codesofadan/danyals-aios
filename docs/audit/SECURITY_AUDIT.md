# SECURITY AUDIT — AIOS (Daniel Project)

**Audit date:** 2026-08-23 · **Commit:** `79d1036`
**Scope:** authentication, authorization, RBAC, secrets, credentials, database access, uploads,
webhooks, API surface, input validation, injection (SQL/XSS/CSRF/SSRF/prompt), rate limiting,
sensitive logging.

**No secret values are printed in this document.** Where a secret-shaped artefact was found, its
location is named and its content is not reproduced.

---

## 0. Verdict

**The security foundation is the strongest part of this codebase and must be preserved.**
Authentication, tenant isolation and SQL safety are done properly — in several places better
than is typical for a six-week build. The findings below are therefore concentrated in
**identity lifecycle** (you cannot remove a person) and **cost/abuse control** (a public
endpoint can spend the owner's money), not in the cryptographic or data-access core.

| Severity | Count |
|---|---|
| **P0 — Critical** | 4 |
| **P1 — High** | 7 |
| **P2 — Medium** | 6 |
| **Strengths worth naming** | 10 |

---

## 1. What is already right — preserve this, do not rewrite it

| # | Control | Evidence |
|---|---|---|
| S1 | **Own EdDSA (Ed25519) tokens with a hard algorithm allow-list.** `_ALLOWED_ALGS = ["EdDSA"]` is a single-entry list, which defeats alg-confusion (no HS256 downgrade using the public key as an HMAC secret) and the `none` attack outright. `aud`, `iss`, `exp`, `sub` all verified; `exp`/`sub`/`aud` additionally **required** to be present | `app/core/auth.py:52, 100-120` |
| S2 | **Argon2id password hashing**, with a constant-time login path: an unknown user is verified against a dummy hash so response timing does not disclose account existence | `app/routers/auth.py:141-146` |
| S3 | **RLS is the real tenant boundary, not the API.** 195 policies across 77 tables; **every** table has both `ENABLE` and `FORCE` row-level security (verified by parsing all 80 migrations) | `db/migrations/*`, `db/migrations/README.md` |
| S4 | **Transaction-local identity that cannot be forged.** `set_config('app.user_id', %s, true)` with a **bound parameter** — deliberately chosen over `SET LOCAL` precisely because `SET LOCAL` cannot bind, and a bound value is data, never executable SQL. Plus `RESET ALL` on pool return, and autocommit asserted off (identity would otherwise escape its transaction) | `app/db/database.py:_configure_rls_connection`, `rls_connection` |
| S5 | **Identity is validated as a UUID app-side** before it ever reaches Postgres, so `set_config` can never receive attacker-shaped text | `app/db/database.py:_validate_user_id` |
| S6 | **Two explicit connection seams**, and the privileged (BYPASSRLS) one is server-only with a never-logged DSN. The code documents the trap it avoids: `service_role` bypasses **policies, not triggers**, so task writes stay on the RLS pool | `app/db/database.py` |
| S7 | **No ORM, but no injection surface either.** Every value is a bound param; every dynamic identifier goes through `psycopg.sql.Identifier`; dynamic column lists come only from server-built dicts | all 25 `app/db/*_repo.py` |
| S8 | **Live-site mutation is human-attributed at the database.** `apply_onpage_fix` / `revert_onpage_fix` run on the acting **lead's** RLS identity, and the `0038` guard trigger *refuses a live-site write that is not lead-attributed* | `app/modules/on_page/tasks.py`, `db/0038_on_page.sql` |
| S9 | **Task lifecycle enforced by database triggers**, not only by the API — illegal `todo→done` transitions are rejected by the trigger | `db/0012_tasks_guard_hardening.sql` |
| S10 | **Audit-report HTML is doubly contained**: served with `default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:` **and** rendered client-side in a `srcdoc` iframe with `sandbox="allow-same-origin"` and **no `allow-scripts`** | `app/services/audit_artifacts.py:39`, `frontend/components/report/ReportViewer.tsx:241-246` |

Additionally: no public signup route exists; provisioning is owner-only in a single privileged
transaction; a runtime OpenAPI sweep test (`tests/test_route_auth_guard.py`) fails the build the
moment any route ships without an identity guard; and CI runs `pip-audit` + `gitleaks` + an RLS
gate against ephemeral Postgres on every change.

---

## 2. P0 — Critical

### SEC-A · There is no way to remove a person from the system

**Location:** `db/migrations/0002_identity_rbac.sql:15`, `app/routers/admin_users.py`,
`app/routers/auth.py:132`, `app/core/auth.py:177-190`

Four independent facts compound:

1. `create type public.user_status as enum ('active', 'away', 'invited', 'offline')` — **there is
   no `suspended`, `disabled` or `deactivated` value.**
2. `app/routers/admin_users.py` exposes GET, POST, `/invite`, `/{id}/grants`,
   `/{id}/credentials`, `/{id}/password` — **and no DELETE, no deactivate**.
3. `login()` verifies the password and mints a token. It **never reads `status`.**
4. `get_current_user` loads `status` into `CurrentUser` and **no guard anywhere consults it**
   (grep across `app/core/`, `app/rbac/`, `app/routers/`, `app/modules/` returns nothing).

Meanwhile `app/rbac/matrix.py:131` advertises `manage_team` as *"Add, edit & **deactivate**
members"*. The capability is advertised and does not exist.

**Impact.** A departing specialist, or a compromised account, retains full role-level access
indefinitely. The only available remedy is a manual `DELETE` against a 77-table schema with 110
foreign-key references — which will either cascade destructively or leave orphans.

**Also note:** this requirement is **absent from `REQUIREMENTS_TRACEABILITY.md` entirely.** It is
a gap in the requirements, not only in the build.

**Fix.** Add `suspended` to the enum; check it in `login()` **and** in `get_current_user`;
add `POST /users/{id}/suspend` + `/reactivate` (owner/admin); make `status` part of every
authorization decision. Pair with SEC-B.

---

### SEC-B · A 7-day, non-revocable bearer token in `localStorage`, with no application CSP

**Location:** `app/config.py:68-72`, `frontend/lib/api.ts`, `infra/deploy/nginx.conf:31-34`

- `jwt_access_ttl_seconds: int = 604_800` — 7 days. The comment is explicit: *"there is no
  refresh route, so this IS the whole session."*
- **No `jti` claim, no denylist, no `token_version` column, no revocation endpoint** (grep for
  `revoke|jti|denylist|blacklist|token_version` in the auth path returns nothing).
- The token is stored in `localStorage` under `aios-token-v1` — readable by any script on the
  origin.
- **No `Content-Security-Policy` on the application.** `nginx.conf` sets HSTS, `nosniff`,
  `X-Frame-Options` and `Referrer-Policy` — and no CSP. `Caddyfile` likewise. The team clearly
  knows the header: they applied a strict one to served audit artefacts. It was never applied to
  the app.

**Impact.** One XSS anywhere in 136 components yields a token granting full account access for up
to seven days, which **cannot be revoked by any means** — not a password change, not an admin
action, not deleting the user row (the token verifies against a static public key; the DB lookup
would fail, but only after the row is gone).

**Mitigating factors, stated honestly.** Bearer-only, no cookies, so **CSRF is structurally
impossible**. Only one `dangerouslySetInnerHTML` exists in the whole frontend
(`ProjectGantt.tsx:148`, an internally-constructed chart tooltip). React escapes by default. So
the XSS *likelihood* is low; the *blast radius* is the problem.

**Fix.** Add a `jti` + a server-side denylist (Redis, TTL = token TTL); invalidate on password
change, suspend and logout; add an application CSP; shorten the access TTL and add a refresh
route so shortening does not log staff out mid-work.

---

### SEC-C · An unauthenticated endpoint spends the owner's money and records the cost as zero

**Location:** `app/routers/public.py:262`, `workers/tasks/audit.py:450-517`,
`integrations/audit_engine.py:211-227`

- `POST /api/v1/public/audits` is **unauthenticated by design** (lead-gen funnel).
- The run is documented as *"never gated"* — it does not pass the cost gate at all, so **the
  global spend-halt and the per-client budget cap cannot stop it** (ADM-026, MT-005).
- It now runs `--mode auto` with **paid providers on** — Serper and Google Places spend on every
  call. The adapter's own comment: *"this path is NO LONGER $0 … the owner should know the free
  funnel is now a metered cost."*
- It then records `_safe_record_cost(store, row, 0.0)`.
- The only control is `rate_limit_ip("public_audit", 5)` — **5 per minute per IP**, and the
  limiter **fails open** on a Redis error (`app/core/ratelimit.py:33`).

**Impact.** Denial-of-wallet. With rotating IPs, an attacker (or an aggressive scraper) drives
unbounded Serper + Google Places spend on the owner's keys, and the Cost screen shows $0.00 the
whole time. This is simultaneously a security finding, a cost-integrity finding and a
truthfulness finding.

**Fix.** Route the public funnel through the cost gate under its own dial with its own budget;
record real cost; add a global daily cap on free audits independent of IP; add a proof-of-work or
email-verification step before the run is queued; make the rate limiter fail **closed** on paid
paths.

---

### SEC-D · The WhatsApp export sits in the working tree

**Location:** `whatsapp chats, media and calls/` (untracked)

589 `.opus` voice notes, 26 `.mp4`, 16 `.mov`, 224 `.jpg`, plus chat transcripts, in the
repository working directory. It is **untracked**, so it is not in git history — that is the good
news, and it means SEC-017 has not yet been violated irreversibly.

It is also one `git add -A` away from being permanent, and the recovery specification itself
records that credentials were shared through these channels (SEC-016 requires rotating them).

**Fix.** Move the directory outside the repository root today. Add it to `.gitignore` as a
belt-and-braces measure. Then complete SEC-016 (rotate every credential that appeared in those
exports) and SEC-018 (establish a credential channel that is not a messaging app) — both of which
are operational, not code, and neither of which this audit can verify.

---

## 3. P1 — High

| # | Finding | Location | Impact | Fix |
|---|---|---|---|---|
| SEC-E | **Rate limiting fails open and covers 6 endpoints.** `_enforce` swallows Redis errors and allows the call. Applied only to login, public audits, audit create, portal audit create, portal request create, and one competitor-intel route | `app/core/ratelimit.py:33`; 6 call sites | A Redis blip removes every limit, including on login (brute force) and the paid public funnel | Fail **closed** on paid/auth paths; extend coverage to every spend-causing and every write endpoint |
| SEC-F | **No prompt-injection defence on fetched content.** Crawled site text, competitor page content and policy-source text flow into user-turn prompts with no delimiter convention, no escaping and no injection test. The frozen system prompt provides structural separation but nothing enforces that fetched content stays in a data position | `app/services/content_research.py`, `policy_watch.py`, `site_design.py`, `integrations/citation_discovery.py:648` | A malicious page could steer generated client content or a policy recommendation | Wrap all untrusted text in an explicit, escaped delimiter block; add an injection-corpus test to CI (AI-010, SEC-020) |
| SEC-G | **AI output is shape-validated, not fact-validated.** Strict-JSON parsing exists; nothing checks that a number in a model's output matches a Python-computed one | `policy_generate.py`, `policy_ask.py` | AI-001's "Python computes numbers" holds by convention, not by enforcement — a future prompt change could leak an invented metric into a client report | Add a validator that rejects any numeric field not present in the computed input (AI-006) |
| SEC-H | **The activity log is not tamper-evident and not universal.** `record_activity` is called from routers by convention; there is no trigger and no revoked UPDATE/DELETE grant making it genuinely append-only | `app/services/activity.py`, `db/0005_activity_log.sql` | An operator dispute cannot be settled from the log; a path that forgets the call leaves no trace | Enforce append-only at the DB (revoke UPDATE/DELETE from `authenticated`); add a coverage test asserting every mutating route logs (DATA-021, ADM-032) |
| SEC-I | **Vault master-key custody is undocumented.** The key is correctly held outside Postgres; there is no runbook for where it lives, how it is backed up, or how it is rotated | `app/services/vault.py` | Losing it makes every stored credential unrecoverable; leaking it makes RLS irrelevant for secrets | Write the custody + rotation runbook (SEC-021) |
| SEC-J | **Backups are never restore-tested and do not cover artefacts.** `pg_dump` + B2 upload is well built (password via `PG*` env, never argv; traversal-safe root; owner-only restore with an echoed-id confirm) but nothing fires it (beat is off), no drill is evidenced, and audit artefacts on the `aios_state` volume are not in scope | `app/services/backups.py`, `integrations/b2.py` | A restore is unproven at exactly the moment it matters (SEC-022, MT-008, MT-009) | Schedule it, alert on failure, run a documented drill, extend scope to the artefact store |
| SEC-K | **`site-analytics/oauth/callback` has no identity dependency.** It is the OAuth return leg, so this is expected — but the `state` parameter's binding to the initiating user could not be confirmed from source | `app/modules/site_analytics/router.py` | If `state` is not bound and verified, an attacker could attach their own Google property to another tenant | Verify `state` is a signed, single-use, user-bound nonce; add a negative test |

---

## 4. P2 — Medium

| # | Finding | Location |
|---|---|---|
| SEC-L | **Realistic fake secrets in the frontend source.** `frontend/lib/vault.ts:101-113` — 11 entries with both `masked` and `secret` fields shaped like real Anthropic / Google / OAuth / WordPress credentials. Unimported (verified), so tree-shaken from the bundle, but a permanent secret-scanner false positive and a bad pattern | remove |
| SEC-M | **Plaintext demo passwords shipped to the browser.** `frontend/lib/data.ts` `teamCredentials` — eight named users with `pass` values, seeded into every visitor's `localStorage` by the still-mounted `lib/store.tsx` (`app/layout.tsx:62`). No screen reads the store | remove the store and the seed |
| SEC-N | **A real business NAP and phone number in a committed script.** `tools/finish_citation.py:51-54` | remove |
| SEC-O | **Uploads.** `data_import` has a traversal-safe upload root and a streaming (`read_only`) XLSX reader — good. `client_max_body_size 100m` at nginx. No content-type allow-list or virus scanning was found | add an extension/MIME allow-list |
| SEC-P | **No webhook receivers exist.** Confirmed by inspection — there is no inbound webhook surface, so webhook signature verification is not applicable. Recorded so a future reviewer does not re-open it | n/a |
| SEC-Q | **Secrets in logs.** Multiple seams explicitly document never logging keys (the WP plugin key rides in the body; the DB password rides in `PG*` env; the Sentry DSN is logged by name only). No counter-example found. Good, but unasserted | add a log-scrubbing assertion test |

---

## 5. Injection surface — summary

| Class | Verdict | Evidence |
|---|---|---|
| **SQL injection** | **Not present.** Every value bound; identifiers via `psycopg.sql.Identifier`; the one place a literal would be catastrophic (`set_config` for RLS identity) uses a bound param *by design* | all repos, `app/db/database.py` |
| **XSS** | **Low risk, high blast radius.** React escapes by default; one `dangerouslySetInnerHTML` with internally-built content; audit HTML is sandboxed + CSP'd. **But the app has no CSP and the token is 7-day non-revocable** | `ReportViewer.tsx`, `nginx.conf` |
| **CSRF** | **Structurally impossible.** Bearer-only, no cookies, `credentials` never sent | `frontend/lib/api.ts` |
| **SSRF** | **Well defended.** `validate_public_host` at 30 call sites — audits, public funnel, content research, on-page, site-builder, policy-watch, site-analyzer, audit-engine. Called off the event loop because `getaddrinfo` blocks | `app/core/security.py` |
| **Prompt injection** | **Undefended.** See SEC-F | — |
| **Path traversal** | **Defended** in both places it matters: audit artefacts and the data-import upload root both refuse keys that escape their root | `audit_artifacts.py`, `data_import/storage` |
| **Alg confusion / `none`** | **Defended** by a single-entry allow-list | `app/core/auth.py:52` |
| **Tenant impersonation via SQL** | **Defended** — the txn-local identity form cannot be reached by a bound parameter | `app/db/database.py` |

---

## 6. Remediation order

1. **SEC-C** — gate and meter the public audit funnel. *Highest expected loss; live right now.*
2. **SEC-A** — add user suspension and enforce `status` at login and at every request.
3. **SEC-B** — add `jti` + Redis denylist, revoke on suspend/password-change/logout, add an app CSP.
4. **SEC-D** — move the WhatsApp export out of the tree; then rotate credentials (SEC-016).
5. **SEC-E** — rate limiter fails closed on paid and auth paths; widen coverage.
6. **SEC-F / SEC-G** — prompt-injection delimiters and a numeric-output validator.
7. **SEC-H** — make the activity log append-only at the database.
8. **SEC-I / SEC-J** — vault custody runbook; scheduled, alerting, restore-drilled backups covering artefacts.
9. **SEC-K** — confirm OAuth `state` binding.
10. **SEC-L / SEC-M / SEC-N** — delete the mock secrets, the demo store and the operator scripts.
