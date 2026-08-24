# Internal Link Plan - Dental Implants service page (sample-dental)

Per `knowledge/foundations/internal-linking.md` + `cluster-graph-protocol.md`. This is the brand-wide service hub for implants; it links UP to the homepage, ACROSS to related/alternative services, and DOWN to the service-in-city spokes and location pages.

## Links OUT from this page

| Target page | Anchor text (descriptive, not exact-match stuffed) | Why |
|---|---|---|
| Homepage | Sunbridge Dental | Brand/entity anchor |
| /services/dental-bridges | a fixed bridge without grinding down healthy teeth | Named alternative in body |
| /services/dentures | implant-supported dentures | Named alternative in body |
| /services/emergency-dentistry | a cracked or badly decayed tooth | Related intent |
| /santa-monica/dental-implants | dental implants in Santa Monica | Service-in-city spoke |
| /pasadena/dental-implants | dental implants in Pasadena | Service-in-city spoke |
| /glendale/dental-implants | dental implants in Glendale | Service-in-city spoke |
| /santa-monica (location) | our Santa Monica office | Location page |
| /pasadena (location) | our Pasadena office | Location page |
| /glendale (location) | our Glendale office | Location page |
| /about (team) | Dr. Elena Marquez / Dr. David Chen | E-E-A-T author anchor |

## Links IN to this page (recommend adding on)

- Homepage services grid -> "Dental Implants"
- Each location page -> "dental implants" (to this hub, plus to the local spoke)
- Related service pages (bridges, dentures) -> "dental implants" as the fixed alternative

## Rules applied
- Exact-match anchor "dental implants los angeles" used at most once site-wide (not forced here).
- Every spoke links back up to this hub (spoke-to-hub mandatory).
- No 30-link wall; body links are contextual, not a footer dump.
- Validate the live graph with `scripts/link_graph.py` once the site URLs exist.
