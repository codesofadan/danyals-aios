# Page-layout templates (the shared layout doctrine)

> GENERATED from `backend/app/services/page_blueprints.py` — do not edit by
> hand. Run `python -m app.services.page_blueprints` to regenerate; a unit test
> (`tests/test_page_blueprints.py`) fails if this file drifts from the module.

These are the canonical, audited section sequences a generated page of each
type is built to. The dashboard content generator and these skills resolve the
SAME blueprint, so a page's structure matches whether it was shaped by an
analyzed site or a chosen template. Invariants: `hero` is first; a trust /
social-proof block sits high on commercial types; `cta` is the last content
section. A `content=false` section is CHROME (trust bars, maps, galleries,
search) the theme / AIOS Publisher plugin supplies — never fabricated copy.

Section kinds are drawn from a controlled vocabulary; each carries a layout
variant (`split`/`grid`/`numbered-steps`/`accordion`/`banner`/…) the publish
path renders as a styled component.

## Service page  (`template=service`)

Default for page type: `service`. Split hero + a repeated CTA (hero + bottom banner); benefits/features as grids.

| # | kind | layout | role | heading |
|---|------|--------|------|---------|
| 1 | `hero` | `split` | content | {primary} |
| 2 | `trust_bar` | `carousel` | chrome | Trusted by |
| 3 | `intro` | `stacked` | content | Why {primary} matters |
| 4 | `benefits` | `grid` | content | The benefits of choosing {client} |
| 5 | `features` | `grid` | content | What's included |
| 6 | `process` | `numbered-steps` | content | How it works |
| 7 | `proof` | `stacked` | content | Proven results |
| 8 | `testimonials` | `carousel` | content | What clients say |
| 9 | `pricing` | `cards` | content | Pricing |
| 10 | `faq` | `accordion` | content | Frequently asked questions |
| 11 | `cta` | `banner` | content | Get started with {primary} |

## Location page  (`template=location`)

Default for page type: `local`. Location-specific hero + real photos; NAP/hours/map are theme-supplied chrome.

| # | kind | layout | role | heading |
|---|------|--------|------|---------|
| 1 | `hero` | `split` | content | {primary} in {city} |
| 2 | `contact` | `nap` | chrome | Visit us |
| 3 | `hours` | `list` | chrome | Opening hours |
| 4 | `intro` | `stacked` | content | About our {city} location |
| 5 | `services` | `grid` | content | Services at this location |
| 6 | `reviews` | `carousel` | chrome | Local reviews |
| 7 | `team` | `cards` | chrome | Meet the team |
| 8 | `gallery` | `grid` | chrome | Our {city} location |
| 9 | `map` | `map-embed` | chrome | Find us |
| 10 | `service_areas` | `list` | chrome | Areas we serve nearby |
| 11 | `faq` | `accordion` | content | Frequently asked questions |
| 12 | `cta` | `banner` | content | Book at our {city} location |

## Service-area page  (`template=service_area`)

Default for page type: `local`. Lead with service + unique local content, not NAP; explicit covered-areas list.

| # | kind | layout | role | heading |
|---|------|--------|------|---------|
| 1 | `hero` | `split` | content | {primary} in {city} |
| 2 | `trust_bar` | `carousel` | chrome | Trusted locally |
| 3 | `intro` | `stacked` | content | Serving {city} and the surrounding area |
| 4 | `services` | `grid` | content | What we offer in {city} |
| 5 | `service_areas` | `list` | content | Areas we cover |
| 6 | `benefits` | `grid` | content | Why choose {client} |
| 7 | `reviews` | `carousel` | chrome | What local customers say |
| 8 | `process` | `numbered-steps` | content | How it works |
| 9 | `map` | `map-embed` | chrome | Our coverage area |
| 10 | `faq` | `accordion` | content | Frequently asked questions |
| 11 | `cta` | `banner` | content | Request {primary} in {city} |

## Blog / article  (`template=blog`)

Default for page type: `blog`. Stacked hero (title + featured image); body absorbs the H2 blocks; sticky ToC.

| # | kind | layout | role | heading |
|---|------|--------|------|---------|
| 1 | `hero` | `stacked` | content | {primary} |
| 2 | `intro` | `stacked` | content | Introduction |
| 3 | `related` | `toc` | chrome | In this article |
| 4 | `body` | `stacked` | content (absorbs overflow) | - |
| 5 | `proof` | `stacked` | content | The evidence |
| 6 | `faq` | `accordion` | content | Frequently asked questions |
| 7 | `conclusion` | `stacked` | content | Conclusion |
| 8 | `cta` | `banner` | content | Next steps |

## FAQ page  (`template=faq`)

Default for page type: `blog`. Accordion for 10+ questions (plain list under ~10); simplest questions first.

| # | kind | layout | role | heading |
|---|------|--------|------|---------|
| 1 | `hero` | `centered` | content | Frequently asked questions |
| 2 | `search` | `stacked` | chrome | Search the FAQ |
| 3 | `related` | `list` | chrome | Browse by topic |
| 4 | `faq` | `accordion` | content (absorbs overflow) | Questions & answers |
| 5 | `cta` | `banner` | content | Still have questions? |

## Local business landing  (`template=local`)

Default for page type: `local`. H1 = service + location + differentiator; primary CTA is tap-to-call.

| # | kind | layout | role | heading |
|---|------|--------|------|---------|
| 1 | `hero` | `split` | content | {primary} in {city} |
| 2 | `trust_bar` | `carousel` | chrome | Rated by locals |
| 3 | `services` | `grid` | content | Our services |
| 4 | `about` | `stacked` | content | About {client} |
| 5 | `reviews` | `carousel` | chrome | Customer reviews |
| 6 | `service_areas` | `list` | content | Areas we serve |
| 7 | `map` | `map-embed` | chrome | Where we are |
| 8 | `cta` | `banner` | content | Call {client} today |

## Homepage  (`template=homepage`)

Default for page type: `service`. One primary CTA repeated top + bottom; logo trust strip under the hero.

| # | kind | layout | role | heading |
|---|------|--------|------|---------|
| 1 | `hero` | `split` | content | {client} |
| 2 | `trust_bar` | `carousel` | chrome | Trusted by |
| 3 | `benefits` | `grid` | content | What you get |
| 4 | `features` | `grid` | content | How it works |
| 5 | `proof` | `stacked` | content | Proven results |
| 6 | `testimonials` | `carousel` | content | What clients say |
| 7 | `about` | `stacked` | content | About {client} |
| 8 | `stats` | `tiles` | chrome | By the numbers |
| 9 | `cta` | `banner` | content | Get started |
