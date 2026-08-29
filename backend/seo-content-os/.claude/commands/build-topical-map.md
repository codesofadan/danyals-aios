---
description: Build the client's topical map - the site-level plan of which pages should exist, before any page is written. Runs real-discovery research, filters the service x geography grid down to an evidence-gated node set, classifies core vs outer, and writes clients/<slug>/topical-map.md. The input to a greenfield build and to every /brief.
argument-hint: <client-slug>
allowed-tools: Task, Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

Build the topical map for a client. Argument: `$ARGUMENTS` (the client slug, e.g. `desert-door-pros`).

Read `CLAUDE.md` and `knowledge/foundations/topical-map-protocol.md` first if not already in context. This command runs the pre-writing PLANNING layer. It decides which pages should exist for this business and hands the evidence-gated node set to the page-writers and to `cluster-graph-protocol.md`. It writes no page copy.

**Prime rule (topical-map-protocol.md):** every node traces to a live demand signal or a real capability in `brand.yaml`. No node is proposed from memory. The full service x city grid is the ceiling, never the plan. Every node defaults to `index-only`; it is promoted to `page` only when it has real first-party evidence that makes that page un-copyable.

**Hard line (Law 8):** no topical-authority score, no coverage %, no completeness %. Map quality is the evidence gate, not the node count. Refuse any request to "score" the map.

## Pipeline

Work in `clients/<client-slug>/`.

1. **PROFILE CHECK.** Load `clients/<client-slug>/brand.yaml`. Confirm the `entity` block (`central_entity`, `source_context`), `services`, `service_areas`, and `competitive_set` are filled. If `entity` or `competitive_set` is empty (an older profile), STOP and run `/new-client` (or the SME profile interview) to fill them first - the map roots in these fields and cannot be built without them.

2. **BUILD.** Launch the **topical-map-architect** agent with the client slug. It runs the real-discovery research (autocomplete, PAA, related searches, ranking competitor architectures, GBP categories/Services), builds the grid ceiling, applies the demand filter and the user-cluster merge, classifies every node core or outer, sets each node's status by the evidence gate, orders the publishing plan core-first, and writes `clients/<client-slug>/topical-map.md` from `templates/topical-map.md`. It halts and flags any node whose demand is real but whose promotion evidence is missing (that node stays `index-only`). **Non-destructive re-run:** if a map already exists, the architect updates it in place - it reads the current map first and preserves operator edits, held-node evidence notes, and each node's `build_state`, changing only what real re-discovery warrants, then reports the diff (nodes added / promoted / demoted) rather than overwriting.

3. **ENFORCE (evidence gate).** Run the deterministic gate on the map the architect just wrote:
   ```bash
   python scripts/topical_map_lint.py clients/<client-slug>/topical-map.md --manifest clients/<client-slug>/brand.yaml
   ```
   Exit 0 = every `status: page` node carries a real `evidence` line and `info_gain_thesis`. Exit 1 = an unbacked promotion (a node marked `page` with empty/placeholder evidence). On failure, route back to the architect to either demote the flagged node to `index-only` or supply the missing first-party fact, then re-run. The map does not pass to review until the lint is clean. This is the machine backstop to the architect's judgment; do not skip it.

4. **REVIEW HANDOFF.** The map is an operator-review artifact, like `/brief`. Do not auto-proceed to writing pages. Report the map summary and stop, so the operator can confirm the node set and supply evidence for held nodes before a build.

## Output contract

Confirm `clients/<client-slug>/topical-map.md` exists and is filled from the template. Report to the operator:
- **Grid ceiling vs map size:** N candidate cells filtered down to M nodes (P promoted to `page`, H held at `index-only`).
- **The publishing plan:** the ordered core-first list of `page` nodes.
- **Held nodes and their missing evidence:** the specific first-party fact each `index-only` node is waiting on (this is the SME's homework; supplying it promotes the node).
- **Any coverage-inflation flags:** demand found for a city not in `brand.yaml.service_areas` (do not add it; flag it).

Then stop. The next step is either the operator supplying evidence for held nodes, or a greenfield build that runs the write pipeline per `page` node in publish order (feeding each node's `info_gain_thesis` into `/brief`).

**Note (not enrolled here):** the map is a plan, not a shipped page. Nothing is enrolled by this command. Enrollment (Law 18) happens per page when each promoted node is written and finalized.