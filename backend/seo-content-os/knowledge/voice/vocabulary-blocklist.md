# Vocabulary Blocklist - Local Service Copy

The words and phrases that mark a page as AI-written to any reader who has read more than a handful of LLM outputs. Banned in SEO-CONTENT-OS output. The scan runs during drafting (self-check every sentence before writing the next) and again at the voice-fidelity gate before finalize.

This is not detector-evasion. It is craft. These phrases read as machine-generated to a *human* reader, and they are almost always a symptom of a thin sentence with no real local fact in it. If a phrase below "fits perfectly," the sentence is wrong: it is generic where it should name a neighborhood, a price, a crew, a year. Rewrite from a more specific premise. See the "if you reach for a banned word" note at the bottom.

The list is thorough on purpose. Nothing leaves it just because it stopped being trendy.

---

## Tier 1 - hard ban (zero tolerance)

Any single Tier-1 hit fails the sentence. Run a literal scan; rewrite every match.

### Verbs

- delve, delve into
- leverage / leverages / leveraging (as a verb)
- navigate (metaphorical: "navigate your insurance claim," "navigate the process")
- empower / empowers
- unlock ("unlock savings," "unlock the value of your home")
- elevate (metaphorical: "elevate your curb appeal")
- transform (as filler: "transform your space"; OK when literal)
- streamline / streamlines (as filler)
- foster (metaphorical)
- harness (metaphorical)
- revolutionize / revolutionizing
- supercharge, turbocharge, skyrocket
- ensure (as the reflexive AI closer: "ensuring your complete satisfaction"; see Tier 2 for the literal use)
- boast ("we boast a team of...")
- pride ourselves / take pride ("we pride ourselves on quality workmanship")
- strive ("we strive to exceed expectations")

### Adjectives

- seamless (as filler: "seamless experience," "seamless process")
- robust
- comprehensive
- unparalleled
- unmatched
- top-notch
- top-of-the-line
- state-of-the-art (allowed only when literally true and named, e.g. a specific machine)
- cutting-edge
- world-class
- best-in-class
- industry-leading (if true, name the metric)
- premier ("your premier provider of...")
- trusted (as a decoration: "your trusted partner"; OK when tied to a real number, e.g. "trusted by 400 homeowners since 2009")
- reliable, dependable, trustworthy (when stacked as near-synonyms)
- exceptional, superior, unrivaled
- meticulous, dedicated, committed (as filler adjectives about the team)
- hassle-free, worry-free, stress-free
- affordable (as a bare claim with no price; name the number or the range)

### Nouns and metaphors

- solutions ("plumbing solutions," "roofing solutions," "your heating solution")
- partner ("your trusted partner in home comfort")
- journey ("your home renovation journey," "your comfort journey")
- peace of mind (as a tacked-on benefit phrase)
- landscape (metaphorical: "the local roofing landscape")
- realm, arena, world of ("the world of HVAC")
- one-stop shop / one-stop solution
- game-changer
- backbone ("the backbone of your home")

### Phrases (the local-copy AI tells)

- when it comes to [your plumbing / your roof / your family's comfort]
- look no further
- nestled in the heart of [city]
- in the heart of [neighborhood]
- whether you're [A] or [B]
- from [X] to [Y], we do it all
- we've got you covered
- rest assured
- at [Brand], we understand that...
- at [Brand], we believe that...
- we understand that your home is your biggest investment
- your satisfaction is our top priority
- we go above and beyond
- second to none
- the go-to [service] for [city] residents
- proudly serving [city] and surrounding areas (the bare version; OK only when the real coverage list and a real reason follow)
- for all your [plumbing / electrical / roofing] needs
- give us a call today (as the reflex closer; the CTA must be specific, see hooks-and-titles.md)
- contact us today to learn more
- don't hesitate to reach out
- in today's fast-paced world
- in conclusion, to sum up, to summarize
- it's important to note that, it's worth noting that
- needless to say
- rest easy knowing
- experience the difference
- the [Brand] difference
- quality you can trust
- committed to excellence / dedicated to excellence
- unwavering commitment
- tailored to your needs / tailored to meet your unique needs
- customized to your specific needs
- our team of experts / our team of skilled professionals / our team of dedicated professionals

### Tricolons of near-synonyms

- "fast, reliable, and affordable"
- "professional, courteous, and dependable"
- "licensed, bonded, and insured" is allowed ONLY as a literal factual claim tied to real numbers; banned as a rhythm decoration
- "quality, integrity, and service"

If three words mean the same thing, use one. If they mean different things, make the difference explicit with a fact.

### Self-storage cliches

The mass-produced self-storage slogan corpus (verified verbatim against published storage-slogan lists). Every entry names no size, price, gate hour, camera count, or held temperature, and several pattern-match to the exact empty promise that burned a renter who got robbed or flooded (so they read as untrustworthy, not just generic). Banned for self-storage clients; harmless elsewhere (no plumber writes "storage made easy"). Reframe rule: reaching for one means the sentence lacks a fact - name the size, the gate window, the camera count, the disc lock, the price, the manager (see `knowledge/voice/self-storage-voice.md`).

- space solutions / storage solutions / your storage solution / self-storage solutions
- "space solution for every situation"
- "your space, your way"
- more than just storage / not just a storage facility
- "clean, safe and secure"
- safe and secure
- your belongings are safe with us / your stuff is safe and sound
- safe and sound
- safe haven / safe harbor for your belongings
- where security meets serenity
- rest easy knowing your stuff is safe / sleep easy knowing your belongings are safe
- worry-free storage / stress-free storage
- all space no worry
- storage made easy / storage made simple / renting made easy
- storage you can trust / trust your belongings with us
- where your belongings belong
- your treasured belongings / your precious memories / your prized possessions
- "peace of mind, piece by piece"

---

## Tier 2 - context-banned (allowed only when literal or load-bearing)

Flagged for review. Pass only if the use is literal, specific, and genuinely the right word.

- ensure (use "make sure"; "ensure" is fine in a literal warranty or safety sentence)
- utilize (use "use")
- provide / provider (fine occasionally; banned when every sentence is "we provide")
- offer ("we offer a range of services" - be specific about which)
- numerous, various, a variety of, a wide range of, an array of (name the actual list)
- significant, substantial (quantify it: how much)
- quality (as a bare noun: "quality work"; fine when tied to a specific standard or spec)
- professional (as a bare adjective; fine when it means licensed/credentialed and you name it)
- expert / expertise (fine when backed by a credential, years, or a named person; banned as decoration)
- efficient (quantify: how much faster, how much cheaper)
- competitive pricing / competitive rates (name the price, the range, or the guarantee)
- state-of-the-art, advanced (only if you name the actual equipment or method)
- prompt, timely (name the response window: "on-site within 90 minutes")
- surrounding areas (only with the real coverage list)

---

## Tier 3 - structural anti-patterns

Not single words, but AI structures. The critical-edit pass catches these.

### The "more than just" formula

"We're not just a plumbing company. We're your partner in home comfort." Banned. Open with the real claim, not the negated decoy.

### The "At [Brand], we..." reflex opener

"At Round Rock Roofing, we understand that your roof is your home's first line of defense." Cut. Start with the actual point the homeowner needs.

### Empty benefit-stacking close

"...giving you peace of mind and the confidence that your home is in good hands." Cut. End on a specific fact, a number, or the specific next action.

### Setup-payoff filler

"Here's the thing." "But here's the kicker." "Here's where we come in." Cut.

### Empty transition openers

"Furthermore," "Moreover," "Additionally," "However" when not load-bearing. Most are deletable. If more than two paragraphs on a page open with one, flag.

### Hedge stacking

"may potentially help to provide" becomes "helps." "can often be quite costly" becomes "costs $X to $Y." Commit to the claim; where real uncertainty exists, name the specific reason for it.

### The hypothetical-customer opener

"Imagine you wake up to a flooded basement at 2am..." Banned. Use a real customer scenario from the SME interview, not an invented one. (A fabricated scenario also fails the first-hand specificity gate.)

### Anaphora cascade

Three or more sentences in a row starting with the same word, especially "We," "Our," "At," "This." Reads as scaffolding. Break the pattern.

### The generic FAQ answer

"The cost of a new roof varies depending on a number of factors." Banned as an answer opener. Lead with the actual range: "A new asphalt-shingle roof in Round Rock runs $8,500 to $14,000 for a typical 2,000 sq ft single-story." (This is also the passage-block direct-answer rule.)

---

## Em dash

Banned workspace-wide (U+2014). The Write/Edit hook fails any attempt to write the character. Use a hyphen, comma, parentheses, or rewrite.

---

## Per-client banned phrases

Each client's `brand.yaml` voice block carries a `banned_phrases` list specific to that business. Those append to Tier 1 at write time. A dentist might ban "painless" (a claim they cannot make); a law firm might ban "guarantee" (a compliance line). Load the client list alongside this file.

---

## Enforcement

1. **During drafting.** Self-check every sentence against Tier 1 before writing the next. A Tier-1 hit blocks the sentence; rewrite from a more specific premise.
2. **At the critical edit.** Scan the full draft for missed hits plus the Tier-3 structures.
3. **At the voice-fidelity gate** (`knowledge/quality-gates/gates.md`). A deterministic scan produces the final hit list. Any confirmed Tier-1 or Tier-3 hit fails the gate and reroutes to a rewrite. The `/qa` command and `compliance-auditor` agent run this.

---

## If you find yourself reaching for a banned word

It signals one of three things, and the fix is always upstream of the sentence:

1. The sentence is filler and should be cut.
2. The section premise is too generic and needs a specific local angle (a neighborhood, a price, a named crew member, a real job).
3. You do not have the source material yet: the SME interview is thin, or `brand.yaml` lacks the specifics. Get the fact, do not paper over its absence with a fluent phrase.

Patching by substitution rarely works. Swapping "top-notch" for "excellent" fixes nothing. The rewrite has to start from a more specific premise: what actually makes this business's work good, in words only this business could truthfully say.
