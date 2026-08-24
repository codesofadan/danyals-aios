# Passage Block Protocol

This file defines the format that every H2 answer section on a SEO-CONTENT-OS page follows. It is the most consequential structural rule in the writing engine, because it is what makes a local page citable by Google AI Overviews, ChatGPT search, Perplexity, and Claude. It is the mechanical execution of doctrine Law 13: optimize for the answer, not only the link.

If you remember nothing else: a SEO-CONTENT-OS page is a federation of passage blocks, not a flowing brochure. Each H2 is a self-contained retrieval unit that could be lifted out and cited by an AI answer engine without the rest of the page. The page as a whole still converts a homeowner or business owner into a phone call; the H2 sections, individually, are each cleanly extractable.

Related but separate: `internal-linking.md` owns how these blocks link to each other. This file owns the block itself.

---

## Why extractability matters more for local queries

Local service queries are the most answer-engine-hungry queries there are. "Water heater replacement cost Tempe", "do I need a permit to replace my roof in Austin", "emergency plumber near me open now", "how long does AC install take" - a huge share of these now resolve inside an AI Overview or an assistant answer before the user ever clicks. The person asking has a job to be done in a specific place, and the engine wants a specific, local, trustworthy answer it can quote.

That is the opening. A national brand writing generic copy cannot answer "what does this cost in Tempe" with a real Tempe number. A local business that carries its own prices, permit facts, timelines, and service-area specifics can. Extractable local passage blocks are the single highest-leverage way a small service business gets named inside answers it could never outrank for on the blue links. Being the cited source is often worth more than position 3, because the citation appears above the links and carries the business name into the answer itself.

---

## What a passage block is

A passage block is one H2 section built so that a retrieval system can lift it out, trust it, and cite it standing alone. Three properties define it:

1. **Self-contained.** It answers its own question with zero dependency on any other part of the page. No "as mentioned above", no "as we covered in the intro", no "see the section below". If the block were the only thing an engine ingested, it would still be a complete, correct answer.
2. **Answer-first.** The direct answer lands in the first one or two sentences, before any setup or context.
3. **Concretely local.** It carries the specifics only this business in this city has: a real price band, a real permit rule, a real timeline, a real neighborhood or code requirement, named by the client's `brand.yaml` or verified in research, never invented.

---

## The anatomy of a passage block

Every H2 answer section on a SEO-CONTENT-OS page is:

1. **H2 phrased as, or close to, the real question.** Use the words a local searcher actually types. "How much does water heater replacement cost in Tempe?" beats "Water Heater Replacement Pricing". "Do I need a permit to replace my roof in Austin?" beats "Permits and Regulations". The header is the retrieval hook; match it to the query, not to a brochure heading. Question-form or claim-form headers get extracted far more often than noun-phrase labels.

2. **Direct answer in the first 1-2 sentences.** The opening sentence answers the H2's implicit question outright, with a specific local number or fact. Not "There are several factors that affect water heater cost." That is filler and it never gets cited. Lead with the answer: "Replacing a standard 40-to-50-gallon tank water heater in Tempe typically runs $1,400 to $2,600 installed, depending on tank size, gas versus electric, and whether the existing connections are up to current code." The lead sentence is what AI Overviews lift verbatim most often when this block is the cited source.

3. **Supporting specifics next.** After the direct answer, the block earns trust with the real detail behind it: what moves the price, what the permit process actually involves, what the timeline depends on, what a local homeowner should watch for. One idea per paragraph. Each paragraph carries at least one concrete anchor: a number, a named local requirement, a code reference, a neighborhood, a brand of equipment, a season.

4. **Local specificity is mandatory, not optional.** A passage block on a local page that could have been written for any city in the country has failed, even if it reads cleanly. The whole point is the specific: the Tempe permit fee, the Maricopa County inspection step, the tankless upsell that makes sense in Arizona hard water, the summer AC-season lead time. If the only local word in the block is the city name dropped into otherwise generic copy, it is a doorway block. Rewrite it from a real local fact.

5. **Self-contained close.** The last sentence is the strongest standalone-citable line in the block: a specific recommendation, a clear factual assertion, a number. Not a transition ("In the next section we will cover installation") and not a hedge ("This may vary"). It is the sentence you would expect an engine to quote if it quoted only one line.

6. **Facts come from the client, never from the model.** Every price, permit rule, timeline, credential, and service-area fact is pulled from `clients/<client>/brand.yaml`, from the SME interview, or from cited live research (the city permit office page, the client's own published rates). If a specific is not available, the writer asks for it or researches it. A fabricated local fact is the fastest path to a trust penalty and it makes the citation actively harmful when an engine repeats it.

---

## Length targets

- **Standard answer block: 120 to 220 words**, measured from the first sentence after the H2 to the last sentence before the next heading. Median target 150 to 180. Below roughly 100 words the block is too thin to carry enough context for an engine to confidently attribute it. Above roughly 300 words retrieval models start truncating or summarizing, which lowers attribution accuracy and dilutes the citation.
- **The "short answer" opener** (a page's first H2, when it is a direct "how much / how long / do I need" question) may run 60 to 120 words. This is often the block that wins the most AI Overview citations for the whole page, so it is worth writing tightest.
- **FAQ entries: 40 to 150 words each.** An FAQ section is one section made of many small sub-blocks; the per-block length rule applies to each Q and A pair, and the whole FAQ can run 400 to 800 words. Each Q is phrased as the real question; each A leads with the direct answer.

---

## Formatting for extraction

Use structure where it genuinely helps an engine lift the answer, not for decoration.

- **A short list** when the answer is naturally a set: what a permit application requires, what is included in a tune-up, the steps of an install-day visit. Lists get extracted cleanly into AI answers.
- **A small table** when the answer is a comparison or a price-by-variant: tank size versus price band, service tier versus what is covered, gas versus electric. Keep it to a few rows; a giant table fragments retrieval.
- **Bold the specific** sparingly, on the number or the rule that is the actual answer, so a human skimming and a parser both find it fast.
- **Prose still leads.** The direct-answer sentence comes before any list or table, so the block has a citable lead line even when the payload is structured.

Never format for its own sake. A block that is a wall of bullets with no lead sentence is as un-citable as a block of vague prose.

---

## The rules

1. Every H2 is a self-contained answer to a real local question.
2. The direct, locally specific answer lands in the first 1-2 sentences.
3. One idea per paragraph; every paragraph carries at least one concrete local anchor.
4. No backward or forward references. No "as mentioned above", no "see below".
5. Every local specific traces to `brand.yaml`, the SME interview, or cited research. Nothing invented.
6. The close is a standalone-citable line, not a transition or a hedge.
7. Local specificity is required. City-name-swap templated copy is a doorway block and fails.
8. Never write for a detector. Per doctrine Law 8, Google is method-agnostic and punishes scaled low-value content, not AI provenance; detector scores have near-zero correlation with rankings. A block reads human because it carries real local facts a competitor does not have, not because it was laundered. There is no "passes AI detection" step, ever.

---

## Worked example: BAD passage block

### H2: Water Heater Replacement Pricing

> When it comes to replacing your water heater, there are several factors to consider. Every home is different, and pricing can vary based on a number of variables. It is important to work with a trusted, experienced professional who can assess your unique needs and provide a customized solution.
>
> Our team is dedicated to delivering top-quality service at competitive prices. We pride ourselves on transparency and customer satisfaction, and we will work with you every step of the way to ensure you get the best value for your investment.
>
> Whether you have a small home or a large family, we have the expertise to handle all your water heater needs. Contact us today for a free quote and let us show you why so many homeowners trust us with their plumbing.

**Why this fails every rule:**
- **No direct answer.** The reader asked what it costs. The block never says a number. The lead sentence is "there are several factors to consider", which is pure filler.
- **Zero local specificity.** Nothing in it is about Tempe, Arizona, Maricopa County, hard water, or any real place. Swap in any city and any trade and it still "works", which means it works for nobody. This is a doorway block.
- **Not self-contained as an answer.** An engine has nothing to extract. There is no fact, no number, no permit rule, no timeline to cite.
- **Wrong header form.** "Water Heater Replacement Pricing" is a brochure label, not the query. Searchers type "how much does water heater replacement cost in Tempe".
- **Sales close, not citable close.** "Contact us today" is a call to action, not a quotable statement.

This block would never be cited by an answer engine and reads as generic AI-or-agency filler to a human. It fails the passage-block gate and the local-specificity gate.

---

## Worked example: GOOD passage block

### H2: How much does water heater replacement cost in Tempe?

> Replacing a standard 40-to-50-gallon tank water heater in Tempe typically runs **$1,400 to $2,600 installed**, and switching to a tankless unit runs **$3,200 to $5,500** because it usually requires a gas-line upsize and new venting. The single biggest swing in that range is code compliance: Tempe follows the 2018 International Plumbing Code, and if your existing install predates it, we add an expansion tank, a drain pan, and a seismic strap, which is roughly $180 to $350 in parts and labor.
>
> Fuel type moves the number too. Gas units cost more to install than electric because of venting and gas-line work, but they recover heat faster, which matters for larger Tempe households running back-to-back showers in a hard-water area where sediment buildup shortens tank life. We flush and inspect the gas line on every gas replacement rather than reconnecting the old one blind.
>
> A straightforward like-for-like tank swap is a same-day job, usually 2 to 3 hours on site. If we are relocating the unit or converting to tankless, plan for most of a day and a separate city inspection. Every quote we give is a flat installed price with the permit and haul-away of the old unit included, so the number above is what you pay, not a starting point.

**Why this works:**
- **Answer-first.** Sentence one gives two real price bands with the specific driver behind each.
- **Locally specific and true.** Tempe, the 2018 IPC reference, hard water, the inspection step, the expansion tank and strap, the same-day timeline. These are facts a local plumber has and a national page cannot fake. (In production, each of these is pulled from `brand.yaml` or verified against the Tempe code page in research; the numbers here are illustrative of the shape, not to be copied blind.)
- **Self-contained.** Lift this block out and it fully answers the question with numbers, drivers, and timeline. Nothing points elsewhere on the page.
- **One idea per paragraph.** Price and code, then fuel type, then timeline and what is included.
- **Citable close.** "The number above is what you pay, not a starting point" is a specific, quotable trust claim.
- **Header matches the query.** Phrased exactly as a Tempe homeowner would ask an assistant.

---

## Second worked example: a permit answer block

### H2: Do I need a permit to replace my roof in Austin?

> Yes. The City of Austin requires a building permit for a full roof replacement on almost every residential structure, and re-roofing without one can force a tear-off and re-inspection at your cost if it surfaces during a future home sale. We pull the permit for you as part of every full replacement; you do not file anything yourself.
>
> A repair of a small section, generally under one roofing square (100 square feet) and not touching the decking, usually does not need a permit. The line most homeowners cross without realizing it is decking replacement: the moment rotten sheathing comes off, it is a structural change and the permit and inspection apply. We flag that on the estimate before work starts so there is no mid-job surprise.
>
> Austin also enforces specific requirements a permit triggers, including proper underlayment and, in some zones, a wind-uplift rating tied to the roof pitch. On a typical asphalt-shingle replacement the permit and inspection add 3 to 5 business days to the timeline, which we build into the schedule up front.

This block answers the yes/no in word one, draws the real local line most people get wrong (decking versus surface repair), names the city and a specific code trigger, and closes on a concrete timeline. It is the kind of block that gets named in an AI Overview for "roof permit Austin" queries.

---

## How each of the 6 page types uses passage blocks

Passage blocks are the atomic unit of every page type. Where they sit differs:

- **Service-in-city combo page (the money page).** Highest passage-block density. The "how much does [service] cost in [city]" block, the "how long does it take" block, the "do I need a permit / permit and code" block, the local-process block, and a full FAQ of 4 to 8 sub-blocks. This is the page that wins the most local answer-engine citations, so it carries the most extractable answers.
- **Location / city page.** A "what to expect when you call us in [city]" block, a "how fast can you get to [neighborhoods]" block, local-proof blocks (jobs done, conditions specific to that city), and city-scoped versions of the top service-cost questions. Every block must carry that city's real specifics or it becomes a doorway page.
- **Service page (brand-wide).** Answer blocks scoped to the service, not a single city: "what does [service] involve", "how do I know I need it", "what does it typically cost" with a range and the drivers, "how long it takes". These get localized further on the service-in-city pages that sit under this one.
- **Homepage.** Short service-summary blocks, one per core service, each a compact 2-to-4-sentence answer to "what is [service] and do I offer it here", each leading to its service hub. Plus a "who we are / where we work" block that anchors the business entity. Homepage blocks are tighter than deep-page blocks but follow the same answer-first rule.
- **About page.** Blocks that answer trust and E-E-A-T questions directly: "how long have you been in business", "are you licensed and insured in [state]", "who does the work". Answer-first with the real credential, license number where public, and years, all from `brand.yaml`. These blocks feed both human trust and entity clarity for answer engines.
- **Service-area page.** A coverage block that answers "which areas do you serve" with the real named list, and per-area mini-blocks only where each area carries genuine local specifics (response time, a neighborhood quirk, a code difference). Where there is nothing locally true to say about an area, it gets a linked list entry, not a fake near-duplicate block. This is the anti-doorway rule applied at the block level.

Across all six, the discipline is the same: every H2 stands alone as a locally specific, answer-first, cited-facts block, and the page as a whole still reads as one business talking to one customer in one place.
