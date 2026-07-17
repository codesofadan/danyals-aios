---
name: local-seo
description: Reports a client's map-pack rankings and audits their Google Business Profile completeness and NAP consistency across directories. Use when an operator asks about map-pack or local-pack rankings, "do we show in the 3-pack", GBP or Google Business Profile completeness, missing categories or hours, NAP consistency across directories, or wants to add a local keyword or refresh local ranks. Refreshing SPENDS metered budget. GBP sync is read-only and currently always holds. There is no geo-grid.
argument-hint: "[client] [location]"
arguments: [client, location]
model: opus
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py:*), Read
---

# Report Map-Pack Rank and Audit the GBP Profile

**Purpose.** Report `$client`'s map-pack positions for `$location`, audit the Google Business
Profile's completeness, and surface NAP inconsistencies across directories — using only what the
backend measured.

**Who runs it.** Reading needs `view_reports`. Creating/patching a ranking, refreshing, and
creating/patching/syncing a profile are **LEAD-only** (owner/admin/manager). Every route needs
the `local_seo` feature grant. Lacking either → 403 → report which one and STOP.

## Required inputs / keys
- `$client` — the client name, resolved to a real `client_id`. Never invent an id.
- `$location` — the profile's location label / the `geo` for a map-pack check.
- `AIOS_BASE_URL` (default `http://localhost:8000/api/v1`) and `AIOS_SKILL_TOKEN`.
- The map-pack provider must be live server-side for real ranks; the paid check is gated in the
  **worker** (dial `local_seo`), so a refresh can never bypass the money dial.
- **GBP sync is approval-gated and currently ALWAYS holds.** Without the Google OAuth client it
  returns `{queued: false, held: true, reason: "no_oauth_client"}` at 202. Even WITH OAuth set,
  no GBP reader is wired, so the worker holds. **This hold is the designed steady state, not an
  error and not a bug.** Report it as "GBP sync pending the approval-gated Google API".

**Trigger.** Map-pack / local-pack rankings, "do we show in the 3-pack", GBP completeness, missing
categories or hours, NAP consistency across directories, adding a local keyword, refreshing ranks.

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Resolve the client (resolve-client)
- [ ] Step 2: Read the profiles + the local stats
- [ ] Step 3: Read the map-pack rankings (rank=null means NOT in the pack)
- [ ] Step 4: Run the GBP audit + the NAP alignment report
- [ ] Step 5: Refresh / sync only if asked; render the pinned output
```

1. **Resolve the client.** Run `python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py
   resolve-client --client "$client"` → `GET /clients` (name match). Capture `client_id`.

2. **Read the profiles and stats.** Run `aios_client.py get "/local-seo/profiles?clientId=<id>"`
   → `GET /local-seo/profiles` (one profile with `aios_client.py get /local-seo/profiles/<profile_id>`
   → `GET /local-seo/profiles/{profile_id}`) and `aios_client.py get /local-seo/stats` →
   `GET /local-seo/stats`. Fields: `reference/part8-output-formats.md` §5.

3. **Read the map-pack rankings.** Run `aios_client.py get "/local-seo/rankings?clientId=<id>"` →
   `GET /local-seo/rankings`. The field is **`rank`**, not `position`. History:
   `aios_client.py get "/local-seo/rankings/<ranking_id>/history?limit=30"` →
   `GET /local-seo/rankings/{ranking_id}/history`.

4. **Audit the profile and the NAP.** Run `aios_client.py get /local-seo/profiles/<profile_id>/audit`
   → `GET /local-seo/profiles/{profile_id}/audit` (recomputed fresh; `findings` keys are
   snake_case, values `ok|missing|thin`) and `aios_client.py get
   /local-seo/profiles/<profile_id>/nap-alignment` → `GET /local-seo/profiles/{profile_id}/nap-alignment`.

5. **Mutate only on request.** Add a local keyword: `aios_client.py post /local-seo/rankings --json
   '{"profileId":"<pid>","keyword":"<kw>","geo":"$location"}'` → `POST /local-seo/rankings` (201).
   Pause one: `aios_client.py patch /local-seo/rankings/<ranking_id> --json '{"isActive":false}'`
   → `PATCH /local-seo/rankings/{ranking_id}`. Kick the refresh sweep: `aios_client.py post
   /local-seo/rankings/<ranking_id>/refresh` → `POST /local-seo/rankings/{ranking_id}/refresh`.
   Upsert a profile: `POST /local-seo/profiles` / `PATCH /local-seo/profiles/{profile_id}`. Try a
   sync: `aios_client.py post /local-seo/profiles/<profile_id>/sync` → `POST
   /local-seo/profiles/{profile_id}/sync`. Render the **Output format**.

## Decision points
- If `rank` is **null** → the business is **not in the map pack** for that keyword/geo: checked
  successfully, not present. It is **never** a failed check and **never** "position 0". A failed
  check writes nothing at all, so every null is a real observation. Report "not in the pack".
- If `POST /local-seo/profiles/{profile_id}/sync` returns `held: true, reason: "no_oauth_client"`
  → **this is NORMAL, not an error.** Report "GBP profile sync is pending the approval-gated
  Google API". Do not retry, do not treat it as a failure, do not report the profile data as stale
  because of it.
- If a sync returns `queued: true` → **that still does not mean a sync will happen.** No GBP
  reader is wired, so the worker holds. Do not promise refreshed profile data off a `queued: true`.
- If the operator asks for a **geo-grid**, a grid scan, a radius sweep, or a heatmap → **it does
  not exist and is out of contract scope.** The provider takes a single scalar `geo`; there is
  structurally nowhere to put grid points. Say so plainly; do not simulate one by fanning out
  checks across invented coordinates.
- If a refresh is requested → note that `POST /local-seo/rankings/{ranking_id}/refresh` **kicks the
  whole due sweep, not just that row.** The `ranking_id` only selects the 404 check and the echoed
  `id`. Do not tell the operator one keyword was refreshed.
- If `avgRating` is **null** → the profile has never synced. Report "not synced", not `0.0`.
- If `avgMapRank` is `0.0` → nothing ranks (it excludes unranked and inactive rows). Report it as
  "no ranked rows", not as an average of zero.
- If the audit's `findings` show `thin` → the field exists but is under-filled; `missing` lists
  every field whose verdict is not `ok`. Report the backend's verdicts verbatim; do not re-grade.
- If a NAP directory row is `cosmeticOnly: true` → the difference is formatting, not a real NAP
  inconsistency. Do not escalate it as a citation error.

## Common Pitfalls
- "`rank` is null — we dropped out of the pack." → Null means checked and not in the pack. Without
  a prior ranked history point there is no drop to report. A failed check writes nothing.
- "The sync held, so GBP is broken." → The hold is the expected steady state (the Google API is
  approval-gated and no reader is wired). It is not an error and needs no fix from the operator.
- Reporting a `queued: true` sync as "profile refreshed" → nothing synced; the worker holds.
- Building a geo-grid by looping checks over made-up lat/lng points → out of scope, and the
  invented coordinates would fabricate data. Refuse and explain.
- "The refresh updated this keyword." → It kicks the entire due sweep. Say "refresh sweep kicked".
- Using `position` → the field is **`rank`**. `position` does not exist here.
- Quoting `completeness` from the profile as the audit result → the audit **recomputes** fresh.
  Use the audit's own `completeness` and `findings`.
- Escalating a `cosmeticOnly` NAP difference as an inconsistency → it is formatting only.
- Inventing `googleLocationId` in a report → it is write-only in practice; no read route returns it.

## Output format
Emit verbatim (values copied from the endpoints; never from memory):

```
LOCAL SEO — <client> · <location>
Profiles: <gbpProfiles>   Avg map rank (ranked rows only): <avgMapRank>   Citations: <citations>

GBP PROFILE [<id>] — <location>
  Place ID: <placeId>   Primary category: <primaryCategory>   Secondary: <secondaryCategories>
  NAP: <napName> / <napAddress> / <napPhone>       Website: <website>
  Reviews: <reviewCount>   Avg rating: <avgRating | "not synced (null)">
  Completeness: <completeness>   OAuth connected: <oauthConnected>   Last synced: <lastSyncedAt|never>

GBP AUDIT (recomputed fresh):
  Completeness: <completeness>
  Findings: <field>=<ok|missing|thin> ...
  Missing/thin: <missing or "none">

NAP ALIGNMENT: aligned=<aligned>
  consistent=<consistent>  inconsistent=<inconsistent>  missing=<missing>  cosmeticOnly=<cosmeticOnly>
  <directory>: <status> <"(cosmetic only - formatting, not a real inconsistency)" if cosmeticOnly> — "<note>"
  ...

MAP-PACK RANKINGS (rank=null means NOT IN THE PACK, not a failed check):
  <keyword> (<geo>)  rank=<rank | "not in pack">  prev=<previousRank|none>  change=<change>
                     inPack=<inMapPack>  url=<foundUrl|none>  provider=<provider>  active=<isActive>
                     top competitors: <topCompetitors>   checked=<lastCheckedAt|never>
  ...

Action taken: <read-only | ranking added | ranking paused | refresh sweep kicked | sync attempted>
GBP sync: <"held: no_oauth_client -> pending the approval-gated Google API (NORMAL, not an error)"
  | "queued: true -> but no GBP reader is wired, so the worker holds; no data will refresh">
Geo-grid: NOT AVAILABLE (out of contract scope - single scalar geo, no grid/radius/heatmap).
```

Exact response fields + the null-rank / hold / no-geo-grid rules:
`reference/part8-output-formats.md` §5.
