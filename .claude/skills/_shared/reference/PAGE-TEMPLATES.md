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

Default for page type: `service`. Split hero; deliverables as a grid; numbered process; proof + price last.

| # | kind | layout | role | heading |
|---|------|--------|------|---------|
| 1 | `hero` | `split` | content | {primary} |
| 2 | `features` | `grid` | content | What's included |
| 3 | `process` | `numbered-steps` | content | How it works |
| 4 | `faq` | `accordion` | content | Frequently asked questions |
| 5 | `testimonials` | `carousel` | content | What clients say |
| 6 | `pricing` | `cards` | content | Pricing |
| 7 | `cta` | `banner` | content | Get started with {primary} |

## Location page  (`template=location`)

Default for page type: `local`. Hero + local intro + services; NAP and reviews render only from real data.

| # | kind | layout | role | heading |
|---|------|--------|------|---------|
| 1 | `hero` | `split` | content | {primary} in {city} |
| 2 | `intro` | `stacked` | content | About our {city} location |
| 3 | `services` | `grid` | content | Services at this location |
| 4 | `faq` | `accordion` | content | Frequently asked questions |
| 5 | `contact` | `nap` | chrome | Visit us |
| 6 | `reviews` | `carousel` | chrome | Local reviews |
| 7 | `cta` | `banner` | content | Book at our {city} location |

## Service-area page  (`template=service_area`)

Default for page type: `local`. Service + area content first; the covered-areas list is the page's spine.

| # | kind | layout | role | heading |
|---|------|--------|------|---------|
| 1 | `hero` | `split` | content | {primary} in {city} |
| 2 | `intro` | `stacked` | content | Serving {city} and the surrounding area |
| 3 | `services` | `grid` | content | What we offer in {city} |
| 4 | `process` | `numbered-steps` | content | How it works |
| 5 | `service_areas` | `list` | content | Areas we cover |
| 6 | `reviews` | `carousel` | chrome | What local customers say |
| 7 | `cta` | `banner` | content | Request {primary} in {city} |

## Blog / article  (`template=blog`)

Default for page type: `blog`. Stacked hero; body absorbs the H2 blocks; evidence block only when cited.

| # | kind | layout | role | heading |
|---|------|--------|------|---------|
| 1 | `hero` | `stacked` | content | {primary} |
| 2 | `intro` | `stacked` | content | Introduction |
| 3 | `body` | `stacked` | content (absorbs overflow) | - |
| 4 | `faq` | `accordion` | content | Frequently asked questions |
| 5 | `conclusion` | `stacked` | content | Conclusion |
| 6 | `proof` | `stacked` | content | The evidence |
| 7 | `cta` | `banner` | content | Next steps |

## FAQ page  (`template=faq`)

Default for page type: `blog`. Accordion body; a services grid so the page sells as well as answers.

| # | kind | layout | role | heading |
|---|------|--------|------|---------|
| 1 | `hero` | `centered` | content | Frequently asked questions |
| 2 | `intro` | `stacked` | content | What this page answers |
| 3 | `faq` | `accordion` | content (absorbs overflow) | Questions & answers |
| 4 | `services` | `grid` | content | What we do |
| 5 | `proof` | `stacked` | content | Where these answers come from |
| 6 | `related` | `list` | chrome | Related reading |
| 7 | `cta` | `banner` | content | Still have questions? |

## Local business landing  (`template=local`)

Default for page type: `local`. H1 = service + location + differentiator; the CTA is tap-to-call.

| # | kind | layout | role | heading |
|---|------|--------|------|---------|
| 1 | `hero` | `split` | content | {primary} in {city} |
| 2 | `services` | `grid` | content | Our services |
| 3 | `about` | `stacked` | content | About {client} |
| 4 | `faq` | `accordion` | content | Frequently asked questions |
| 5 | `service_areas` | `list` | content | Areas we serve |
| 6 | `reviews` | `carousel` | chrome | Customer reviews |
| 7 | `cta` | `banner` | content | Call {client} today |

## Homepage  (`template=homepage`)

Default for page type: `service`. One primary CTA repeated top + bottom; proof only where proof exists.

| # | kind | layout | role | heading |
|---|------|--------|------|---------|
| 1 | `hero` | `split` | content | {client} |
| 2 | `benefits` | `grid` | content | What you get |
| 3 | `services` | `grid` | content | What we do |
| 4 | `process` | `numbered-steps` | content | How it works |
| 5 | `about` | `stacked` | content | About {client} |
| 6 | `testimonials` | `carousel` | content | What clients say |
| 7 | `cta` | `banner` | content | Get started |

## About page  (`template=about`)

Default for page type: `service`. Story first, values as a grid, people and numbers only when they are real.

| # | kind | layout | role | heading |
|---|------|--------|------|---------|
| 1 | `hero` | `split` | content | About {client} |
| 2 | `intro` | `stacked` | content | Why we exist |
| 3 | `benefits` | `grid` | content | What we stand for |
| 4 | `process` | `numbered-steps` | content | How we work |
| 5 | `team` | `cards` | content | The people behind {client} |
| 6 | `stats` | `tiles` | content | By the numbers |
| 7 | `cta` | `banner` | content | Work with {client} |
