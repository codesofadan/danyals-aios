# Research Input - <brand_name> (<slug>)

Browser-captured demand signals the agents cannot fetch themselves (live Google autocomplete
and PAA are JavaScript-gated). This is Tier A, the ground truth, per
`knowledge/foundations/research-input-protocol.md`. Capture from a LOGGED-OUT (incognito)
browser set to the target city. Fill what you can; any node whose demand can only come from
autocomplete/PAA stays a flagged candidate until this file supplies it.

Save to `clients/<slug>/research-input.md`.

- **Captured from city:** <the city the SERP was queried from>
- **Capture date (PKT):** <YYYY-MM-DD>

---

## 1. Autocomplete (per seed service x top city)

For each seed service crossed with the top cities, type it into the Google box logged-out and
paste the dropdown. Then the alphabet-soup pass ("[service] [city] a", "...b", ...) for the
terms worth keeping.

- `<service> <city>`: <dropdown suggestions>
- `<service> near me`: <suggestions>
- alphabet-soup keepers: <the a..z suggestions that are real variants>

## 2. People Also Ask (verbatim)

Search each head `<service> <city>` and `<service>` query, open the PAA box, expand it, and
paste the questions exactly as shown. These become FAQ entries and passage-block leads too.

- "<PAA question 1>"
- "<PAA question 2>"
- ...

## 3. Related searches (foot of the SERP)

Paste the "Related searches" / "People also search for" block from the bottom of each SERP.

- <comma-separated, verbatim>

## 4. Ranking competitors (per head query)

For each head query, the top 3-5 organic + local-pack competitors. From each, note the page
type and the services/cities in their nav (their validated demand map).

| Head query | Competitor URL | Page type | Services / cities in their nav |
|---|---|---|---|
| <ac repair tempe> | <url> | service-in-city | <their service + city list> |

## 5. Map-pack GBP categories

The primary/secondary GBP categories the map-pack competitors chose (visible on their profiles).

- <competitor> - primary: <category>; secondary: <categories>

---

**Note on completeness:** the agent also runs its own `WebSearch` (Tier B) and competitor
`WebFetch` (Tier C), so this file does not need to be exhaustive to be useful. The parts only a
human browser can capture are sections 1 and 2 (autocomplete + PAA); those are the highest-value
rows to fill, because they are exactly what the agent's tools cannot fetch.
