# Google Business Profile Posts - Deep Playbook

**Artifact:** the short "post" a business publishes on its Google Business Profile (the What's New / Offer / Event / Update entries that show on the GBP panel in Search and Maps). Not a web page. A short piece of promotional copy plus a CTA button.

**Command:** `/write-gbp-posts`. Load order per `CLAUDE.md`: doctrine -> `foundations/review-content-strategy.md` (section 7 places this asset) -> this playbook -> voice -> client `brand.yaml`.

---

## THE HONESTY LABEL (read first, applies to every use of this asset)

**GBP posts move rankings by zero. This is a CTR / engagement / conversion asset ONLY. It must never be positioned, sold, or reported to a client as a ranking lever.**

The evidence is a controlled study, not an opinion. Sterling Sky ran a 9-week controlled test across 441 keywords and 3 listings and found **zero ranking movement from GBP posts** - one listing actually declined during the test (https://www.sterlingsky.ca/do-google-posts-impact-ranking/, fetched 2026-07-20 PKT). Posts keep the profile active and can drive clicks, calls, and offer redemptions, but they are not a ranking factor.

**Doctrine binding (Law 8):** optimize the reward function, not a proxy. Selling GBP posts as a ranking play would be optimizing a proxy that the strongest available evidence says does not move the target. That is a Law 8 violation. So this command, this playbook, and any report to a client:

- Label GBP posts strictly as a **CTR / engagement / conversion** asset.
- **Refuse to claim a ranking benefit.** If a client, a brief, or a file asks for GBP posts "to rank higher" or "to improve local SEO rankings," the correct response is to correct the premise, cite the Sterling Sky study, and reframe the asset as engagement-only. Do not soften this into "posts might help rankings indirectly." The controlled test says no.
- Behavioral / engagement signals (clicks, calls, direction requests) are a separate, small, rising ranking category in the Whitespark survey - but that is about the *actions users take*, not about the post being a ranking input. Do not launder "engagement signals are rising" into "posts rank you." The post's honest value is that it can *prompt* a click or call, which is a conversion win in its own right.

If you cannot say something true and useful about a GBP post without implying it ranks the business, say less. The engagement value is real and worth writing well. That is the whole pitch.

---

## 1. What GBP posts are genuinely good for

Framed honestly, posts earn their place as a light, recurring engagement asset:

- **Occupying real estate on the profile** with a timely, clickable message (a seasonal offer, a new service, an event, a genuine update) at the moment a high-intent searcher is already looking at the business.
- **Driving a specific action** via the post CTA button (Book, Call, Order, Learn more, Buy) - the conversion the post exists for.
- **Signaling an active, tended business** to the human reading the profile (a profile with recent posts and photos reads more alive than a dormant one). This is a trust-to-the-reader effect, not a ranking effect.
- **Promoting truthful, time-bound offers** the business genuinely runs.

That is the honest value ceiling. Write to it.

---

## 2. Post types and the copy pattern for each

GBP supports a few post types; each has a job and a length reality (posts are short - front-load the message, roughly 150-300 characters of body land before truncation, with a required CTA button on most types).

| Post type | Job | CTA | Copy note |
|---|---|---|---|
| **Update / What's New** | A timely, genuine update or tip | Learn more / Call | Lead with the value; one clear idea |
| **Offer** | A real, time-bound promotion | Redeem / Call | Must be a real offer with real terms and real dates; no fabricated scarcity (Law 20) |
| **Event** | A real event with start/end dates | Learn more / Book | Real date, real place; nothing invented |
| **Product** | Highlight a real service/product | Buy / Learn more | Real price only if genuinely fixed |

**The copy pattern (all types):**
1. **Lead with the value or the news** in the first line (it is what shows before truncation). Not "At [Business] we pride ourselves on..." - the actual thing.
2. **One concrete detail** that makes it real and specific (the real offer terms, the real event date, the real new service).
3. **One clear CTA** matched to the button. First-person or direct: "Book your spot," "Call to claim."
4. **Owner voice**, brief, no filler.

---

## 3. Hard rules

- **Never claim or imply a ranking benefit** (the honesty label above). Engagement/CTR/conversion only.
- **No fabricated urgency or scarcity** (Law 20): no "only 2 spots left" that is not true, no countdown that resets, no fake deadline. A real seasonal deadline or a real booked-out calendar is fine and effective; an invented one is an FTC dark-pattern and a trust risk.
- **Offers must be real and honorable** with real terms and dates; the business must be able to fulfill them.
- **No spammy repetition or keyword stuffing.** A post stuffed with "[service] [city]" reads as spam to the human and gains nothing (no ranking value to chase). Write for the reader.
- **NAP / entity consistency:** any phone, name, or offer detail matches the GBP and the site.
- **No em dash** (U+2014); the hook blocks it.
- **Truthful claims only** (compliance spine): no unsubstantiated superlatives, no fake reviews quoted, no misleading offer math.

---

## 4. Cadence and reporting (set expectations honestly)

- **Cadence:** a light, sustainable rhythm (for example weekly or a few times a month) tied to real things the business has to say - a real offer, a real event, a genuine seasonal tip. Do not manufacture posts to hit a number; an empty post is worse than a gap.
- **What to measure:** post views, CTA clicks, calls, offer redemptions - the *engagement* metrics. **Do not report post activity against ranking changes** or imply causation. If rankings moved, attribute them to the levers that actually move rank (reviews, on-page relevance, links, entity consistency), never to the posts.
- **The client conversation:** "Posts keep your profile active and can drive clicks and calls on the offers you actually run. They do not move your ranking - a controlled study confirmed that - so we treat them as a conversion asset, not an SEO one." That honesty is a differentiator, not a weakness.

---

## 5. Output contract

`/write-gbp-posts` emits to `output/<client>/gbp-posts/<date>/`:

- `posts.md` - each post (type, body, CTA button, any real offer terms/dates), ready to paste into the GBP.
- `label.md` - a one-paragraph honesty note restating that these are engagement/CTR assets with zero ranking value (Sterling Sky), for the operator's records and any client-facing report.

A set is not done until `label.md` carries the engagement-only labeling and every offer/event in `posts.md` is real and honorable.

---

## 6. Finished-set checklist

- [ ] Every post labeled and understood as engagement/CTR/conversion only; no ranking claim anywhere; Sterling Sky cited.
- [ ] Any offer/event is real, time-bound, honorable, with real terms and dates; no fabricated urgency or scarcity (Law 20).
- [ ] Value/news leads the first line; one clear CTA matched to the button; owner voice.
- [ ] No keyword stuffing; NAP/entity consistent with GBP and site.
- [ ] No em dash; claims truthful and substantiated.
- [ ] Output contract emitted: `posts.md`, `label.md` (engagement-only label present).
</content>
</invoke>
