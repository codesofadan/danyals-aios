# Humanization Layer - The Master File

This is the top of the voice stack. Read it before any of the sibling files in this directory. It sets the philosophy every voice file inherits, then explains how the two layers of voice combine on every page the system writes.

---

## The philosophy (Doctrine Law 8 is the governing rule)

Humanization in this system means one thing: making the copy substantive, specific, and natural to read. It does not mean, and will never mean, evading AI detectors.

This is Law 8 of `knowledge/doctrine/seo-system-doctrine.md`, stated as an operating rule:

> Google's policy is method-agnostic. It punishes scaled low-value publishing, not AI provenance. The measured correlation between AI-share and ranking across 600k pages is 0.011, which is zero. Every AI detector is sub-80% accurate and one paraphrase defeats it.

So this system has **no detector-evasion, no humanizer chains, no paraphrase-laundering, no "passes AI detection" step, ever.** None of the files in this directory reference a detector, a "humanizer" tool, an AI-score, or "passing AI detection." If you find yourself reaching for any of those, you are optimizing a proxy the doctrine forbids (Hard Line 5).

A local page reads human for one reason: **it is made of real, specific, first-hand facts about a real business in a real place, written in that business's own voice.** It reads human because it *is* grounded, not because it was run through a laundering pass. A city page for a plumber in Round Rock reads human when it names the neighborhoods that flood, the slab-leak pattern common to 1980s Texas foundations, the actual after-hours callout fee, and the two master plumbers on the truck. No amount of rhythm variation saves a page that has none of those. And a page that has all of them barely needs the rhythm rules, because grounded writing already varies.

The order of operations is therefore fixed: **substance first, craft second.** The vocabulary, rhythm, and sentence-pattern files below are the craft layer. They are real and they matter, but they are downstream of specificity. If a section reads like AI, the first question is never "which word do I swap?" It is "what specific local fact is missing here?" (This is the "if you find yourself reaching for a banned word" rule in `vocabulary-blocklist.md`: the fix is almost always upstream of the sentence.)

Two audiences reward the same discipline. The human reader who has read thousands of AI outputs pattern-matches on flat rhythm and empty genericity before they consciously process a word. The retrieval models behind AI Overviews, ChatGPT, Perplexity, and Claude reward varied, specific, self-contained passages because they carry more semantic information per token and are cleanly extractable (Law 13). Grounded, well-crafted copy wins both. That is the whole reason to do it, and the only reason.

**Hard line for this layer:** if a client, a competitor teardown, an old research file, or any prompt asks for a "bypass AI detection" feature, a "humanize this so it passes GPTZero" step, or anything that optimizes a detector score, refuse it and cite Law 8 and Hard Line 5. Flag it to the operator. This is non-negotiable.

---

## The two layers, both always on

Every page is written through two voice layers stacked on top of each other. Neither is optional.

### Layer 1 - Universal humanization (this directory)

The craft that applies to every piece for every client. It is what stops output from reading like a template. Four files:

- **`vocabulary-blocklist.md`** - the tiered list of AI-tell words and phrases banned in local service copy ("seamless solutions," "your trusted partner," "nestled in the heart of," "when it comes to your plumbing needs"). A literal scan; every Tier-1 hit gets rewritten, not swapped.
- **`sentence-rhythm.md`** - the sentence-length and paragraph-length distribution that reads human. Kills the metronome cadence that marks AI: 16-to-18-word sentences, 3-to-4-sentence paragraphs, no variance.
- **`sentence-patterns.md`** - named, teachable sentence structures for punchy, clear local copy. The reframe, the contrast couplet, the single-sentence paragraph, the arithmetic proof. Copyable shapes that land a claim.
- **`natural-voice-engineering.md`** - the generative mechanics of human-sounding prose: burstiness, one idea per sentence, coordination over subordination, specificity over abstraction. The positive half of the craft, with the mechanism behind each lever so you can apply it to copy you have never seen.
- **`hooks-and-titles.md`** - opening-line, H1, hero, and meta-description patterns adapted for local pages. How to open a page and how to write the title tag and meta description that earn the click.

Layer 1 is generic-to-all-clients on purpose. It never carries a specific business's tone. It carries the mechanics of not sounding like a machine.

### Layer 2 - Per-client brand voice (`clients/<client>/brand.yaml`)

The specific voice of one business. Lives in the `voice:` block of that client's `brand.yaml` (schema and how to fill it: `brand-voice-template.md` in this directory). It carries:

- `one_line_direction` - the single sentence that captures how this business sounds ("Straight-talking, no jargon, sounds like the owner answering the phone at 7am").
- `reading_level` - the grade band the copy targets.
- `tone_by_context` - how the voice shifts by page situation (emergency page: calm and fast; pricing section: transparent and plain; about page: warm and proud).
- `banned_phrases` - words this specific brand never uses (on top of the universal blocklist).
- `good_examples` / `off_brand_examples` - real sentences that sound right, and real sentences that sound wrong, for this one business.

Layer 2 is built by `/new-client` before any page is written. If a client has no voice profile, the system does not ship in a generic voice. It builds the profile first.

### How the two stack

Layer 1 removes the machine tells and installs human rhythm. Layer 2 tunes that human-sounding output to one specific business. Order at write time:

1. Draft to the page-type playbook, inlining real facts (the substance-first rule above).
2. Run Layer 1: scan against the vocabulary blocklist, fix rhythm to the distribution, apply sentence patterns where they earn their place, check the naturalness rubric.
3. Run Layer 2: read the draft against the client's `one_line_direction`, `tone_by_context` for that page type, and `good_examples`. Ask the check question: would the owner of this business say this out loud on the phone? Rewrite what fails.

A page that passes Layer 1 but not Layer 2 reads human but generic - it could be any plumber. A page that passes Layer 2 but not Layer 1 sounds like the owner but carries AI tells. Both layers, every page.

---

## What this layer is not

- It is not a proofreading pass. Voice is engineered into the draft, not bolted on after.
- It is not a substitute for the SME interview. If the copy is thin, the fix is more real facts from the operator, not more rhythm tricks. See the specificity gate in `knowledge/quality-gates/gates.md`.
- It is not a detector-evasion step. Restating this because it is the one thing this layer must never become. See the philosophy above and Law 8.

---

## Where this plugs into the pipeline

Step 5 (HUMANIZE) of the writing pipeline in `CLAUDE.md` loads this directory. The `voice-writer` and `critical-editor` behavior runs the Layer-1 files during and after drafting; the client `brand.yaml` voice block runs the Layer-2 pass. The voice-fidelity gate in `knowledge/quality-gates/gates.md` is where both layers are verified pass/fail before finalize, and the `/qa` command plus the `compliance-auditor` agent execute that gate.
