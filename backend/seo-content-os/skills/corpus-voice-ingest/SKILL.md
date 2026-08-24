---
name: corpus-voice-ingest
description: Derive a client's brand voice from their OWN existing copy (current site pages, email replies, call transcripts, GBP posts that the operator pastes in) and write it into clients/<slug>/brand.yaml voice block plus an optional voice.md. Use during /new-client, or to upgrade a hand-written voice profile, whenever the client has real writing to learn from. Measures sentence rhythm, characteristic phrases, reading level, tone-by-context, banned/loved words, and good-vs-off-brand exemplars. Refuses to learn generic marketing filler: if the existing site is AI slop, it stops and asks for real writing instead. Closes the one gap where Jasper's corpus-trained voice beats a template.
allowed-tools: Read, Write, Edit, Bash, Grep, Glob
---

# corpus-voice-ingest

Learn a client's real voice from their real writing, and write it into their voice profile. This is the corpus-trained voice layer: the one place a template loses to Jasper, closed by ingesting the client's own copy instead of hand-writing adjectives.

Read `CLAUDE.md`, `knowledge/voice/humanization-layer.md`, and `knowledge/voice/brand-voice-template.md` first if they are not already in context. This skill fills Layer 2 (per-client voice); the universal Layer 1 is untouched.

## The one rule that governs this skill

**Learn the operator, not the slop.** A client's current website is very often generic marketing filler that an agency or an AI wrote: "your trusted partner for seamless solutions." That is exactly what the whole system exists to beat (doctrine Law 8, the vocabulary blocklist). If you derive a voice from a generic site, you copy the slop into `brand.yaml` and poison every future page. So the first job is always to separate the real idiolect from the filler, and if the corpus is mostly filler, to stop and get real writing.

Where the operator's own words exist, they win. Rank the corpus by how much of the operator is actually in it:

1. **Real speech and personal writing** (best): discovery-call transcripts, the owner's email replies, texts, voice-note transcripts, how they answered the SME interview. This is the unfiltered idiolect. Weight it highest.
2. **Owner-written posts**: GBP posts, personal LinkedIn, reviews they responded to. Usually still in their voice.
3. **Current site copy** (treat with suspicion): may be theirs, may be an agency's, may be AI. Fingerprint it before trusting it. High filler ratio means do not learn from it.

If you only have category 3 and it scores as filler, you have no real corpus. Say so and fall back to the `/new-client` SME voice interview. Do not invent a voice.

## Inputs

The operator pastes or points to a corpus. Accept any of:
- Text pasted directly into the conversation.
- One or more files (`.txt`, `.md`, HTML saved from their site) under `clients/<slug>/_corpus/` or a path the operator gives.
- A live URL the operator asks you to fetch (only if `WebFetch`/`WebSearch` are permitted for the run; this skill does not require network).

Ask the operator to label each source by category (speech / owner-written / site copy). The label sets how much you trust it. If they cannot label it, fingerprint each file separately and let the filler ratio tell you.

## Procedure

### 1. Assemble and segment the corpus

Collect the sources. Keep the high-trust sources (speech, email) separate from site copy so you can compare them. If the operator pasted text inline, write it to `clients/<slug>/_corpus/<label>.txt` so the fingerprint script can read it and so the corpus is auditable later. Strip obvious boilerplate (nav menus, cookie banners, footer legal) by hand or by only keeping body copy.

### 2. Fingerprint each source (the measurement pass)

Run the offline helper on each source, and on the combined high-trust set:

```
python scripts/voice_fingerprint.py clients/<slug>/_corpus/site.txt
python scripts/voice_fingerprint.py clients/<slug>/_corpus/emails.txt
python scripts/voice_fingerprint.py --json clients/<slug>/_corpus/emails.txt   # machine-readable
```

It reports, per source, the measurable style stats that seed the voice params:
- **Sentence rhythm**: average length, variance, stdev, min/max, and the short/medium/long mix. High variance is a real human voice; flat variance is the machine metronome.
- **Syllables per word**: the lexical-complexity proxy that seeds `reading_level`.
- **Contraction rate** (per 100 words): high means conversational ("we'll", "don't"); near-zero means formal or corporate.
- **Question rate and imperative rate**: how much the copy asks and commands. Direct imperatives are the CTA signature of converting local copy.
- **Distinctive n-grams (1 to 3 words)**: phrases frequent in this corpus that are NOT generic filler. These are the raw candidate characteristic phrases.
- **Filler ratio**: the share of the corpus that is generic marketing/AI slop. This is the guardrail number.

### 3. The filler gate (do not learn slop)

Read the filler ratio for each source.

- If a source's filler ratio is **above ~15%** (the script warns and exits 1), that source is generic. Do not learn voice from it. If your only corpus is such sources, stop: tell the operator their current copy reads as generic marketing filler (name two or three of the actual filler phrases the script surfaced as evidence), and ask for real writing instead: a few email replies, or answers to the SME voice questions. This refusal is the point of the skill, not a failure of it.
- If a source is **below the cap**, it is voice-bearing enough to learn from. Proceed, but still apply judgement: the script measures, it does not understand. A low filler ratio does not make a phrase worth keeping.

Never override the gate by lowering `--max-filler-ratio` to force a pass. The threshold protects the whole client. If the operator insists their filler-heavy site "is their voice," explain that copying it forfeits the system's entire advantage (Law 8) and re-offer the SME interview.

### 4. Derive the voice parameters (the judgement pass)

Turn the numbers plus a close read of the high-trust corpus into the `voice:` block fields. The script seeds; you decide.

- **`reading_level`**: map syllables-per-word and average sentence length to a grade band. Roughly: ~1.4 syll/word and short sentences sit around Grade 6 to 7; denser copy runs higher. Cross-check with `scripts/readability_scorer.py` on the corpus. Name a band, e.g. "Grade 6 to 8", tied to the real customer (a homeowner mid-problem on a phone reads lower than a law-firm client).
- **`one_line_direction`**: write the single actionable sentence with a contrast built in, grounded in what you measured. If the corpus is short-sentence, high-contraction, high-imperative, that is literally "sounds like the owner on the phone: plain, direct, tells you the next step." Do not write "professional and friendly"; that directs nothing (see brand-voice-template.md).
- **`tone_by_context`**: infer per-situation tone from the corpus where it exists (find the emergency/pricing/about passages and read their register), and fill the rest from the page types this client will use. Every page type the client runs needs a named tone.
- **`banned_phrases`** (business-specific, on top of the universal blocklist): two sources feed this. First, any filler phrase the fingerprint flagged that appears on their current site is a candidate to explicitly ban going forward. Second, positioning bans the operator confirms (a premium remodeler bans "cheap"; a law firm bans "guarantee"). Confirm these with the operator; do not guess a compliance ban.
- **`good_examples`** (the loved words / real on-voice sentences): pull 2 to 3 real sentences verbatim from the high-trust corpus, ideally ones that also contain a distinctive n-gram the script surfaced. Real beats invented, always: they carry the idiolect no schema captures. If the operator said something sharp on the call, use that.
- **`off_brand_examples`**: pull 2 to 3 real off-brand sentences, ideally from their own generic site copy, rewritten from the same content as a good example where possible. Pairing an on-voice sentence with its off-voice twin on the same content is the strongest signal to the writer. If the current site is the filler source, it is a gift here: those are your off-brand examples.

Characteristic phrases (the distinctive n-grams) do not get their own YAML field. Fold the strongest two or three into `one_line_direction` or `good_examples`, or list them in the optional `voice.md` (below) as "phrases the owner actually uses." Discard n-grams that are just this client's proper nouns or one-off topic words rather than voice signature; the script cannot tell the difference, you can.

### 5. Write the voice block

Write the derived fields into the `voice:` block of `clients/<slug>/brand.yaml`, matching the schema in `brand-voice-template.md` exactly. If the file does not exist yet (pure `/new-client` path), scaffold it from `clients/_template/brand.yaml` first. Edit only the `voice:` block; leave NAP, schema, services, and E-E-A-T to the rest of `/new-client`.

Every value must trace to the corpus or to an operator confirmation. If a field cannot be grounded (for example, a `tone_by_context` for a page type the client has no existing copy for), fill it from the page-type default and mark it for operator confirmation rather than inventing an idiolect for it.

### 6. Optional voice.md

When the corpus is rich enough to say more than the terse YAML block holds, write `clients/<slug>/voice.md` as the long-form companion the writer can read alongside the block. Keep it dense (it loads into context): the measured fingerprint numbers as a reference, the full list of characteristic phrases with a real example of each in use, the three or four strongest good/off-brand pairs with a one-line note on why each lands or fails, and any per-context nuance too long for the YAML map. Do not duplicate the whole blocklist; point to it.

### 7. Confirm with the operator

Show the derived block and the evidence: "Here is the voice I read from your writing, and the sentences I pulled it from." The operator confirms or corrects. Voice is a claim about how they sound; they get the final say. On confirmation, the block is live and the writing pipeline will load it on every page.

## Hard rules

- **Never learn from a filler-dominated corpus.** The gate at step 3 is not advisory. Slop in equals slop out on every future page.
- **No detector-evasion, ever.** This skill measures style to match a real voice. It never scores or optimizes "AI detection" (Law 8, Hard Line 5). The fingerprint script has no such feature; do not add one.
- **Real sentences over invented ones.** `good_examples` and `off_brand_examples` come from the corpus verbatim wherever possible. An invented example is a last resort, flagged as such to the operator.
- **Ground every field.** Every voice param traces to a measured stat, a corpus quote, or an operator confirmation. Blank-and-flag beats guessed.
- **No em dash (U+2014).** Enforced by the Write/Edit hook. Use hyphens or rephrase.
- **The script seeds, you decide.** `voice_fingerprint.py` produces numbers and candidate phrases. It does not understand voice. Every derived field is your judgement over its output, not a copy of it.

## What this produces

A `clients/<slug>/brand.yaml` voice block (and optional `voice.md`) derived from the client's real writing rather than a hand-filled template: measured rhythm and reading level, real characteristic phrases, per-context tone, business-specific bans, and real good/off-brand exemplars. Corpus-trained voice, with a guardrail that refuses to train on generic slop.
