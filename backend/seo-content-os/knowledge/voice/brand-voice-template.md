# Brand Voice Template

The schema for a client's brand voice: Layer 2 of the voice stack (`humanization-layer.md`). This is what `/new-client` fills, and it plugs directly into the `voice:` block of `clients/<client>/brand.yaml`. The universal humanization layer (this directory) makes copy not sound like AI; this profile makes it sound like one specific business.

A voice profile is not a mood board. It is a set of constraints a writer and a reviewer can both check a draft against. Adjectives alone ("friendly, professional, trustworthy") are useless: they produce different copy from two writers and cannot be graded. This schema forces the two things that make a voice checkable: **contrast pairs** (what the voice is, versus the nearby thing it is not) and **real examples** (sentences that sound right, sentences that sound wrong).

Keep it short. It gets loaded into the writer's context on every page, so it has to be dense, not a 10-page brand book. The `voice:` block in `brand.yaml` is the source of truth; this file explains how to fill each field well.

---

## The schema (mirrors `brand.yaml` voice block)

```yaml
voice:
  one_line_direction: ""        # the single sentence that captures how this business sounds
  reading_level: ""             # the grade band the copy targets
  tone_by_context: {}           # how the voice shifts by page situation
  banned_phrases: []            # words this brand never uses (append to the universal blocklist)
  good_examples: []             # 2-3 real sentences that sound right
  off_brand_examples: []        # 2-3 sentences that sound wrong for this brand
```

---

## Field-by-field

### `one_line_direction`

One sentence. The voice in a nutshell, written as a direction a writer can act on, ideally with a contrast built in.

- Good: "Sounds like the owner answering the phone at 7am: plain, direct, a little blunt, never salesy."
- Good: "Warm and reassuring, like a family dentist talking to a nervous patient, never clinical or corporate."
- Weak (no contrast, unactionable): "Professional and friendly." (Every business claims this. It directs nothing.)

The test: could a writer produce two clearly different sentences, one on-voice and one off, from this line alone? If not, sharpen it.

### `reading_level`

The grade band, tied to the real customer. Most local home-services copy lives at Grade 6 to 8: a homeowner reading on a phone, mid-problem. A law firm or a medical specialty may run higher. Name the band, e.g. "Grade 7 to 8." This governs sentence length and vocabulary, and it is checkable (the readability gate).

### `tone_by_context`

A map from page situation to a tone target. This is the single most useful field, because a business does not have one flat tone; it shifts with what the reader is doing. Fill the contexts the client's pages will actually hit:

```yaml
tone_by_context:
  emergency: "calm and fast, take-charge, zero fluff"
  pricing: "transparent and plain, no dodging, name the number"
  about: "warm and proud, first-hand, specific about the people"
  service_detail: "clear and practical, teach a little, no jargon"
  cta: "direct and low-pressure, one clear next step"
```

Every page type the client uses should map to a named tone. The writer reads the tone for the page in front of them; the voice-fidelity gate checks the draft against it.

### `banned_phrases`

Words and phrases THIS brand never uses, on top of the universal blocklist. These are business-specific, and they matter:

- A dentist bans "painless" (a claim they cannot substantiate).
- A law firm bans "guarantee" and "best" (bar-compliance lines).
- A premium remodeler bans "cheap" and "budget" (wrong positioning).
- A no-nonsense trades business bans "delight," "journey," "partner" (wrong register).

These append to Tier 1 of the vocabulary blocklist at write time.

### `good_examples`

2 to 3 real sentences that sound exactly right for this brand. Pull them from the client's own writing where possible: their actual GBP posts, their email replies, how the owner talks on a discovery call. Real examples beat invented ones, because they carry the idiolect no schema captures.

- "We'll be straight with you: this water heater has another year in it, tops. Your call whether to replace now or nurse it."
- "Storm season's coming. Get on the schedule now, because in May we're booked three weeks out."

### `off_brand_examples`

2 to 3 sentences that sound wrong for this brand, ideally the same content written in the wrong voice. The contrast is what makes the profile checkable.

- "At [Brand], we pride ourselves on delivering seamless, worry-free solutions tailored to your unique needs." (corporate AI mush; off-brand for a plain-talking trades business)
- "Embark on your home comfort journey with our comprehensive HVAC solutions." (banned words, wrong register)

Pairing a good example with its off-brand twin on the same content is the strongest possible signal to a writer.

---

## A filled example (a plain-talking plumber)

```yaml
voice:
  one_line_direction: "Sounds like the owner on the phone at 7am: plain, blunt, honest to a fault, never salesy or corporate."
  reading_level: "Grade 6 to 7"
  tone_by_context:
    emergency: "calm, take-charge, fast, zero fluff"
    pricing: "transparent, names the number, no dodging"
    about: "warm and proud, first-person, specific about the two brothers who run it"
    cta: "direct, low-pressure, one clear next step"
  banned_phrases:
    - "solutions"
    - "peace of mind"
    - "your trusted partner"
    - "state-of-the-art"
    - "we pride ourselves"
  good_examples:
    - "We'll be straight with you: that heater's got a year left, tops. Your call."
    - "Call at 2am and Danny picks up. He's the one on the truck, too."
    - "No trip charge inside Round Rock. The estimate is the price."
  off_brand_examples:
    - "At Round Rock Plumbing, we pride ourselves on delivering seamless, worry-free plumbing solutions."
    - "Let us be your trusted partner on your home comfort journey."
    - "Our team of dedicated professionals utilizes state-of-the-art equipment."
```

---

## How this plugs in

- `/new-client` interviews the operator and fills this block in `clients/<client>/brand.yaml`. No page is written until it exists.
- The writer loads it on every page alongside the universal layer, reads the `tone_by_context` entry for the page type, and drafts to it.
- The voice-fidelity gate (`knowledge/quality-gates/gates.md`) checks the draft against `one_line_direction`, the relevant `tone_by_context`, `banned_phrases`, and the gap between `good_examples` and `off_brand_examples`. The `/qa` command and `compliance-auditor` agent run that gate.
- After each engagement, real winning sentences from the shipped pages can be promoted into `good_examples`, so the profile sharpens over time (the Law 10 compounding rule).
