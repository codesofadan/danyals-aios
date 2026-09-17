# M09 · Indexing

Requirements: `REQ-IDX-001` … `REQ-IDX-005`.

Publishing a page is not the deliverable. A page that is **indexed** is the deliverable.
This module closes that gap and — more importantly — measures whether it closed.

---

## 1. Submission

Three channels, each with its own quota and its own honest accounting:

| Channel | Scope | Quota reality |
|---|---|---|
| **Google Indexing API** | Officially job postings and livestreams; used broadly in practice | Per-project daily quota, typically 200/day. **Must be measured against real publish volume before launch** — at 100 clients this is the binding constraint |
| **IndexNow** | Bing, Yandex, Seznam, Naver | Generous; key file hosted on the client domain |
| **Bing Webmaster** | Bing direct | Per-site daily quota |

`REQ-IDX-002`: **quota accounting with a pre-submit check.** A submission that would exceed
quota is **queued**, not dropped and not silently discarded. The queue drains on the next
window. A dropped submission that reported success is exactly the class of dishonesty this
platform exists to eliminate.

## 2. Registration

`REQ-IDX-004`. Automatic, via domain events — no module calls this one directly:

- `content.page.went_live` → register the URL
- `content.page.updated` → re-register
- `web2.post.published` → register the property URL (a Parasite Poster page that is not
  indexed is not a deliverable)

## 3. Verification

`REQ-IDX-003`. Submission is not indexation. A scheduled job re-checks index state and
records it with provenance:

- Where GSC is connected (M07), the URL Inspection API is the authoritative check.
- Otherwise, a `site:` query through the SERP provider, labelled as the weaker signal it is.

States: `submitted` · `indexed` · `not_indexed` · `excluded` (with the reason where
available) · `unknown`. `unknown` is a real state and is displayed as such.

## 4. Sitemaps

`REQ-IDX-005`, P1. Where we control the client's sitemap (our WordPress plugin is
installed), generate and ping it on publish. Where we do not, read it and report staleness.

## 5. Acceptance criteria

| # | Criterion |
|---|---|
| A1 | A publish event registers the URL without the content module calling this one |
| A2 | A submission exceeding quota is queued and drains in the next window; nothing is lost |
| A3 | Quota accounting matches the provider's own count across a week of real submissions |
| A4 | Index verification distinguishes `indexed`, `not_indexed` and `unknown`, and never reports `indexed` on an unverified URL |
| A5 | A client report shows submitted-vs-indexed honestly, including the `unknown` count |
| A6 | IndexNow key file presence is probed per client domain and its absence is a named degraded capability |
