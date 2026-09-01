# Internal Links - Climate Controlled Storage in Round Rock

Link plan for the climate-controlled money page (storage-type x city). Follows `knowledge/foundations/internal-linking.md` + `knowledge/foundations/storage-topical-map.md` (the facility page is the hub every axis links back into). [SAMPLE] client; URLs are placeholders.

## Outbound (from this page)

| Anchor text | Target | Why |
|---|---|---|
| the Round Rock building / our Round Rock facility | `/round-rock/` (facility page) | UP the silo to the facility hub (mandatory spoke->hub) |
| a 10x10 climate unit | `/round-rock/10x10-storage-units/` (unit-size page) | ACROSS to the size axis (the size the copy references) |
| a drive-up unit is cheaper | `/round-rock/drive-up-storage/` (sibling storage-type) | ACROSS to the sibling type (the honest cheaper alternative) |
| what fits in each size | `/storage-unit-sizes-guide/` (size-guide asset) | ACROSS to the informational asset (the dual-node partner) |
| Pflugerville | `/pflugerville/` (other facility) | lateral to the sibling facility (only where genuinely relevant) |

Anchor text is descriptive and varied (no exact-match "climate controlled storage round rock" stuffed on every link, per G5). 4-5 contextual links, placed at decision-relevant moments in the body, not a footer block.

## Inbound (links TO this page - assigned by link-architect)

| From | Anchor |
|---|---|
| `/round-rock/` facility page | "climate-controlled units (55-80F, dehumidified)" |
| `/round-rock/10x10-storage-units/` unit-size page | "our climate 10x10s" |
| homepage (Round Rock climate feature) | "climate storage in Round Rock" |
| `/storage-unit-sizes-guide/` asset | "climate storage near you" (bridge to live inventory) |

## Graph notes

- This node is `core` (converts). Link equity flows outer -> core: the size-guide asset and the About page link into it more than it links back out.
- It is NOT orphaned: reachable from the facility page, the 10x10 page, and the homepage.
- `link_graph.py` persists this node into `clients/sample-storage/` link graph on FINALIZE (Law 10), via `link-architect`.
