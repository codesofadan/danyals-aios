# 07 · Security

The system holds, for 50–100 businesses: WordPress admin credentials, Google OAuth tokens,
32 platforms' publishing credentials, directory account passwords, business phone numbers
and addresses, and the agency's own provider keys. A breach here is a breach of every
client at once.

---

## 1. Threat model

| Threat | Realistic? | Control |
|---|---|---|
| Cross-tenant data access through an application bug | **Very likely** — v1's most probable defect class | Postgres RLS as the primary boundary, adversarial CI gate |
| Credential exfiltration via logs, errors or API responses | **Likely** — the classic accidental leak | Envelope encryption, a scrubbing layer, and a CI check that greps for secret-shaped strings in log statements |
| A compromised operator machine using the extension | **Plausible** | Short-lived, client-scoped operator tokens; no credentials in the extension; every action audited |
| SSRF via a user-supplied URL (audit target, design source, WordPress endpoint) | **Likely** — we fetch URLs users give us | Strict URL validation, DNS resolution pinning, private-range blocking, a dedicated egress path |
| Prompt injection from scraped pages into an agent with tools | **Plausible** | Untrusted-content framing, no tools on scraping nodes, no submit capability in the citation graph |
| Stored XSS via generated content rendered in the dashboard | **Plausible** | Content rendered as data, never `dangerouslySetInnerHTML` on model output; preview in a sandboxed iframe |
| Privilege escalation between staff roles | **Plausible** | Capability strings resolved server-side; no client-trusted role |
| Supply-chain compromise of a dependency | **Possible** | Lockfiles, pinned digests for base images, dependency audit in CI, no `curl | sh` in any build |
| A client's WordPress being damaged by us | **Likely if careless** | Draft-first publishing, versioned publishes, one-click revert, capability probe before writing |

---

## 2. Identity and access

### Authentication
- **argon2id** password hashing with per-user salt and tuned parameters; no legacy hashes
  carried over from v1.
- **TOTP MFA mandatory** for Owner and Admin (`REQ-CORE-002`); optional elsewhere.
  Recovery codes issued once, hashed at rest.
- Access tokens live in memory only. Refresh tokens are `HttpOnly`, `Secure`,
  `SameSite=Strict`, rotated on every use, with reuse detection that revokes the family.
- Failed-login throttling per account and per IP; lockout with an owner-visible alert.
- Session list per user with remote revoke.

### Authorisation
- **Capability strings**, not roles, at every enforcement point:
  `content:publish`, `citations:submit`, `vault:read`, `cost:set_dial`, `client:*`.
- Roles map to capability sets in one table. A handler comparing `user.role` fails review.
- Every capability check happens **server-side**. The frontend hides what a user cannot do
  as a courtesy, never as a control.
- Client-portal principals carry a bound `client_id`; their token cannot address another.

### Operator tokens (extension)
- Opaque, 8-hour maximum, bound to one `user_id` **and** one `client_id` **and** one
  session.
- Carry only `citations:analyze` and `citations:record`. They cannot read the vault, list
  clients, or touch any other module.
- Revocable individually and en masse; revocation is immediate (checked per request, not
  cached).

---

## 3. Tenant isolation

Specified in [`04-DATA-MODEL.md`](04-DATA-MODEL.md) §2. The security-relevant points:

- `FORCE ROW LEVEL SECURITY` — so the boundary applies even to the table owner, which is
  the connection the application actually uses.
- The tenant context is set **once**, in the session factory, from the authenticated
  principal. No other code may call `set_config`. A grep gate enforces this.
- Workers set the same context from the job's `client_id` before executing a handler.
- `TenantViolationError` is not an ordinary error: it triggers a Sentry alert at
  `fatal`, writes an activity-log row, and pages the owner.
- The adversarial RLS suite runs on every PR and attempts a cross-tenant read against
  **every** tenant table, not a sample.

---

## 4. Secrets

### At rest
- **Envelope encryption.** Each secret gets a per-secret DEK; the DEK is wrapped by a KEK
  held outside the database (environment variable in production, `age` file locally).
- Ciphertext columns are `bytea` and are never selected outside `platform/vault`.
- Per-client sealing: a client's secrets are wrapped with a client-scoped key, so
  offboarding a client by destroying their key destroys their secrets irrecoverably.
- **Rotation** is a first-class operation with a documented runbook per provider. Every
  credential exposed during v1's development is rotated before v2 touches production.

### In use
- `vault.get(secret_id, purpose, job_id)` is the only read path, and it writes an access
  log row every time.
- Secrets are **never**: placed in a job payload, returned by any API, written to a log,
  included in a Sentry event, put in an environment variable of a worker process for a
  specific client, or sent to LangSmith.
- Provider clients receive secrets as constructor arguments held in memory for the
  duration of the call.

### In transit
- TLS everywhere, HSTS with preload, TLS 1.2 minimum.
- The extension talks only to the configured API origin, declared in the manifest's
  `host_permissions`.

### CI enforcement
- `gitleaks` on every PR and a pre-commit hook.
- A check that fails the build if a log or exception statement interpolates a variable
  named like a secret (`*key*`, `*token*`, `*password*`, `*secret*`).
- No `.env` file is ever committed; `.env.example` carries names only.

---

## 5. SSRF and outbound fetching

We fetch URLs that users control: audit targets, the previous-website URL, WordPress
endpoints, directory pages, sitemap URLs. This is the single most likely remote-exploit
path in the system.

**Every outbound fetch of a user-supplied URL goes through `platform/providers/fetch.py`,
which:**
1. Parses and rejects anything that is not `http`/`https`.
2. Rejects credentials in the URL, non-standard ports, and URLs longer than a sane cap.
3. Resolves DNS itself, rejects private, loopback, link-local, multicast and reserved
   ranges (IPv4 **and** IPv6), and **pins the resolved IP for the connection** — closing
   the DNS-rebinding window between check and connect.
4. Re-validates on every redirect, with a redirect cap.
5. Enforces a response size cap and a timeout.
6. Never forwards our own headers, cookies or credentials to a third-party host.

The browser workers run with no access to the internal network — they can reach the
internet and nothing else. This is a network-level control, not an application one.

---

## 6. Content safety

| Surface | Control |
|---|---|
| Model output rendered in the dashboard | Rendered as text nodes. `dangerouslySetInnerHTML` is banned outside the page-preview component, which renders in a **sandboxed iframe** with no same-origin access |
| Generated HTML published to WordPress | Sanitised against an allow-list of tags and attributes before it becomes a block tree; no `<script>`, no inline event handlers, no `javascript:` URLs |
| Scraped page content entering a prompt | Wrapped in a delimited untrusted block; the node reading it has no tools |
| Uploaded files | Type sniffed, not trusted by extension; size-capped; served from a separate origin with `Content-Disposition: attachment` |
| Directory form values | The fill plan is validated field-by-field against the client's own profile values before being offered; the agent cannot invent a value to type |

---

## 7. Extension security

- **Minimum permissions.** `activeTab` and explicit `host_permissions` for the API origin.
  No `<all_urls>`, no `tabs`, no `cookies`, no `webRequest`.
- **No credentials, ever.** The extension does not hold, cache or display a password. The
  account-creation graph generates credentials **server-side** and vaults them; the
  extension receives only a fill plan for the current form.
- **No page content leaves the browser** except: a PII-free structural digest of the form,
  and the explicit field-value set the operator can see before it is used.
- Content scripts are isolated-world; no page script can address the extension.
- The side panel shows every value that will be typed, with low-confidence fields flagged
  and never silently applied.
- **There is no submit capability.** The extension cannot dispatch a form submission or
  click a submit control. This is a code-level absence, verified by a test.

---

## 8. Dependency and build security

- Lockfiles committed (`uv.lock`, `pnpm-lock.yaml`); CI installs from the lock only.
- Base images pinned by digest.
- `pip-audit` / `npm audit` on every PR; a new critical advisory fails the build.
- No build step downloads and executes a remote script.
- Containers run as a non-root user with a read-only root filesystem where possible.

---

## 9. Audit and monitoring

Every one of these writes an immutable activity-log row with actor, target and before/after:

authentication events · capability grants · vault reads, writes and rotations · money-dial
changes and budget edits · global halt toggles · every publish, submission and campaign
start · client creation and offboarding · every RLS violation · every manual override of
an automated decision.

**Alerts that page immediately:** a tenant violation · a vault read with no job context ·
a spend rate exceeding 3× the trailing average · repeated authentication failures against
one account · any 5xx rate above baseline · a provider returning a contract-breaking
response.

---

## 10. Data protection

- **Client data lives in one jurisdiction** — the VPS region. No client data is sent to a
  third party except the named providers, each of which is listed in the DPA.
- **Provider disclosure:** a page in the docs lists every third party that receives client
  data and what they receive. It is kept current because the client will eventually ask.
- **Deletion on offboarding** (`REQ-X-008`): destroy the client key (which destroys their
  secrets), hard-delete their rows after the retention window, and record the deletion.
- **Backups are encrypted** at rest with a separate key, stored off-host, and a restore is
  drilled before hand-over.
- **PII in observability:** Sentry runs with `send_default_pii=False` and a `before_send`
  scrubber. LangSmith is self-hosted by default for exactly this reason.

---

## 11. Pre-hand-over security checklist

- [ ] Every credential exposed during v1 development rotated
- [ ] MFA enforced on Owner and Admin
- [ ] RLS adversarial suite green against every table
- [ ] `gitleaks` clean across full history, not just HEAD
- [ ] SSRF suite green, including the rebinding case
- [ ] Extension permission set reviewed and minimal
- [ ] Backup restored into a clean host and verified
- [ ] Provider disclosure page current
- [ ] Dependency audit clean of criticals
- [ ] An owner-operated kill switch verified working for each module
