# Sentence Rhythm

The single most reliable signal that copy was written by an LLM is rhythmic monotony. Default model output averages 16 to 18 words per sentence with very low variance and paragraphs that converge on 3 to 4 sentences. Human writing varies wildly. These rules force the variance back in.

This is not detector-evasion. Readers are not detectors. The reader who has seen thousands of AI outputs pattern-matches on flat rhythm before they consciously process a single word, and a flat local page reads as machine-written before they notice anything specific. The retrieval models reward varied passages too, because varied passages carry more information per token. Same discipline, two audiences.

The rhythm pass runs at the critical edit. Sections that fail the distribution get rewritten, not patched.

---

## Distribution targets

Every page section over ~120 words should hit all four buckets across its sentences:

| Bucket | Words per sentence | Minimum share |
|--------|-------------------|---------------|
| Short jab | 5 to 12 words | 20% |
| Mid | 12 to 20 words | 40 to 55% |
| Long sweep | 20 to 30 words | 15 to 25% |
| Very long (rare) | 31+ words | 0 to 5%, max one per ~250 words |

If the distribution is too narrow (most sentences in the 12-to-20 band, no short jabs), the section fails the rhythm check and gets rewritten.

Local-copy example. Flat and AI-default:

> We provide comprehensive plumbing services to homeowners throughout the Round Rock area. Our team of experienced professionals is dedicated to delivering reliable solutions for all your needs. We understand that plumbing issues can be stressful and inconvenient for your family.

Varied and human:

> We have run plumbing calls in Round Rock since 2009. Slab leaks are the ones that scare people, and Old Town's 1980s foundations get more than their share. Call at 2am with water coming up through the tile and someone answers. We are on the truck within 90 minutes, and the after-hours callout is a flat $95, not a mystery.

---

## Adjacent-sentence variance rule

No two consecutive sentences within 3 words of each other. If sentence N is 14 words, sentence N+1 cannot be 11 to 17 words. This forces a jab-cross pattern: short, then long, then medium, then short. AI writing that violates this reads as a metronome ticking.

---

## Paragraph length variance

| Paragraph type | Sentence count |
|----------------|----------------|
| Single-sentence punch | 1 |
| Standard | 2 to 4 |
| Long (only when load-bearing) | 5 to 6 |

A full page should carry a few single-sentence paragraphs scattered through it. They land a claim. They reset rhythm. They make the page scannable on a phone, which is where most local search happens.

A passage block (per `knowledge/foundations/passage-block-protocol.md`) of ~120 to 220 words typically holds 3 to 4 paragraphs of varied length: a 1-sentence direct-answer lead, two 2-to-3-sentence paragraphs, occasionally a 4-to-5-sentence paragraph when a claim needs evidence, then implication.

---

## The first-sentence rule

The first sentence of the page body, and the first sentence under every H2, is 5 to 12 words. The reader decides whether to keep reading in those words. It does not open with "When it comes to," "At [Brand]," "Are you looking for," "In today's," or any other AI scaffolding.

**Bad (AI default):** "When it comes to keeping your family comfortable throughout the hot Austin summers, there are several important factors to consider when choosing an HVAC company you can trust."

**Good:**
- "Your AC will fail in July. It always does."
- "We service every AC brand sold in Austin since 2004."
- "A tune-up costs $89. A new compressor costs $2,400."
- "Round Rock has hard water. Your water heater pays for it."

The first sentence under each H2 is the direct-answer lead: it opens with the answer, not the setup. That is also what makes the passage extractable for AI Overviews.

---

## The last-sentence rule

The last sentence of a section is 6 to 15 words. It does not summarize. It either names the single most useful next action, lands one specific concrete claim the section earned, or states the price/fact that the reader came for. It never starts with "In conclusion," "To sum up," or "Rest assured."

---

## Punctuation rhythm

- **Em dash:** banned (hook enforced). Use a hyphen, comma, parentheses, or rewrite.
- **Semicolon:** allowed but rare, 2 to 3 per page at most. Joins two related clauses where a period would over-fragment.
- **Colon:** useful before a list or a payoff. Use freely.
- **Parentheses:** for a quick aside the reader benefits from (like a price, or a caveat) without breaking the main line.
- **Period:** the workhorse. Most sentences end with one.
- **Comma splice:** banned. Use a period, a semicolon, or rewrite.

---

## The question rule

A real question every ~200 words earns its place, especially on service and pricing pages where the reader has one. A real question is one the reader is actually asking, answered directly in the next 1 to 2 sentences. It doubles as a passage-block direct-answer lead.

- **Bad (rhetorical filler):** "So what does this mean for you?"
- **Good (real):** "Does a roof inspection cost anything? No. Ours is free and takes about 40 minutes, and you get photos of every problem area." 

---

## The header rule

H2s and H3s are part of the rhythm. Read the headers alone, top to bottom, and they should tell a coherent story, use varied lengths (3 to 12 words), avoid repeated structures (six "How to..." headers in a row), and avoid generic placeholders ("Our Services," "Why Choose Us," "Introduction," "Conclusion").

Headers can be statements, questions, imperatives, or comparisons. Mix at least three of those four families on any page with 5+ H2s. For local pages, question-worded headers double as PAA and voice-search matches: "How much does a water heater cost to replace in Austin?" is both a good header and a real query.

Read the headers aloud. If they sound like AI-generated headers ("Comprehensive Solutions for Every Need"), the page is at risk.

---

## The read-it-aloud test

Before finalize, read the first ~150 words and the last ~150 words aloud at conversational pace. Where you stumble, the sentence is too long or tangled. Where you lose interest, the rhythm is too flat. Fix by breaking a long sentence into a short one followed by a long one, or merging two short ones into a medium one to break a too-jabby run.

---

## Anti-pattern: the AI symphony

The most common AI cadence trap:

- Every paragraph opens with a transition word ("Furthermore," "Additionally," "Moreover").
- Three sentences of similar length per paragraph.
- Closes with a hedge ("This can be a great option for many homeowners").
- Repeats across 5 to 7 paragraphs.

The fix is not to vary the transition words. Delete them and let the paragraph break carry the shift. Then break the 3-sentence pattern: collapse two sentences into one in one paragraph, split one into three in another, open one paragraph with a 6-word punch.

---

## Anti-pattern: the anaphora cascade

Three or more consecutive sentences starting with the same word, especially "We," "Our," "At," "This."

Bug:

> We install tankless water heaters. We service every major brand. We offer financing on new units.

Rewrite:

> We install tankless water heaters and service every major brand. Financing is available on new units, 0% for the first 12 months. Most installs are done in a day.

---

## Self-test before finalize

1. Sentence-length distribution per section: does each hit the table at the top?
2. Adjacent variance: any two consecutive sentences within 3 words? Fix.
3. Single-sentence paragraphs: are there a few scattered through the page?
4. Read the headers alone: human, varied, story-telling?
5. Read the first and last ~150 words aloud: does it flow?
6. Anaphora scan: 3+ same-opening sentences in a row?

If any check fails, rewrite the failing section. Do not patch by adding a comma or a transition word. The patch always reads worse than the rewrite.
