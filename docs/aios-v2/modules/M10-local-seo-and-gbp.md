# M10 · Local SEO & Google Business Profile

Requirements: `REQ-LOC-001` … `REQ-LOC-006`.

For a local business, GBP is the highest-leverage asset on the internet. It is also the
canonical source of the NAP that M04 spends the whole citation programme propagating.

---

## 1. Connection and read

`REQ-LOC-001`/`002`. Google OAuth per client **location** (not per client — a multi-location
business has multiple profiles). Reads categories, attributes, hours, services, photos,
description and the verified NAP.

**GBP is the canonical NAP source where it is connected.** M04 reads from the reconciled
canonical record, and any divergence between GBP, the client site and live citations
produces a NAP consistency score (`REQ-LOC-006`) and a task — never a silent pick.

## 2. Posts

`REQ-LOC-003`. GBP posts created, scheduled and published from the content pipeline, with
images. Types: update, offer, event. They obey the same rules as everything else:

- Content from the M03 pipeline, in the client's voice, grounded against the client profile.
- Staff approval before publishing (D-18: the end client never approves).
- Idempotent publish — a retry must not create a second post.
- A publish that cannot complete ends `blocked` with a cause.

GBP also appears as a platform card in M05's connection grid, because that is where an
operator expects to find it. It is the same underlying connection.

## 3. Reviews

`REQ-LOC-004`, P1. Monitor new reviews; draft replies with the model; **staff approve before
posting**. A reply is published under the client's business identity — the blast radius of a
bad automated reply is the client's public reputation, so there is no auto-post path.

Review velocity and average rating are reported with provenance.

## 4. Q&A

`REQ-LOC-005`, P1. Seed the questions a business should have answered, monitor for new
public questions, and raise a task on anything unanswered. Seeding uses the client's own
service data, never invented claims.

## 5. NAP consistency

`REQ-LOC-006`. A score computed across three sources: GBP, the client website, and every
live citation from M04. Each mismatch is itemised with the two values and where each was
found, so it is actionable rather than a number.

This score is one of the few figures a local SEO client understands immediately, so it
appears in the monthly report — which means it must be measured, dated, and never estimated.

## 6. Acceptance criteria

| # | Criterion |
|---|---|
| A1 | A multi-location client connects each location's profile independently |
| A2 | GBP data populates the canonical NAP and any divergence raises an itemised task |
| A3 | A GBP post publishes with an image and is idempotent under retry |
| A4 | A post that cannot publish ends `blocked` with a named cause |
| A5 | No review reply or Q&A answer is ever posted without recorded staff approval |
| A6 | The NAP consistency score itemises every mismatch with both values and their sources |
| A7 | The GBP connection is shared with M05's platform grid rather than duplicated |
