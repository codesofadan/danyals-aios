# Module 05 — Web 2.0 & Social Publishing

What was rebuilt against [`M05`](../../docs/aios-v2/modules/M05-web2-and-social.md), what
is reachable from the API, and what is honestly still missing.

The module's pure logic lives in `app/modules/web2/`; the v1 pipeline it calls
(`app/services/web2_*`, `integrations/web2_publishers.py`) is unchanged except where noted.

---

## 1. The content model — why a note is not a short article

`platform_spec.py` holds a measured content model for **53 platforms**, each citing the
adapter behaviour it was derived from. It exists because of this, read off the adapters:

```
MastodonClient._MAX_CHARS = 500     text[: self._MAX_CHARS]
BlueskyClient._MAX_CHARS  = 300     text[: self._MAX_CHARS]
WarpcastClient._MAX_CHARS = 320     text[: self._MAX_CHARS]
PlurkClient                         content[:360]
```

A 900-word article is ~5,500 characters. A Bluesky placement was **the first 300
characters of a blog post, cut mid-sentence, with the editorial backlink sliced off the
end** — and the row reported `verified`, because the API did return a URL. 13 platforms
truncate; 21 more run `_html_to_text` and discard every heading and link.

`content_generator` clamps to a **600-word floor**, so a 300-character placement was never
a shrunken article — it is a different artifact. `note_composer.py` composes it, fits it at
a **sentence** boundary, and reserves room for the `anchor: url` the adapter appends
afterwards (a body filling the ceiling deletes exactly the link the property exists for).

`tests/test_web2_platform_spec.py` re-derives the truncation facts from adapter **source**
and fails when a spec drifts from the code it describes.

---

## 2. One client login, and the accounting that keeps it honest

`client_credentials.py` + migration 0151. The operator enters a client's username and
password once; it is the client's identity on every platform. What it can actually do,
measured against `PLATFORM_CREDENTIAL_FIELDS`:

| | Platforms |
|---|---|
| publishes directly with username + password | **8** |
| takes an app password generated in-account | **2** (Bluesky, WhiteWind) |
| requires an OAuth grant or access token | **43** |

So 43 of 53 need a token no password substitutes for. `GET
/offpage/web2/clients/{id}/connection-plan` reports three buckets — `ready`, `one_step`
(with the **one named action**), `blocked` — rather than a grid of cards all saying
"Connect". Readiness is computed from credential shapes and sealed-account state; **the
vault is never opened** to answer "is a credential held".

The password is sealed under `<client_id>:web2-login`, separate from the mailbox
credential, and a blank field never clears it (clearing is explicit).

---

## 3. Compose once, publish everywhere

`broadcast.py` → `POST /offpage/web2/broadcast/plan`. One subject, a platform tick-list or
`All`, and you see the whole fan-out **before anything is drafted or paid for**.

It fans out into *variants*, not copies, because of a measured run:

```
same client, SAME topic, 30 platforms  -> body r = 1.000  (all thirty blocked)
same client, DISTINCT topics           -> body r = 0.034  (pass)
```

Three axes differentiate them: **shape** (article / note / snippet), **angle** (a distinct
facet per article), **framework** (rotated — measured to halve heading resemblance
0.406 → 0.208). Running out of distinct angles is reported *before* the drafts are paid
for. Excluded platforms are reported with reasons; a selection is never silently shrunk.

---

## 4. The safety spine

| Control | Where | What it was before |
|---|---|---|
| Account health (A9) | `account_health.py`, publish path | Only `suspended`/`deleted` blocked — **`degraded` published as if healthy**, and that is the early-warning state |
| House property cap (A6) | 0150 trigger | `property_count` was read, rendered, and **incremented nowhere** — the cap could never trip |
| Idempotency (A3) | 0150 unique index | Status check is read-then-write; two workers could both publish |
| Link liveness (A8) | `placed_links.py` + 0150 | Three mutable columns — "live in March, lost in June" was unanswerable |
| Anchor distribution (A5) | `anchor_bank.py` | Per-anchor floor only; no profile shape |
| Pacing (A4) | `release_guard.py`, publish path | No same-minute rule existed at all |
| Medium (A12) | `web2_pipeline.run_publish` | `DRAFT_ONLY` — accepted, **paid for a draft**, settled at `pending` forever |

Two properties worth knowing:

- **`unknown` never overwrites a known link state.** An unreachable page is a fact about
  our fetch, not their link — without this, one flaky night reports every live link in the
  portfolio as lost, to the client.
- **The pacing guard returns `None` on any error.** A check that exists to *space*
  publishes must never become the reason nothing publishes.

---

## 5. Parasite Poster

`parasite.py` + migration 0152. Host selection by authority and topical fit, with §6's
guardrails: terms must **permit** (an unread terms page is an unknown, not a yes — 72
catalogue rows sit at an unreviewed default), one page per term per host, must be able to
rank, must be fetchable.

**A11 was impossible before 0152.** `tracked_keywords` was unique on
`(client_id, normalized_keyword, engine, device, location, language)` and `add_keywords`
inserts `ON CONFLICT DO NOTHING` — so tracking a parasite page for a term the client
already tracked was silently skipped. §6's premise is that parasite pages target terms the
client *cannot yet rank for*, which are exactly the terms already in the tracker. **The
feature collided with itself by design and reported success while nothing measured it.**
`hosted_url` is now in the key, so the hosted page and the client's own site are tracked
side by side — which is the comparison the tactic exists to produce.

> `rank_tracker/repo.add_keywords`' `ON CONFLICT` target must equal that index exactly. A
> mismatch raises on **every** insert rather than failing quietly.

---

## 6. Reachable API surface, and the screens on it

```
GET  /offpage/web2/clients/{id}/connection-plan   readiness, 3 buckets, named actions
PUT  /offpage/web2/clients/{id}/identity          + shared username/password (sealed)
POST /offpage/web2/broadcast/plan                 compose once → fan-out preview
GET  /offpage/placed-links?clientId=&state=       link ledger, LOST-FIRST
```

Lost-first ordering is the point of the last one: sorted by date, the three links that went
missing sit under two hundred that are fine.

All four are on `/admin/web2` (`components/offpage/Web2Tab.tsx`):

| Screen | Component | What it is for |
|---|---|---|
| **Publishing access** tab | `Web2ConnectionPlan` | the client's ONE login, plus the 3 buckets and the single named action per platform |
| **Write once, publish everywhere** button | `Web2BroadcastComposer` | subject → platforms (or All) → fan-out preview → commit |
| **Link health** tab | `Web2PlacedLinks` | the ledger, lost-first, with `unknown` counted apart from `live` |

Two things those screens deliberately refuse to do:

- **The broadcast commit does not publish.** It creates a campaign, so every placement is
  drafted and then held at the review gate. A button reading "Publish everywhere" would
  describe something the pipeline does not do, and the copy says so at the moment of
  committing.
- **`All` is an explicit control, not an empty selection.** The route refuses a blank list
  on purpose — "none chosen" and "everywhere" are different intentions — so the composer
  sends the `__all__` sentinel, and ticking any platform by hand releases All.

> `Web2ArticleWizard` and `Web2BroadcastComposer` self-wrap in `.tw`. The overlay styles are
> scoped `.tw .modal-scrim` in `globals.css` and **the admin layout provides no `.tw`** —
> without the wrapper a modal renders inline as a card in the page flow, with the table it
> is supposed to cover still scrolling underneath. `CitationCampaignModal` carries the same
> note; the wizard was missing it and was wrong on this page until 2026-09-19.

---

## 7. What is NOT built

- **Every mainstream social platform** — X, Facebook, Instagram, LinkedIn, Threads, TikTok,
  YouTube, Pinterest. No adapters, no credentials. **A1 (≥15 platforms) cannot be met**
  until the developer apps exist: X needs a paid tier, Meta and TikTok need app review.
  This is procurement, not code.
- **A parasite commit route.** `broadcast/plan` previews and the composer commits it
  through `POST /offpage/web2/campaigns`, so that path is closed. Parasite host selection
  into a published page is not: `parasite.py` chooses and refuses, and nothing publishes
  what it chose.
- **Credential checks on the house accounts.** All 24 sit at `health='unverified'`, so
  `account_health` — correctly — refuses every one of them, and the broadcast preview
  currently answers *"this account has never passed a credential check, so nothing is
  known about it"* for the whole selection. Nothing can publish until a check runs. This
  is the fail-closed design working, not a defect, but it is the ONE thing standing
  between the composer and a real placement.
- **Calendar, My Posts, analytics** (REQ-W2-016/017). Analytics in particular needs
  per-platform metrics APIs that most blog platforms simply do not expose — expect
  provenance gaps rather than a full grid.
- **Video posting** (P1 in M05).

## 8. Guards

| Guard | Catches |
|---|---|
| `test_web2_platform_spec.py` | a spec drifting from the adapter it describes |
| `test_web2_note_composer.py` | a note that overruns, or loses its link to truncation |
| `test_web2_account_health.py` | a degraded account publishing; a cap that cannot trip |
| `test_web2_placed_links.py` | `unknown` overwriting a known state; `lost_at` re-stamping |
| `test_web2_anchor_bank.py` | an exact-match anchor; a profile out of shape at any prefix |
| `test_web2_release_guard.py` | two properties in one minute, at A4's stated 200-post load |
| `test_web2_parasite.py` | an unreviewed host; a doorway set; an untracked page |
| `test_web2_surfaces_router.py` | the three routes, driven through the real app |
