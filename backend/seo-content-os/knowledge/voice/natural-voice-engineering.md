# Natural Voice Engineering

The generative half of the humanization layer. `vocabulary-blocklist.md` says what never to write and ends on one check question: would the business owner say this out loud? That question catches a failure after it is on the page. It does not tell you how to write a line that passes it the first time. This file is the missing generative half: named, teachable techniques for producing natural, spoken-sounding prose on purpose, each with a mechanism (not just an assertion), a written-versus-natural example in local-service English, and a rule for how often to use it before it turns into a tic.

This is craft, not detector-evasion (Law 8). The point is prose a human reads as written by a person, not prose that fools a scanner. The two are different goals with different methods, and this system only ever pursues the first.

**Boundary.** This file engineers general human spoken-written rhythm: the mechanics of how a fluent person actually talks and writes, versus how flat edited prose is composed. The *specific* voice of one business - its owner's phrasing, its tone by page context - lives in that client's `brand.yaml` voice block (`brand-voice-template.md`). When a real client voice profile exists, it overrides any generic rule here on conflict. General craft gets a page to "human." The client profile gets it to "this business."

---

## Generative technique rulebook

Twelve named levers, synthesized from copywriting craft, broadcast-writing doctrine, and corpus/register linguistics. Every example pair is an illustrative construction for a local service business, written for this file. Each lever names its mechanism so you can apply it to copy you have never seen, not pattern-match a swipe file.

---

### 1. Burstiness (sentence-length variance)

**Mechanic:** deliberately alternate sentence length and clause complexity across a passage instead of settling into a uniform average. A short punch next to a long, qualified run.

**Why it produces a human effect:** likelihood-maximizing text generation pushes toward the statistically safest next token at every step, which flattens sentence length into an unnaturally smooth line, in contrast to the organic fluctuation of human text ([Holtzman et al. 2020](https://arxiv.org/abs/1904.09751)). Human thought is hierarchical: load-bearing points get a long qualifying sentence, asides get a fragment, punchlines get three words. AI output flattens all three to the mean.

**Written vs natural (local example):**
- Flat: "We offer fast service. We offer reliable service. We offer affordable service to all our valued customers."
- Bursty: "We show up fast. Same-day for most of Pflugerville, next-morning at the latest. And the price on the quote is the price you pay, no surprise line items."

**Where it applies:** every page body, especially service and location pages where a run of same-length sentences is the fastest way to read as machine-narrated.

**Frequency budget:** no run of three or more consecutive sentences with matching length and structure. If a read-aloud pass (lever 12) produces three flat beats in a row, break at least one. (This is the adjacent-variance rule in `sentence-rhythm.md`, stated as a generative target.)

---

### 2. One idea per sentence

**Mechanic:** restrict each sentence to a single claim. One subject, one action, one point, rather than packing several propositions into one grammatically complex sentence.

**Why it produces a human effect:** broadcast-writing doctrine names this because a listener cannot re-parse a confusing sentence the way a reader can re-read one, and caps sentences around 15 to 20 words with simple subject-verb-object order for exactly this reason ([Journalism University, n.d.](https://journalism.university/broadcast-and-online-journalism/language-differences-radio-print/)). A local page is skimmed on a phone under stress (the AC just died); it is consumed more like speech than like an essay. A sentence reads clearer when the actual character of the sentence is its grammatical subject and its action is the verb, rather than the action buried in an abstract noun ([Williams, via Boston University Teaching Writing, Essential Lesson 10, n.d.](https://www.bu.edu/teaching-writing/resources/essential-lesson-10/)).

**Written vs natural (local example):**
- Crammed: "Our licensed technicians, who undergo continuous training and utilize state-of-the-art diagnostic equipment, are able to identify and resolve a wide range of HVAC issues while ensuring minimal disruption to your daily routine."
- One idea per sentence: "Our techs are licensed and factory-trained. They carry the same diagnostic gear the dealerships use. Most repairs are done in one visit."

**Where it applies:** hooks, CTAs, and pricing lines first (where a lost reader costs the most), then the body throughout.

**Frequency budget:** if a sentence carries two or more commas that are not a simple list, split it. No cap on total sentence count, only on ideas per sentence.

---

### 3. Coordination over subordination (parataxis over hypotaxis)

**Mechanic:** chain independent clauses with light coordinators (and, so, then, but) instead of nesting them with subordinators (because, although, given that, which meant that). This is distinct from lever 2: lever 2 is how many ideas per sentence; this is which connectors join them once chained.

**Why it produces a human effect:** parataxis (coordination) joins clauses as independent units; hypotaxis (subordination) nests them hierarchically ([Dickinson College Commentaries, n.d.](https://dcc.dickinson.edu/grammar/goodell/parataxis-and-hypotaxis); [Wikipedia, "Parataxis," n.d.](https://en.wikipedia.org/wiki/Parataxis)). Spoken and natural writing leans on coordination because a speaker under real-time pressure does not know a sentence's subordinate structure until the main clause is already out; heavily edited prose, composed with unlimited planning time, favors deep subordinate nesting.

**Written vs natural (local example):**
- Hypotactic: "Because regular maintenance, which most homeowners tend to neglect until a breakdown occurs, is essential to prolonging the lifespan of your system, we recommend scheduling a tune-up annually."
- Paratactic: "Skip the yearly tune-up and the system dies early. So we send a reminder, and the tune-up is $189. Simple."

**Where it applies:** any explanatory or causal claim, especially "why this matters" and "how it works" sections where a "because" is tempting.

**Frequency budget:** default to coordination; reserve one subordinator per paragraph at most for a genuinely complex causal claim that cannot be split.

---

### 4. Direct address plus real questions

**Mechanic:** address the reader as "you," and open or pivot a point with a question the reader is actually asking, rather than stating the answer cold.

**Why it produces a human effect:** conversational-copywriting craft names direct "you"-address, questions, plain vocabulary, contractions, and short paragraphs as the register of spoken address rather than formal prose ([Content Marketing Institute, n.d.](https://contentmarketinginstitute.com/content-optimization/write-like-you-talk-12-tips-for-conversational-content)). Formal registers default to nominalization and hedged qualifiers because the writer is not addressing one specific person; a local page is addressing exactly one worried homeowner, and should sound like it.

**Written vs natural (local example):**
- Third-person: "Homeowners seeking to address persistent drainage issues should consider professional intervention."
- Direct address: "Got a drain that backs up every few weeks? That is not a plunger problem. It is a main-line problem, and we can camera it today."

**Where it applies:** hooks, every CTA, FAQ answers, and any section that risks talking *about* the customer instead of *to* them.

**Frequency budget:** two to three real questions per page section at most. Stacking more reads as a sales-page tic. And they must be real questions the reader has, not rhetorical setups ("So what does this mean for you?" is banned filler).

---

### 5. Specificity over abstraction

**Mechanic:** replace every generic noun phrase with the named, concrete version. The actual neighborhood, the actual price, the actual brand, the actual year, the actual crew member. This is the single highest-leverage lever for local copy, and the one most tied to the doctrine.

**Why it produces a human effect:** a system optimized to generalize across arbitrary prompts is statistically pulled toward language that stays true across many contexts ("many homeowners," "a wide range of services," "in your area"), while a person recounting their actual business names the actual thing, because that is what happened ([arxiv 2502.19614, 2025](https://arxiv.org/abs/2502.19614), documenting the same generic-vs-specific gap in AI-authored text). Specificity also carries an independent persuasion effect: precise numbers increase perceived trust and expertise, with the caveat that stacking too many in one place reduces the effect ([Peters & Markowitz, via Scientific American 2025](https://www.scientificamerican.com/article/numbers-are-persuasive-if-used-in-moderation/)).

**Written vs natural (local example):**
- Generic: "We serve many neighborhoods in the area and handle all types of plumbing problems for our customers."
- Specific: "We run about 12 calls a week between Old Town, Forest Creek, and Teravista. Half are the same 1980s slab-leak pattern under those foundations."

**Where it applies:** everywhere, but hardest on location pages, service-area pages, and any proof or differentiator section. This is the lever that makes a page un-copyable and doubles as the first-hand specificity gate.

**Frequency budget:** one or two concrete specifics per sentence at most; beyond that the persuasion and naturalness both degrade. And every specific must be true (from `brand.yaml`, the SME interview, or cited research), never invented to satisfy the lever.

---

### 6. Elision-aware phrasing (ellipsis)

**Mechanic:** omit words the reader can recover from context, instead of spelling out every subject and auxiliary verb.

**Why it produces a human effect:** ellipsis is the grammatical omission of recoverable material, and it is efficient precisely because both parties share the immediate context ([Wikipedia, "Ellipsis (linguistics)," n.d.](https://en.wikipedia.org/wiki/Ellipsis_(linguistics))). Restoring full grammatical sentences everywhere is often exactly what makes copy read as written rather than spoken.

**Written vs natural (local example):**
- Full form: "We are able to arrive on the same day for most service calls, and we do not charge any additional fee for the initial visit."
- Elliptical: "Same-day for most calls. No trip fee."

**Where it applies:** headlines, callout boxes, badges, quick-answer FAQ leads, and hero copy. Not a device to count; a permission not to over-supply completeness the context already carries.

---

### 7. Parenthetical asides

**Mechanic:** drop in a short, quick tangent set off by a pause (not embedded mid-clause), then return to the main line. Because the em dash is banned, mark the aside with a full stop and a short standalone sentence, or round brackets, never an em dash.

**Why it produces a human effect:** Wallace Chafe's Integration-versus-Involvement framework contrasts written language's *integration* (dense packing of propositions into one complex sentence via subordination) with spoken language's *involvement*: fragmentation into short units, first-person stance, real-time monitoring of the listener ([Chafe 1982/1984, via secondary literature](https://www.semanticscholar.org/paper/Integration-and-Involvement-in-Spoken-and-Written-Chafe/73344c80f884c32e3c5f239db35a415592fc973a)). A written sentence integrates a side-thought as a subordinate clause; natural writing drops the tangent as its own quick beat and comes back.

**Written vs natural (local example):**
- Integrated: "This water heater, which I installed for a client in Brushy Creek last winter during the freeze, has performed reliably ever since."
- Aside: "I put one of these in during last winter's freeze, out in Brushy Creek. Nightmare week. That unit has not skipped once since."

**Where it applies:** about-page and story sections, and any beat drawing on real experience.

**Frequency budget:** one aside per two to four sentences at most. An aside in every sentence reads as scattered.

---

### 8. Breath and pause marking

**Mechanic:** structure clauses so each fits inside one comfortable spoken breath (roughly 8 to 14 words) before a natural break. Mark the pause with a period or a line break, rather than writing one long unbroken clause that runs out of air.

**Why it produces a human effect:** broadcast writing formalizes "write for the ear, not the eye" because a listener gets one pass with no ability to re-read ([Journalism University, n.d.](https://journalism.university/broadcast-and-online-journalism/effective-radio-reporting-crafting-stories-ear/)). The read-aloud test is the mechanical proof: the eye silently assumes missing words are there and skims past a clause that would choke a speaker, while the ear is literal and cannot skip ahead ([David Klein Writing, n.d.](https://davidkleinwriting.com/readaloud.html)). A local page read aloud in the owner's voice exposes every clause that was built for the eye.

**Written vs natural (local example):**
- Unbroken: "When you call our office during regular business hours, which are Monday through Friday from 8am to 6pm, one of our friendly and knowledgeable team members will be happy to assist you in scheduling an appointment at a time that works for you."
- Breath-marked: "Call during the day and a real person picks up. Tell them what is wrong. They will book you a window that works."

**Where it applies:** every page; check hardest on any sentence that ran past ~18 words in the draft.

**Frequency budget:** no clause without a natural break for more than roughly 10 to 14 words.

---

### 9. Repeat the real noun; do not reach for a synonym

**Mechanic:** repeat the actual service name, brand name, or city on purpose across consecutive sentences, instead of swapping in a synonym purely to avoid repetition.

**Why it produces a human effect:** "elegant variation," reaching for a synonym only to avoid repeating a word, is a documented tell of over-composed writing ([Wikipedia, "Elegant variation," n.d.](https://en.wikipedia.org/wiki/Elegant_variation)). AI output cycles "your home," "your residence," "your property," "your dwelling" to avoid repetition; a person just says "your house" three times. For local SEO there is a bonus: repeating the exact service and city term is also the on-page entity signal, so the natural choice and the ranking choice are the same.

**Written vs natural (local example):**
- Elegant variation: "We repair your roof. Our specialists restore your rooftop. We rejuvenate your home's overhead structure."
- Natural repetition: "We repair your roof. Most roof repairs in Georgetown are done same-day. A full roof replacement takes two."

**Where it applies:** everywhere. Do not let a fear of repetition pull you off the plain, correct word.

---

### 10. Commit to claims; hedge only with a specific reason

**Mechanic:** state claims directly by default. Where genuine uncertainty exists, name the specific reason for it, rather than stapling a blanket disclaimer onto every sentence.

**Why it produces a human effect:** over-hedging ("it is important to note," "results may vary depending on a number of factors," "this can potentially help") is a documented AI tell ([Wikipedia, "Signs of AI writing," 2026](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing)). Real expertise commits. A tradesperson who has done a job 500 times does not hedge the price band; they name it and then name the one thing that would change it.

**Written vs natural (local example):**
- Over-hedged: "The cost of a repair may vary and could potentially range widely depending on a variety of factors, so it is difficult to provide an exact estimate."
- Committed with a specific reason: "Most water-heater repairs run $150 to $450. The one thing that blows past that is a cracked tank, which means replacement, not repair. We tell you which on the first visit."

**Where it applies:** pricing, timelines, and any "how long / how much" answer. Committing is also what makes the passage citable by answer engines.

---

### 11. Antithesis and merism instead of the tricolon

**Mechanic:** the blocklist bans the tricolon of near-synonyms ("fast, reliable, and affordable"). This lever is the positive substitute. Use **antithesis** (a two-clause contrast on parallel grammar) or **merism** (naming the concrete parts that make up a whole), and when a list is genuinely needed, favor two or four items over three.

**Why it produces a human effect:** a symmetric three-part list is low-variance and highly predictable by construction, which is exactly the shape that reads as composed rather than spoken; the rule-of-three is independently documented as a live AI-writing tell ([Wikipedia, "Rule of three (writing)," n.d.](https://en.wikipedia.org/wiki/Rule_of_three_(writing)); [GPTZero 2025](https://gptzero.me/news/the-rule-of-three/)). Antithesis makes the ear catch a repeated shape and predict the pivot, which is a listening behavior; merism swaps one abstract umbrella noun for concrete instances.

**Written vs natural (local example):**
- Banned tricolon: "We are prompt, professional, and dependable."
- Antithesis: "Other crews quote low and pad the invoice. We quote the real number and it does not move."
- Merism: "The tune-up is not one thing. It is the coils cleaned, the refrigerant checked, and the capacitor tested before it fails in July."

**Where it applies:** differentiators, hero lines, and anywhere the draft is tempted to reach for "not just X, but Y and Z."

---

### 12. "Say it, then tighten" (the production step)

**Mechanic:** a mandatory two-pass discipline, not a sentence-level device. Draft the line for meaning first. Then read it aloud, in the voice the business owner would use, and mark every stumble or place that runs out of breath. Only then tighten: cut every word the sentence still makes sense without.

**Why it produces a human effect:** this is the mechanism behind every other lever, made into a repeatable step. Separating "what to say" from "does it sound right out loud" stops a writer from polishing sentences prematurely into hedged, complete, essay-register prose, which is exactly the failure mode that produces uniform AI-style output ([Blackman four-pass method, n.d.](https://www.georgeblackman.com/write-on-time/my-4-step-scriptwriting-method-for-millions-of-views)). The tightening half has its own rule from direct-response craft: cut anything that does not add value or change the reader's next move ([Anthony Jude 2025, summarizing Hormozi's editing process](https://anthonyyjude.substack.com/p/alex-hormozis-writing-formula)).

**Written vs natural (local example):**
- Pass one (idea down): "Our team of dedicated professionals is committed to providing you with a seamless and stress-free experience from the initial consultation all the way through to project completion."
- Pass two (read aloud, then tightened): "One crew, start to finish. You get the owner's cell. If something is off, you call him, not a call center."

**Where it applies:** every page, without exception. This is the step, not a stylistic choice. Run it once per draft minimum before the page is considered ready for the gates.

---

## The AI-tell inversion table

Each row names a documented AI-writing tell and the lever that inverts it. Use it when auditing a draft to name *why* a line reads as machine-written, not just flag that it does.

| AI-writing tell | Positive lever that inverts it |
|---|---|
| Flat, uniform sentence length ([Holtzman et al. 2020](https://arxiv.org/abs/1904.09751)) | Lever 1 - burstiness |
| Deep clause-stacking before the main verb ([Dickinson College Commentaries, n.d.](https://dcc.dickinson.edu/grammar/goodell/parataxis-and-hypotaxis)) | Levers 2-3 - one idea per sentence, coordination |
| Third-person, no direct address, no real questions ([Content Marketing Institute, n.d.](https://contentmarketinginstitute.com/content-optimization/write-like-you-talk-12-tips-for-conversational-content)) | Lever 4 - direct address plus real questions |
| Vague genericity: "many homeowners," "in your area," "a wide range" ([arxiv 2502.19614, 2025](https://arxiv.org/abs/2502.19614)) | Lever 5 - specificity over abstraction |
| Full grammatical completeness where context already carries it ([Wikipedia, "Ellipsis," n.d.](https://en.wikipedia.org/wiki/Ellipsis_(linguistics))) | Lever 6 - elision-aware phrasing |
| Every proposition integrated, no tangents ([Chafe, via secondary literature](https://www.semanticscholar.org/paper/Integration-and-Involvement-in-Spoken-and-Written-Chafe/73344c80f884c32e3c5f239db35a415592fc973a)) | Lever 7 - parenthetical asides |
| Sentences that run a real speaker out of breath ([David Klein Writing, n.d.](https://davidkleinwriting.com/readaloud.html)) | Lever 8 - breath and pause marking |
| Elegant variation: cycling synonyms to avoid repeating a word ([Wikipedia, "Elegant variation," n.d.](https://en.wikipedia.org/wiki/Elegant_variation)) | Lever 9 - repeat the real noun |
| Over-hedging on every claim ([Wikipedia, "Signs of AI writing," 2026](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing)) | Lever 10 - commit; hedge only with a specific reason |
| Rule-of-three and "not just X, it's Y" as a default ([GPTZero 2025](https://gptzero.me/news/the-rule-of-three/)) | Lever 11 - antithesis, merism, or a 2/4-item list |
| Promotional inflation: "stands as a testament to," "serves as," avoided copulas ([Wikipedia, "Signs of AI writing," 2026](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing)) | Lever 5 - state the literal outcome; use "is/are" |
| Didactic scaffolding: a preview then a closing summary ([Wikipedia, "Signs of AI writing," 2026](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing)) | Open on the concrete answer; end on a fact, never narrate the page's own shape |

---

## Naturalness rubric

Run this after the structural draft, alongside the read-aloud step (lever 12), before a page goes to the gates.

1. **Read-aloud test.** Read the line aloud in the owner's voice. Did it trip the tongue, force an unplanned breath, or need a re-take? If yes, rewrite; do not just re-read it (lever 12).
2. **Burstiness present.** Three or more consecutive sentences of matching length? Break at least one (lever 1).
3. **Specificity present.** Does every claim carry a named neighborhood, price, brand, date, or person rather than "many," "various," "in your area" (lever 5)?
4. **One idea per sentence held.** Any sentence stacking two or more subordinate clauses before the main verb resolves (levers 2-3)?
5. **No accidental tricolon.** Scan for a rule-of-three list or a "not just X, it's Y" that slipped past the ban; replace with antithesis, merism, or a 2/4 list (lever 11).
6. **Ellipsis / economy check.** Any fully spelled-out sentence where the context already carries the missing words (lever 6)?
7. **Commitment check.** Any blanket hedge that should be a committed claim with one named exception (lever 10)?
8. **Aside and breath check.** Quick set-off tangents rather than everything integrated, and does every clause fit one comfortable breath (levers 7-8)?
9. **AI-tell scan.** Cross-check against every row of the inversion table.
10. **The gut check, last.** Would the owner of this business say this out loud to a neighbor across the fence? This is the last check, not the only one.

A draft that passes item 10 alone but fails several of items 1-9 is not done. It passed the vibe check without passing the craft check.

---

## How to use this file

The `voice-writer` behavior loads this file alongside the client `brand.yaml` voice block and runs the naturalness rubric as an explicit pass, after the passage-block outline is locked but before the page goes to the gates (the same point where lever 12's "say it, then tighten" sits). The voice-fidelity gate in `knowledge/quality-gates/gates.md` grades against this rubric: a page can fail on flat rhythm, missing specificity, or an accidental tricolon alone, even with zero blocklist phrases present. When a client's real voice profile exists, it overrides any generic rule here on conflict. This file is the general engine that gets a page to sound human; the client profile is what gets it to sound like that one business.
