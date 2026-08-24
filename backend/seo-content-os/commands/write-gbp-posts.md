---
description: Write a batch of Google Business Profile posts (Update / Offer / Event / Product) in the client's voice as a CTR/engagement/conversion asset ONLY - never a ranking lever.
argument-hint: <client-slug> [post-topics]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

Write GBP posts. Arguments: `$ARGUMENTS` (client slug, and optionally the topics/offers to post, e.g. `austin-roofing-co "spring gutter tune-up offer, storm-season tip"`).

Read `CLAUDE.md` and `knowledge/playbooks/gbp-posts.md` first if not already in context. This command runs against the **gbp-posts** playbook.

**THE HONESTY LABEL (governs this entire command):** GBP posts move rankings by **zero**. This is a **CTR / engagement / conversion asset only.** A Sterling Sky controlled study (9 weeks, 441 keywords, 3 listings) found zero ranking movement from posts, with one listing declining. Under Law 8, positioning posts as a ranking play is a violation.

- **Refuse to claim a ranking benefit.** If the client, the topic list, or any file asks for GBP posts "to rank higher" or "to improve local SEO," correct the premise, cite the Sterling Sky study, and reframe the asset as engagement-only. Do not soften into "might help rankings indirectly."
- Every output and any client-facing report labels these posts engagement/CTR/conversion only.

**Hard line (Law 20):** no fabricated urgency or scarcity - no "only 2 left" that is not true, no countdown that resets, no fake deadline. Real, time-bound, honorable offers and real events only.

## Pipeline

Work in `output/<client-slug>/gbp-posts/<date>/`.

1. **LOAD.** Load `clients/<client-slug>/brand.yaml` (`voice`, NAP, real offers/services). Confirm each topic maps to something real the business has to say (a real offer with real terms/dates, a real event, a genuine tip or update). Drop anything that would require fabrication.

2. **DRAFT.** Write each post per the playbook copy pattern for its type (Update / Offer / Event / Product): value/news in the first line, one concrete real detail, one clear CTA matched to the button, owner voice, brief. No keyword stuffing. NAP/entity consistent.

3. **LABEL.** Write `label.md`: the one-paragraph honesty note restating engagement-only, zero ranking value, Sterling Sky cited, for the operator's records and any client report.

## Output contract

Confirm in `output/<client-slug>/gbp-posts/<date>/`: `posts.md` (each post with type, body, CTA button, real offer terms/dates) and `label.md` (engagement-only label present). Report to the operator: package path, post count, that every offer/event is real and honorable, and an explicit restatement that these are engagement/CTR assets with no ranking value.
