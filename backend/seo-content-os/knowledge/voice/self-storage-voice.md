# Self-Storage Voice Layer

The niche voice layer for self-storage. Loaded by `voice-writer` and `critical-editor` (Stages DRAFT + HUMANIZE) whenever `brand.yaml.vertical == self-storage`, ON TOP of the universal humanization (`knowledge/voice/`) and the client's own `brand.yaml` voice block. It teaches how storage operators and renters actually talk, the trade vocabulary the copy must never fumble, and the one rule that makes storage trust-copy work: mechanism, not reassurance.

Built from `research/self-storage-2026-07/05-voice-language.md` (operator forums, renter fear accounts, the trade glossary). The self-storage cliche blocklist lives in `knowledge/voice/vocabulary-blocklist.md` (the `### Self-storage cliches` section, auto-loaded by `blocklist_lint.py`); this file is the positive craft that replaces those cliches.

---

## 1. Two registers, never crossed

Storage operators speak in two registers. Our public copy borrows from exactly one.

- **Back-of-house register** (Inside Self Storage, Self-Storage Talk, the revenue-management trade): blunt, tenant-vs-operator, money-and-liability first. ECRI, in-place rate, overlock, delinquency, lien, auction. We READ it to sound like we know the business; we NEVER write it to a renter. The acronyms operators love are the words that make a renter feel handled.
- **Front-of-house register** (the counter manager, the owner's reply to a review, the GBP post): plain, direct, locally specific, owner-present, allergic to corporate polish, unsentimental about money. THIS is the register our operator-voice pages emulate.

---

## 2. The front-of-house operator voice (what our pages sound like)

- **Plain and declarative.** Short sentences. Facts, not adjectives. "Drive-up units, ground floor, 24-hour gate access." Not "premier storage solutions designed with you in mind."
- **Locally rooted.** Names the town, the road, the cross-street, the gate, the manager. The trade's own critique: generic slogans "shouldn't be copy-paste[d]," and marketing that works in one market "can fail spectacularly in another."
- **Operationally specific.** A good operator answers in unit sizes, gate hours, lock types, and dollar amounts, because that is how they think. The move-in special, the admin fee, the month-to-month term are stated flatly.
- **Owner-present.** Reads like a named human ("I'm Dave, I run the Route 9 location"), not a brand voice. The counter manager is the E-E-A-T asset (Law 16): they have watched what floods, what freezes, what gets broken into, which units a two-bedroom actually fits.
- **Unsentimental about money.** Comfortable stating price, late-fee timing, and lien consequences directly. Honesty about fees reads as competence, not as a downer, and pre-empts the renter's #2 fear.

### Operator sentence patterns (draw on these)
- Fact-stack, no connective tissue: "Ground-floor drive-up. 10x20. $145 a month. First month $1, plus the $29 admin fee."
- Named-place anchor: "Our Belmont Ave lot sits behind the [named landmark]; the gate opens at 6am."
- Manager-as-narrator: "I've cut more locks off 10x10s than I can count, so here's what actually fits one."
- Direct consequence, no euphemism: "Rent's due on the 1st, late after the 5th. I'd rather help you keep the unit than send a lien letter."
- Proof by specific: "Every unit on the south row is climate-controlled to 55-80F. I check the thermostats on my Monday walk."

---

## 3. The renter voice (meet their words, then anchor to yours)

Renters are not shopping storage; they are solving a life event (a move, a downsize, a death, a divorce). They arrive anxious and time-pressured and they do not know the vocabulary. They say "space" and "stuff," not "unit." Meet them there, then anchor to the trade term without condescension.

### The five questions every renter is really asking (in priority order)
1. **What fits / what size do I need?** The single highest-intent question. They think in rooms and truckloads, not square feet. This is the money passage (Section 6).
2. **How much / any hidden fees?** They have been burned by move-in-rate-vs-later-bill surprises. They ask about the total up front.
3. **Is my stuff safe?** Security is emotional, not technical. They want to know it will not be stolen.
4. **When can I get in?** Where the gate-hours / access-hours / office-hours confusion lives. Always separate the two clocks.
5. **Will my stuff survive?** Climate, humidity, mold, pests, water.

### The renter's fear vocabulary (what a great page defuses)
Renters' worst cases are concrete and visceral, and they read like this in the wild: break-in then denied claim ("the coverage did not apply"); fees then auction; pests ("roach eggsacks... rat feces"); water ("around $15,000 of amplifiers, speakers, guitars... were ruined," "he said I was stuck out of luck"). The pattern: they fear theft, water/mold/pests ruining irreplaceable things, surprise fees, and losing everything to an auction they did not see coming. A page that names how THIS facility prevents each, with a dated first-party detail, converts. Vague reassurance does the opposite: it pattern-matches to the exact companies that let them down.

### Translate, don't correct (map their words to ours)
| Renter says | Anchor to (do not correct) |
|---|---|
| "space," "spot," "a place to put my stuff" | unit |
| "the size of a one-car garage" | 10x20 drive-up |
| "getting in after work," "24-hour access" | access hours / gate hours |
| "temperature controlled," "AC unit," "won't get moldy" | climate-controlled (vs temperature-controlled) |
| "drive right up to it" | drive-up unit |
| "no long contract" | month-to-month, no deposit |
| "the deal," "first month free thing" | move-in special |
| "the extra fee they didn't tell me about" | admin fee, tenant protection plan |
| "they raised my rent for no reason" | (an ECRI - NEVER say this to them; explain the increase plainly) |
| "will they steal my stuff / can someone break in" | gated access, individual door alarms, cameras, disc lock |

---

## 4. The trade glossary the copy must never fumble

Getting one of these wrong is an instant credibility tell to an operator and to a renter who has rented before. The precision pairs:

- **Climate-controlled (temp + humidity) vs temperature-controlled (temp only).** The humidity distinction is exactly what a worried renter is asking about. Never use them interchangeably (and see overlay SS-5: no moisture promise without real humidity control).
- **Gate hours / access hours vs office hours.** Access hours = when a tenant can reach their unit; office hours = when staff are present. Conflating them is the #1 renter grievance vector. Keep them distinct in copy; never claim 24-hour access the gate does not grant.
- **Disc lock (round, shrouded shackle, bolt-cutter-resistant) vs cylinder lock (flush-mounted, drill-proof).** A page that specifies which lock the facility sells/requires reads as expert.
- **Tenant protection plan (operator-billed self-indemnity) vs tenant insurance (tenant-bought, state-licensed).** Never call a protection plan "insurance" (overlay SS-1; `Heckart`).
- **Reservation (no payment, a hold) vs rental (money moves, unit is theirs).** Governs the CTA (see `research/self-storage-2026-07/04-conversion-cro.md`).
- **Move-in / street rate vs in-place / achieved rate.** The web rate is a teaser, not a locked price; never present it as permanent (overlay SS-8).
- **Drive-up unit, roll-up door, month-to-month, prorate, unit mix, occupancy** (physical / square-footage / economic - mixing them is an operator tell).
- **Back-of-house only, never in renter copy:** ECRI, overlock, delinquent / in lien, lien letter, revenue management, PMS, REIT, 28-day billing.

---

## 5. The mechanism-not-reassurance rule (the load-bearing rule)

Because the renter's fears are concrete (theft, water, pests, fees, auction), **every security / safety / climate claim must carry a specific defense, or it reads as the same empty promise that burned them.** This is both a voice rule and a compliance rule (overlay SS-3/SS-5).

- "Clean, safe and secure" -> "Gated, 24-camera lot; the manager lives on-site and cuts the lights at 10pm; every unit takes a disc lock we sell at the counter for $12."
- "Climate controlled units available" -> "Held at 55-80F with dehumidification; 'climate controlled' isn't a regulated term, so here's exactly what we control."
- "Convenient access" -> "Gate access 6am-10pm daily, with a per-tenant code that logs every entry and exit."
- "Highly rated" -> "[X] Google reviews, [Y]-star average."

Only this business can truthfully write the second version of each, because only this business has those cameras, that thermostat, that gate log. That is the entire point (Law 16).

---

## 6. The size question is the money passage

"What fits in a 10x10" is the highest-intent renter query. Answer it in rooms-and-boxes, not square feet, as a self-contained passage block that leads with the answer:

- BANNED (Tier-3 non-answer): "The size you need depends on how much you have."
- REQUIRED (direct-answer-first): "A 10x10 holds a one-bedroom apartment: a bed, a sofa, a dresser, and about 100 boxes. A 5x10 handles a studio's worth. Not sure? Most people size up one step."

Give the real dimensions, the physical-world equivalent, and the honest capacity (the realistic count, not just the brochure maximum), and keep capacity numbers internally consistent across the page (the Big Tex blog's "150-200 boxes" body vs "80" FAQ is the verified fail).

---

## 7. Fee honesty is a voice asset

Stating the admin fee, the required protection plan, the late-fee timeline, and true month-to-month up front reads as operator competence and pre-empts the #2 renter fear. It is also compliance (overlay SS-6: the admin fee is disclosed in-line with any "free" claim, never in a footnote). Do not hide fees to inflate the "free" hook; the honest total converts better and never becomes a checkout surprise (SS-CV3).

---

## 8. Handoff to the writer

- Two registers, never cross them. Front-of-house: plain, local, specific, owner-present.
- Translate, don't correct. Meet renters at "space" and "stuff," then anchor to "unit," "drive-up," "climate-controlled."
- Every reassurance carries a mechanism (Section 5). No bare "safe and secure," "peace of mind," "space solutions" (blocklist).
- The size question is a direct-answer passage block (Section 6).
- Fee honesty up front (Section 7).
- Layer the client's own `brand.yaml` voice over this; never ship a generic storage voice.

---

## Sources

- `research/self-storage-2026-07/05-voice-language.md` (operator + renter voice, the trade glossary, the cliche corpus), `06-eeat-experience.md` (the mechanism specs), `04-conversion-cro.md` (reservation vs rental, fee honesty).
- System: `knowledge/voice/vocabulary-blocklist.md` (the `### Self-storage cliches` deterministic ban), `knowledge/verticals/self-storage.md` (SS-3/SS-5/SS-6 as compliance), `knowledge/voice/natural-voice-engineering.md` + `sentence-rhythm.md` (the universal humanization this layers onto).
