# About / Team Page - The Local-SEO Build Playbook

Page type: the About / Meet-the-Team page for a local service business (plumber, roofer, HVAC, electrician, dentist, med-spa, law firm, pest control, landscaping, restoration). Command: `/write-about-page`. This is the E-E-A-T and trust surface: the one page a skeptical local buyer opens on purpose, late in the decision, to answer a single question before they call, "can I trust these actual people to come into my home or handle my case."

Read before this file: `knowledge/doctrine/seo-system-doctrine.md` (Law 8 governs; Law 13 on answer-engine visibility applies), `knowledge/doctrine/google-compliance-spine.md`, and the E-E-A-T foundation. Load the client's `clients/<slug>/brand.yaml` before drafting; the `eeat:` block is the raw material for the whole page.

Reading contract. Every benchmark and lift figure in this file is directional, used to rank effort, never quoted to a client as a promised result. The only hard constraints are the legal, consent, and Google-policy rules in sections 8 and 11, which are law and platform policy, not opinion. Two teardowns in this file (section 5) were read live on 2026-07-20 and are cited with URLs; pull them fresh before quoting, because live pages change. Every named framework (StoryBrand, Lencioni, Handley, Fishkin, Klettke, Von Restorff) is a craft convention with explanatory power, not controlled-study proof, and is labeled as such.

The one difference from the generic B2B About page. The dominant teardown corpus for About pages is B2B SaaS with a "we built it for ourselves" origin (Basecamp, Help Scout, Wistia). That founder-as-first-user story does not exist for a plumbing company. A local service business runs the **earned-competence** origin path instead: the specific gap or failure the owner watched happen in local homes, and the trade skill they earned to fix it. And a local business carries a trust burden the SaaS corpus never models: the reader is deciding whether to let a stranger into their home or trust them with their body, their house, or their legal exposure. That raises the stakes on real names, real faces, real license numbers, and real local roots to the top of the page. This playbook is built around that difference.

---

## 1. Purpose and the one job

The one job: convert a skeptical local buyer by proving the real humans, real experience, and real trust behind the business, so the call feels safe to make.

Nobody lands on an About page to be entertained. They arrived because they are close to buying and they are checking you out. For a national SaaS the About page is a nice-to-have. For a local service business it sits directly on the money path, because the local buying decision is a trust decision about letting a specific person into a specific home. The plumber will be under the sink while the homeowner is alone in the house. The roofer will be on the roof over the kids' bedrooms. The dentist will have hands in the buyer's mouth. The lawyer will hold the buyer's financial future. In every one of those, the question is not "is this the cheapest option," it is "are these people who they say they are, and will they show up." The About page is where that question is answered or lost.

Its outsized role in E-E-A-T. E-E-A-T (Experience, Expertise, Authoritativeness, Trust) is not a ranking factor and there is no E-E-A-T score in the algorithm; it is the framework describing what Google's systems are built to reward (see section 3, cited). The About page is where the most of it is demonstrated in one place: the real people (Experience and Expertise), the licenses and years and community standing (Authoritativeness), and the consistent, verifiable, honest identity signals (Trust, the member Google calls the most important of the four). Google's own people-first guidance points at the About page by name as a place to demonstrate who is behind a site (section 8, cited). A thin or faceless About page is the fastest way to tell both a human and a quality rater that there may be nobody real behind the business.

Its role for YMYL local businesses. Many local trades are YMYL (Your Money or Your Life): anything touching health (dental, medical, med-spa, chiropractic), safety (electrical, gas, roofing, garage doors), or finances and legal exposure (law firms, financial services, tax). For YMYL queries the trust bar is materially higher, and the About page carries more of the load, because the harm from trusting the wrong provider is greater. The page must show real credentials, real accountable people, and honest claims, not because "About pages rank," but because the whole site's trustworthiness is judged partly on whether a real, qualified, accountable operator stands behind it.

The governing principle. The first screen earns the scroll; it does not need to hold the whole argument. Establish who you are and that you are real and local in the fold, then let the origin, the team, the credentials, and the local proof unspool below, with the call to act repeated once the proof has landed.

---

## 2. Target intent: the About-page reader's five real questions

The reader is not searching a keyword. They typed the brand name, or clicked "About" from the homepage or a service page, or Googled "[business name] reviews" and landed here. They arrive with five questions, roughly in this order, and the page is built to answer each one in turn.

1. **Who are you, really?** Real names, real faces, a real owner. Not "our team of experts." The reader wants to see the human who will answer the phone or knock on the door.
2. **Can I trust you in my home / with my body / with my case?** Licensed, insured, background-checked, bonded. The specific proof that de-risks letting a stranger in.
3. **Are you actually local?** Do you know this city, these neighborhoods, this climate, these housing stocks, these soil and water problems. A local buyer wants a neighbor, not a call center in another state or a private-equity roll-up wearing a local name.
4. **Are you qualified for my specific problem?** Years in the trade, the exact license class, the certifications for my equipment or my situation, the master vs apprentice distinction.
5. **Will you actually show up and stand behind the work?** The guarantee, the warranty, the years in business that prove they did not vanish, the reviews that prove other neighbors got treated right.

A page that answers all five in the reader's own order converts. A page that opens with "Founded in 2014, we are a leading provider of quality solutions" answers none of them and burns the highest-attention screen. Every section in section 4 maps to one or more of these five questions; if a section answers none of them, cut it.

Note honestly: About traffic is mixed. Some are buyers, some are job-seekers, some are competitors doing recon, some are existing customers looking for a phone number. Build for the buyer, but keep the phone number and hours trivially findable for the existing customer.

---

## 3. 2026 E-E-A-T and entity reality (live, cited)

What is true in 2026, verified against primary sources this session:

**E-E-A-T is not a ranking factor, and neither is Person/author markup.** Google's structured-data policies state plainly that a structured-data manual action "doesn't affect how the page ranks in Google web search"; it only affects rich-result eligibility ([Google, Structured Data General Guidelines](https://developers.google.com/search/docs/appearance/structured-data/sd-policies)). E-E-A-T is a framework describing what Google's systems reward, not a dial in the algorithm. So the honest case for everything on this page is trust-and-conversion architecture plus entity hygiene, never "add this and you rank." Any file, competitor teardown, or client that says "Person schema boosts rankings" is wrong; correct it and cite this.

**Google names the About page as a Who/How/Why trust surface.** Google's "Creating helpful, reliable, people-first content" guidance asks site owners to self-assess with "Is it self-evident to your visitors who authored your content?" and "Do bylines lead to further information about the author or authors involved, giving background about them?" and explicitly recommends demonstrating authority "through links to an author page or a site's About page" ([Google, creating helpful content](https://developers.google.com/search/docs/fundamentals/creating-helpful-content)). The About page is the canonical answer to Google's own "Who" question. This is the strongest cited reason the page matters, and it is about trust, not a ranking lever.

**How real bios feed the Knowledge Graph and answer engines.** The About page is the canonical home for the business's Organization/LocalBusiness entity and the Person entities of its owner and key staff. Consistent, structured, verifiable facts here (legal name, founding year, founders, address, `sameAs` links to real off-site profiles) are how Google resolves the business as a stable entity and how AI answer engines (AI Overviews, ChatGPT, Perplexity, Claude) find a citable passage when a user asks "who is [business]" or "is [business] licensed." Per doctrine Law 13, share-of-answer is a first-class outcome: the About page is often the exact passage these engines lift for identity and trust queries, so its facts must be written as clean, self-contained, extractable sentences (section 9). But note honestly: LLM crawlers largely read rendered visible text, not your JSON-LD, so the entity win comes from the visible bios and facts first, schema second.

**ProfilePage exists and is for people/organizations.** Google supports `ProfilePage` structured data whose required `mainEntity` is a `Person` or `Organization`, with recommended `sameAs`, `image`, `description`, `dateCreated` ([Google, ProfilePage](https://developers.google.com/search/docs/appearance/structured-data/profile-page)). Google does not claim it affects ranking. Use `ProfilePage` on individual team-member bio pages where headcount warrants them; use `AboutPage` + `LocalBusiness` on the main About page (section 10).

**The one thing that changed the stakes.** With AI-generated faces and copy now cheap and everywhere, the buyer's 2026 default assumption is that a slick, faceless, stock-photo team block might be fake. The counter is not more polish; it is verifiable specificity: a real license number a reader can look up on the state board, a real owner whose name is on the truck, a real address with a real Google Business Profile, real reviews on a third-party platform. Verifiability is the moat, and it is exactly the E-E-A-T surface a fully hands-off content pipeline cannot fake (doctrine Law 8).

---

## 4. Section-by-section architecture

Build in narrative order: Hero -> Origin -> Team bios -> Credentials/licenses/insurance -> Local roots and community -> Proof -> Values/promise -> CTA. Each section below gives: what it must contain, the named framework, the local-SEO requirement, the schema requirement, a real-example precedent, the anti-pattern, and a PASS test the QA gate checks.

### 4.1 Hero: who you are, that you are real, and that you are local

- **Must contain.** One line naming who you are, what you do, and for which city, plus the two trust anchors a local buyer scans for first: how long you have served the area and that you are local and family-owned (if true). Example shape: "[Name] has kept [City] homes dry since 1991. Family-owned, licensed, and still answering our own phones." A real photo of the actual owner or crew in the fold, not a stock handshake.
- **Framework.** StoryBrand identity-first opening (Donald Miller), scoped: the About page is the one page where the visitor genuinely came for company facts, so the hero legitimately states who you are rather than withholding it. Structural, not A/B-proven.
- **Local-SEO requirement.** The H1 is real server-rendered text and retains the entity plus the primary city: "About [Business Name], [City]'s [trade] since [year]." This is the most weighted heading an answer engine reads for "who is [business]." Never bake it into an image.
- **Schema requirement.** `AboutPage` wrapping the page; `LocalBusiness` (correct subtype) as the entity, matching `brand.yaml` `schema.local_business_type`.
- **Precedent (live 2026-07-20).** Chambliss Plumbing leads on family plus tenure ("founded in 1991 by Kevin and Kathy Chambliss," "over 30 years") ([chamblissplumbing.com/about-us](https://www.chamblissplumbing.com/about-us/)).
- **Anti-pattern.** "Welcome to our website." "Founded in 2014, we are a leading provider of quality plumbing solutions." A stock photo of a smiling model in a clean uniform holding a wrench.
- **PASS test.** Does the first screen answer questions 1 and 3 (who are you, are you local) with a real name, a real year, and the city, in server-rendered text, with a real photo? If any is missing or stock, FAIL.

### 4.2 Origin: the earned-competence story, specific and falsifiable

- **Must contain.** A compressed arc built on the earned-competence path: the specific gap the owner watched happen in local homes or the specific trade the owner earned, the moment that made them start the business, and what the customer gets because of it. A real, checkable detail: the year, the first truck, the trade the founder came up in, the specific local problem they kept seeing. One idea per paragraph.
- **Framework.** Earned-competence origin (this playbook's local adaptation of the About-page origin rule). Falsifiability is the test: "I spent eleven years as a master plumber watching builders in this county pour 1980s slabs that crack and leak, and I started this company to fix them right" is checkable (the tenure, the license, the local pattern). Passion is unfalsifiable and trust-neutral. Never force a fake "we built it for ourselves" story onto a service business; a borrowed origin reads false faster than an honest plain one.
- **Local-SEO requirement.** Weave the real place into the origin: the neighborhood, the county, the housing stock, the local climate or soil or water problem the business exists to handle. This is unique, locally specific content no competitor can copy because it is literally their story, and it is exactly the specificity that makes the page read human (doctrine Law 8).
- **Schema requirement.** `foundingDate` (from `brand.yaml` `client.founded_year`) and `founder` (Person) on the LocalBusiness/Organization node, matching the visible year and name exactly.
- **Precedent.** ABC Home & Commercial runs a real earned-legacy origin: bought by the Jenkins family in 1965, grown from one technician, territory split among three sons by dividing a map of Texas into thirds ([abchomeandcommercial.com/austin/about](https://www.abchomeandcommercial.com/austin/about); family detail corroborated via [AgriLife Today](https://agrilifetoday.tamu.edu/2024/04/02/the-abcs-of-community-began-at-texas-am-for-jenkins/)). Specific, dated, human, uncopyable.
- **Anti-pattern.** The milestone timeline ("2016: second truck. 2019: new office"). "The founders shared a lifelong passion for exceptional service." A 300-word lore wall with no year, no name, no place.
- **PASS test.** Is there one real, checkable detail (a year, a named trade or license, a specific local problem) and a real friction moment that explains why the business exists? Could a reader in this city verify at least one fact in it? If it is all sentiment and no specifics, FAIL.

### 4.3 Team bios: real, named humans with a credibility hook and one human detail

- **Must contain.** Each key person gets: a real headshot shot in context (not stock, not an undisclosed AI face), a real name, a precise role tied to what they are accountable for ("Master Plumber, license MPL 12345, runs every gas job"), years in the trade, one hard credibility hook (a license class, a certification, a named outcome or number), and exactly one non-work human detail (coaches the local little-league team, third-generation [City] native, drives the truck you have seen around [neighborhood]). One human detail, not a paragraph.
- **Framework.** Inverted-pyramid bio, conditional by vertical. For YMYL and high-trust trades (electrical, gas, roofing, dental, legal, anything the buyer is about to trust with safety or money), lead with the hardest-to-doubt credential; the buyer needs zero guessing. The single human detail earns the felt connection that the credential cannot. Both halves are required.
- **Local-SEO requirement.** Names and roles are real rendered text (extractable for entity resolution), not baked into a team-photo graphic. Where the business is small (under ~15 people), show the whole crew; the "last name on the side of the truck" is the single strongest local-trust signal a home-services business has, so use it.
- **Schema requirement.** Each named person is a `Person` node (name, jobTitle, and `sameAs` to a real LinkedIn or state-license page if one exists), attached to the LocalBusiness via `employee` / `founder`. On a larger team, give each key person their own bio page typed `ProfilePage` with `mainEntity` Person. Headshots ship with descriptive alt text carrying the person's name, explicit width/height (no layout shift), a next-gen format, and lazy-loading below the fold.
- **Precedent.** Chambliss binds real founders (Kevin and Kathy Chambliss) and states the team is background-checked before hiring, licensed, bonded, insured, and in-house trained ([chamblissplumbing.com/about-us](https://www.chamblissplumbing.com/about-us/)). ABC names the owner (Bobby Jenkins) with real biography and community roles ([abchomeandcommercial.com/austin/about](https://www.abchomeandcommercial.com/austin/about)).
- **Anti-pattern.** A stock-photo team block. "Our team of dedicated professionals." Initials-only cards. A grid where every card says "Technician" with no name and no face. All-personality cards with a favorite pizza topping and zero credential. Undisclosed AI-generated faces of people who do not exist (trust-poison and a likeness/deception exposure).
- **PASS test.** Does every card carry a real name, a real in-context photo, a role, one hard credential or number, and exactly one human detail? Are names in rendered text? Zero stock or undisclosed-synthetic faces? If any card is faceless, nameless, or stock, FAIL.

### 4.4 Credentials, licenses, insurance, certifications: the de-risking block

- **Must contain.** The specific, checkable trust proofs: license type and number (where the trade and state make it public), "bonded and insured" with the real coverage, background-check policy, manufacturer and trade certifications (the exact brands and programs, e.g. Rinnai and Rheem certified, NATE-certified HVAC tech, board-certified, bar admission and year), memberships (BBB accreditation, local trade association). Real numbers where public.
- **Framework.** Verifiability-first trust. A linked or numbered credential is evidence; an unlinked adjective ("fully licensed") is an assertion. This block converts "trust me" into "here is the number, go check."
- **Local-SEO requirement.** Render the license number as visible text a reader can copy into the state board's lookup. This is the single most powerful trust artifact a regulated local trade has, and it is exactly what a fake or low-effort competitor cannot show. Do not put it only in an image.
- **Schema requirement.** Certifications and licenses can be expressed as `hasCredential` on the Person or `Organization`; membership as `memberOf`. Only mark up what is visibly rendered and true. Match every number to the visible number exactly.
- **Precedent.** Chambliss displays license MPL 46504, BBB accreditation, and named manufacturer partnerships (Rinnai, Rheem, Kohler, Delta, Moen), plus a stated background-check-before-hire policy ([chamblissplumbing.com/about-us](https://www.chamblissplumbing.com/about-us/)). ABC lists "licensed entomologists, electricians, AC technicians, plumbers," BBB A+ rating, and a Certified QualityPro designation ([abchomeandcommercial.com/austin/about](https://www.abchomeandcommercial.com/austin/about)).
- **Anti-pattern.** "Licensed and insured" with no number, no carrier, no verifiable specifics. Claiming a certification the business does not hold (fraud and a trust-penalty landmine). A generic trust-badge row of unearned logos.
- **PASS test.** For every credential claimed, is there a checkable specific (a license number, a named certification program, a real membership)? Is every one true and confirmed in `brand.yaml` `eeat.credentials`? A fabricated or unverifiable credential is an automatic FAIL and a hard-line violation (section 7).

### 4.5 Local roots and community involvement

- **Must contain.** Proof the business is genuinely of this place: how many years in this specific city, the neighborhoods and areas actually served, the local knowledge (the soil, the water hardness, the storm season, the housing stock, the permit office they deal with weekly), and real community involvement (sponsors the local youth team, member of the chamber, third-generation local, hires locally, disaster-response work after the last storm).
- **Framework.** Positioning-by-locality. For a local buyer choosing between a neighbor and a private-equity roll-up wearing a local name, "actually local" is the differentiator. A brand rooted in a named place is legible; a brand for everywhere is wallpaper.
- **Local-SEO requirement.** Name real places and real local specifics (real neighborhoods, real local conditions), consistent with the service-area and location pages. This is genuine E-E-A-T Experience: it shows first-hand knowledge of the actual place. Never invent coverage; use only the real `brand.yaml` `service_areas`. NAP must be byte-identical to the Google Business Profile.
- **Schema requirement.** `LocalBusiness` `address`, `areaServed`, and `geo` matching `brand.yaml` `nap`. Community memberships as `memberOf` where real.
- **Precedent.** ABC leans hard on being "locally owned and operated" against private-equity-bought competitors, and the owner's real civic roles (past chair of the Austin Chamber of Commerce, American Heart Association and United Way board roles) ([abchomeandcommercial.com/austin/about](https://www.abchomeandcommercial.com/austin/about)). Chambliss uses a Nextdoor "Neighborhood Favorite" award as a local-belonging proof ([chamblissplumbing.com/about-us](https://www.chamblissplumbing.com/about-us/)).
- **Anti-pattern.** "Proudly serving the greater [region] area and beyond" with no named place. "Nestled in the heart of [City]" (a blocklisted phrase, and empty). Inflated coverage listing cities the business does not actually serve (a doorway-adjacent trust risk).
- **PASS test.** Does the section name at least one real neighborhood or local specific and one real community tie, both drawn from `brand.yaml` or the SME interview, with NAP matching GBP? Generic "serving your area" with no named place FAILS.

### 4.6 Proof: reviews, awards, real projects, guarantees

- **Must contain.** A cluster of hard, verifiable social proof placed near the decision point: real review count and platform (with the rating), named awards with years, real completed local projects (the kind of job, the neighborhood, the outcome), and the guarantee or warranty stated concretely. Curated and credible beats maximal: one real "4.9 from 600+ Google reviews" beats a wall of unearned badges.
- **Framework.** Proof-at-the-decision-point plus the Von Restorff isolation effect (Hedwig von Restorff, 1933): a small set of isolated, specific proofs reads believable; a wall of forty vague badges reads laundered.
- **Local-SEO requirement.** Point to third-party-verifiable proof a skeptic could check (the live Google or Facebook review profile, the real BBB page, the real award). A screenshot is illustration, not proof. Reviews shown on-page must not fabricate counts and must respect reviewer privacy (`brand.yaml` `guardrails.review_pii_rule`: no full name or identifying detail without consent).
- **Schema requirement.** The one valid review pattern: genuinely client-authored testimonials, visibly rendered, marked up with the client as `author` and the service as `itemReviewed`. Reserve `AggregateRating` for real third-party UGC (a genuine Google or BBB rating with its real count). Never self-rate your own Organization with an invented `aggregateRating` and `reviewCount` (a manual-action trap and a policy violation, section 8).
- **Precedent.** Chambliss stacks dated, named awards (Best Plumbers in San Antonio 2016-2022, Pulse of the City, Nextdoor Neighborhood Favorite 2022) and a BBB accreditation ([chamblissplumbing.com/about-us](https://www.chamblissplumbing.com/about-us/)). ABC uses "Best of Austin Chronicle 2022" and BBB A+ ([abchomeandcommercial.com/austin/about](https://www.abchomeandcommercial.com/austin/about)).
- **Anti-pattern.** "Over 10,000 satisfied customers" with no source. A carousel of adjective-only testimonials ("Great service! Highly recommend!") with no name or specifics. Self-asserted five-star schema. Inflated or unverifiable numbers that trip the skeptical reader the page is built for.
- **PASS test.** Is every proof number real, sourced, and confirmed in `brand.yaml` `eeat.proof`? Is there at least one third-party-verifiable proof (a real review profile, a real award, a real BBB page)? Is any review schema client-authored, never self-rated? A fabricated count or a self-`AggregateRating` FAILS.

### 4.7 Values / the promise: behavioral and falsifiable

- **Must contain.** A short set of values defined by an action the business can be publicly caught not doing, and a concrete promise (the guarantee, the "we answer our own phones," the "flat-rate pricing you see before we start," the "we clean up before we leave"). At least one value should admit a cost or a standard that is inconvenient to hold.
- **Framework.** Lencioni's values filter (Patrick Lencioni, "Make Your Values Mean Something," HBR 2002): publish only Core, behaviorally-defined values; the inversion litmus is that if the opposite is absurd ("we value low quality"), it is a permission-to-play value, not a differentiator. Leading with "Integrity / Excellence" fails automatically.
- **Local-SEO requirement.** Render the promise as a clean, self-contained sentence an answer engine can lift for "does [business] guarantee their work." A specific, falsifiable promise is a distinctive entity fact; a platitude is not.
- **Schema requirement.** None specific; if the guarantee is a formal warranty, it can be described in the service/offer schema on the relevant service page, not invented here.
- **Precedent.** Chambliss states a behavioral standard tied to an action (background checks before hire; optional masks, gloves, and booties inside the home) rather than a platitude ([chamblissplumbing.com/about-us](https://www.chamblissplumbing.com/about-us/)).
- **Anti-pattern.** A wall of abstract nouns (Integrity, Quality, Innovation, Excellence). A promise with no mechanism ("we care about your satisfaction"). For regulated trades, a result guarantee that violates the vertical's advertising rules (section 8).
- **PASS test.** Is each value defined by a checkable action, and is the promise concrete and specific? Could a competitor paste the values block onto their own site unchanged? If yes, FAIL and rewrite.

### 4.8 CTA: the next step, repeated after proof

- **Must contain.** One primary next step (call now / book online / request a quote) visible in the fold and repeated at the natural scroll-stop after the proof block. On mobile, a `tel:` click-to-call is the high-intent path for emergency trades. Not a dead end after the team grid, not five co-equal buttons.
- **Framework.** Trust-then-ask sequencing. The repeat CTA begins only after the proof has landed, so it never reintroduces a hard ask on a still-cold reader mid-story.
- **Local-SEO requirement.** The phone number matches NAP exactly. The CTA is a real button/link at WCAG-AA contrast with a real `tel:` action on mobile.
- **Schema requirement.** `telephone` on the LocalBusiness node matching the visible, NAP-consistent number.
- **Precedent.** Home-services best practice: the emergency phone number pinned top and bottom (the pattern across the reviewed home-service sites).
- **Anti-pattern.** An About page that dead-ends after the team photos with no next step. A generic "Contact us" mailto as the only path. An aggressive "BOOK NOW" injected into the middle of the origin story before any trust is built.
- **PASS test.** Is there one primary CTA in the fold and one after the proof, with a NAP-matching `tel:` on mobile? If the page dead-ends or the number mismatches NAP, FAIL.

---

## 5. Best-in-class teardowns (real, read live 2026-07-20)

Two real local-service About pages, read live this session. Pull them fresh before citing; live pages change. Neither was A/B-tested; the lesson is the construction, not a proven conversion number.

**Chambliss Plumbing Company, San Antonio ([chamblissplumbing.com/about-us](https://www.chamblissplumbing.com/about-us/)).** Why it builds trust: it front-loads the two things a local buyer scans for (real founders Kevin and Kathy Chambliss, and "over 30 years," founded 1991) and then stacks verifiable, checkable proof rather than adjectives. The master plumber license number (MPL 46504) is on the page, which a homeowner can verify with the Texas state board in thirty seconds. "Licensed, bonded, insured," background-checked-before-hire, and in-house-trained answers the "can I trust a stranger in my home" question directly. The awards are dated and named (Best Plumbers in San Antonio 2016 through 2022, Nextdoor Neighborhood Favorite 2022), and the Nextdoor award specifically signals neighborhood belonging. Named manufacturer partnerships (Rinnai, Rheem, Kohler, Delta, Moen) show real trade depth. The human detail (optional masks, gloves, and booties inside the home) is a small, concrete, un-fakeable promise. Weakness to beat: the values language leans on "respect and integrity," which is closer to permission-to-play than to a falsifiable differentiator; the page would be stronger with one more behavioral, cost-admitting value.

**ABC Home & Commercial Services, Austin ([abchomeandcommercial.com/austin/about](https://www.abchomeandcommercial.com/austin/about)).** Why it builds trust: it wins the "are you actually local" question decisively by positioning explicitly against private-equity-bought competitors ("locally owned and operated," family-owned since the Jenkins family bought it in 1965) at a moment when local buyers are wary of national roll-ups wearing local names. The named owner (Bobby Jenkins) carries real, checkable civic authority (past chair of the Austin Chamber of Commerce, board roles with the American Heart Association and United Way), which is genuine local Authoritativeness. The scale proof is honest and specific ("over 900 people," 75 years, real named metro areas). Credentials are specific to the trade ("licensed entomologists, electricians, AC technicians, plumbers"), and the awards are named and dated (Best of Austin Chronicle 2022, BBB A+, Certified QualityPro). The family-history detail (the map of Texas divided into thirds among three sons) is uncopyable because it is literally true only for them. Lesson: local-belonging plus a real, civically-active named owner is a moat a national competitor structurally cannot copy.

The shared pattern both prove: real names plus real numbers plus real local roots. Neither leans on stock photography or adjective walls. Both give the skeptic something to check.

---

## 6. Worst teardowns (the generic pattern, and why it fails E-E-A-T)

The failure mode is not one specific bad business; it is a template that thousands of low-effort contractor sites ship from the same site-builder themes. Rather than pillory a single small business by name, here is the archetypal generic About page and exactly why each move fails, so the QA gate can catch it. These patterns are ubiquitous and verifiable across cheap template sites in every trade.

**The "we are passionate about excellence" page.** Opens with "Welcome to [Business]. We are passionate about providing exceptional service to our valued customers." Fails question 1 (who are you): there is no name, no owner, no face. It could be any business in any trade in any city. An answer engine asked "who is [business]" finds nothing citable; a quality rater finds no evidence a real, accountable operator exists.

**The faceless / stock team block.** A grid of smiling models in clean uniforms, or "Our team of dedicated professionals is here for you," with zero real names or real faces. In 2026 this reads as possibly fake by default. It fails the entire E-E-A-T Experience and Expertise axis because there is no verifiable human behind any claim. For a business asking to enter a home, facelessness reads as hiding.

**"Licensed and insured" with no number.** The single most common trust-adjective in the trades, and near-worthless: any site can type it, including an unlicensed operator. It fails the verifiability test that separates a real regulated business from a fraud. The fix is one license number.

**The milestone-timeline or lore-wall origin.** Either "2014: founded. 2016: second location," which answers a question no buyer asked, or a 300-word passion-and-dedication wall with no year, no name, no place. Both fail because neither is falsifiable and neither shows first-hand local experience.

**The inflated-coverage / inflated-number page.** "Serving the entire tri-state area, over 10,000 happy customers," with no source and coverage the business cannot actually deliver. This fails Trust (the most important E-E-A-T member) on sight for a skeptical reader, and the inflated coverage edges toward a doorway-page trust risk.

**The values-noun wall.** "Integrity. Quality. Innovation. Excellence." Every one is a permission-to-play value whose opposite is absurd; none is a differentiator; a competitor could paste the whole block unchanged. Fails the Lencioni inversion litmus and the mask test.

Why these fail as a group: none gives a human or a machine anything real to verify. E-E-A-T rewards demonstrated experience, real expertise, real authority, and honest, consistent identity. The generic page demonstrates none of it, so it signals, to both a skeptical buyer and a quality rater, that there may be nobody real and accountable behind the business.

---

## 7. The E-E-A-T proof section: what to pull and how to render it

This is the operational heart of the page. Every real specific comes from two places: the client's `brand.yaml` (`eeat:` block) and the SME interview. Nothing is invented. Map each field to a section:

| Source (brand.yaml `eeat:` or NAP) | Renders in section | How to render it |
|---|---|---|
| `client.founded_year`, `client.legal_name`, `eeat.differentiators` | Hero + Origin (4.1, 4.2) | Real founding year and the real earned-competence story from the SME interview. `founder` in schema. |
| `eeat.team` (name, role, years, one detail) | Team bios (4.3) | One card per real person: name, role, years, one hard credential, exactly one human detail. `Person` nodes. |
| `eeat.credentials` (licenses, certs, insurance, memberships, numbers) | Credentials block (4.4) | License numbers as visible copyable text; named cert programs; real memberships. `hasCredential` / `memberOf`. |
| `nap` + `service_areas` + `primary_city` + `eeat.differentiators` | Local roots (4.5) | Real neighborhoods, real local conditions, real community ties. NAP byte-identical to GBP. `address` / `areaServed`. |
| `eeat.proof` (review counts + platforms, awards, guarantees, projects) | Proof block (4.6) | Real counts with platform and rating; dated named awards; real projects. Third-party-verifiable. Client-authored `Review` only. |
| `eeat.differentiators` + SME promise | Values / promise (4.7) | Behavioral, falsifiable values; one concrete promise as a clean sentence. |

The SME interview questions that feed this page (ask when `brand.yaml` is thin):
- Who owns and runs this business, and who will the customer actually meet? (names, roles, years, license classes)
- What is the one real story of why you started this, and what specific local problem were you fixing? (origin)
- What is your exact license type and number, your insurance, your certifications, and your background-check policy?
- How many years in this specific city, which neighborhoods do you actually serve, and what do you know about this place that an out-of-town competitor does not?
- What is your real review count and rating, on which platform, and which real awards have you won and when?
- What do you promise and guarantee, in concrete terms, that you can be held to?
- One human detail per key person the customer would find relatable.

**The hard rule (non-negotiable, doctrine Law 8 and the CLAUDE.md no-fabricated-facts rule).** Never fabricate a credential, a license number, a team member, a review count, an award, a certification, or a year. If a fact is not in `brand.yaml` and not confirmed by the SME, it does not go on the page; it becomes an SME question. A fabricated license number or invented team member is not a copy weakness, it is a fraud and a trust-penalty landmine that can end a client relationship. When a field is blank and unconfirmed, the page ships without that claim and the gap is flagged, never guessed. "Family-owned since 1998" is worthless and risky unless the specifics that prove it are real and present.

---

## 8. Google-compliance and YMYL notes

- **Structured data marks up only visible, true content.** Google's policy: "Don't mark up content that is not visible to readers of the page," and do not use structured data to deceive or impersonate ([Google, structured-data policies](https://developers.google.com/search/docs/appearance/structured-data/sd-policies)). Every `Person`, credential, and number in JSON-LD must appear and verify on the page. A violation risks a manual action that removes rich-result eligibility (it does not lower ranking, but it removes eligibility site-wide).
- **Author/Person markup is not a ranking lever.** Do not sell it as one internally or to the client. It is entity hygiene and feature eligibility. The honest justification is trust, entity resolution, and answer-engine identity clarity.
- **Validate.** Use Google's Rich Results Test and the schema.org validator (the old Structured Data Testing Tool is deprecated). Note that a non-eligible type may return "no items detected" in the Rich Results Test; that is expected, not a break. Validate LocalBusiness against the [LocalBusiness doc](https://developers.google.com/search/docs/appearance/structured-data/local-business).
- **YMYL trades carry a higher trust bar.** For health (dental, medical, med-spa, chiropractic), safety (electrical, gas, roofing, garage doors), and money/legal (law, tax, financial), the real credentials and real accountable people are load-bearing, and honesty is enforced harder. Show real board certifications, real license numbers, real bar admissions.
- **Regulated-vertical advertising limits.** Legal (ABA Model Rule 7.1 and state analogues), medical/dental (state boards plus FTC substantiation), and financial (SEC/FINRA) constrain outcome and performance claims. A falsifiable result promise, which section 4.7 otherwise encourages, is a presumptive violation for a law firm or a medical practice. On a regulated About page, use process and access promises, not result guarantees, and route any guarantee copy through a compliance read. This is a hard gate.
- **Testimonial and claim substantiation (FTC).** Under the FTC Rule on reviews and testimonials (16 CFR Part 465, in force since 2024), no fabricated, AI-generated, or undisclosed-paid testimonials; every quantified claim substantiated on file; no self-serving `Review`/`AggregateRating` markup on your own Organization. Any performance figure next to a named person must be substantiable and cleared against any client NDA.
- **Employee consent and privacy.** Get documented consent before publishing any employee's face, name, and bio. Ship a removal process and a maintenance cadence so the page never shows departed staff (a stale team page is a trust killer and, where you attribute current claims to a departed person, a misrepresentation). Use a role-based contact path for non-leadership rather than publishing every junior staffer's direct line.
- **Synthetic imagery.** No stock faces presented as your team and no undisclosed AI-generated faces of fictional people. AI headshot tooling is legitimate only to normalize background, lighting, and grade of a real, named employee's genuine photo, with their sign-off, never to alter features or invent a person. The person who arrives at the door must match the grid.
- **Accessibility (WCAG 2.2 AA).** 4.5:1 contrast on normal text and the CTA label; do not hide bio content behind hover-only (invisible on touch, and implicates SC 1.4.13 and 2.1.1 at AA); name-bearing alt text on headshots; respect `prefers-reduced-motion`.
- **Terminology hygiene.** Cite Google's guidance by its current title, "Creating helpful, reliable, people-first content," not the retired "Helpful Content System" branding.

---

## 9. Voice and humanization notes (the page where voice matters most)

The About page is the one page written in the owner's own voice, because it is the one page about the owner. Load `knowledge/voice/humanization-layer.md` and the client's `brand.yaml` `voice:` block before drafting. The two layers stack: universal humanization (kill AI tells, vary rhythm) plus the per-client voice (`one_line_direction`, `tone_by_context.about`, `banned_phrases`, `good_examples`).

- **Substance first, craft second (doctrine Law 8).** The page reads human because it is made of real names, real numbers, a real local story, and a real promise, not because it was run through any humanizer. If a paragraph reads like AI, the first fix is a missing specific, not a swapped word. No detector-evasion, no "passes AI detection" step, ever (Hard Line 5).
- **Sound like the owner answering the phone.** For most trades the target is a warm, plain, slightly imperfect first-person voice ("I started this company because..."), not polished corporate marketing. Contractions, short paragraphs, one idea per sentence where it earns it.
- **Blocklist is strict here.** "Nestled in the heart of," "your trusted partner," "we are passionate about excellence," "committed to exceeding expectations," "when it comes to your [trade] needs," "team of dedicated professionals" are all Tier-1 tells and all empty. Every hit gets rewritten with a real specific, not swapped for a synonym.
- **The mask test (Ann Handley).** Cover the logo. If the About page is indistinguishable from the three closest local competitors', the voice failed. The fix is more real specifics (the real story, the real names, the real local details), which is exactly what competitors cannot copy.
- **Write facts as extractable sentences (doctrine Law 13).** "who founded it," "what year," "what license," "which city," "what guarantee" each as a clean, self-contained sentence an answer engine can lift verbatim. Test by asking an AI engine "who is [business]" and checking it can answer correctly from the page text.

---

## 10. Meta formulas and JSON-LD

**Meta title formulas** (keep under ~60 chars, entity plus city):
- `About [Business Name] | [City]'s [Trade] Since [Year]`
- `Meet the [Business Name] Team | [Trade] in [City], [ST]`
- `About Us | Family-Owned [Trade] in [City] | [Business Name]`

**Meta description formula** (~150 chars, real specifics, one trust anchor plus one human anchor):
- `Family-owned [trade] serving [City] since [year]. Licensed ([license #]), insured, [N]+ [platform] reviews. Meet the [name] family and crew.`

**JSON-LD: AboutPage + LocalBusiness + Person.** The main About page uses `AboutPage` as the page type and the LocalBusiness (correct subtype from `brand.yaml`) as the entity, with founder and key staff as `Person` nodes. Validate with the Rich Results Test and schema.org validator; every value must match the visible page and `brand.yaml` exactly. Skeleton (fill from `brand.yaml`, never invent a field):

```json
{
  "@context": "https://schema.org",
  "@type": "AboutPage",
  "url": "https://example.com/about",
  "mainEntity": {
    "@type": "Plumber",
    "@id": "https://example.com/#business",
    "name": "Chambliss-style Example Plumbing",
    "foundingDate": "1991",
    "founder": [
      { "@type": "Person", "name": "Owner Name", "jobTitle": "Master Plumber" }
    ],
    "telephone": "+1-210-555-0123",
    "priceRange": "$$",
    "address": {
      "@type": "PostalAddress",
      "streetAddress": "1875 Example Dr",
      "addressLocality": "San Antonio",
      "addressRegion": "TX",
      "postalCode": "78260",
      "addressCountry": "US"
    },
    "geo": { "@type": "GeoCoordinates", "latitude": "29.6", "longitude": "-98.4" },
    "areaServed": [ { "@type": "City", "name": "San Antonio" } ],
    "employee": [
      {
        "@type": "Person",
        "name": "Master Tech Name",
        "jobTitle": "Master Plumber",
        "hasCredential": {
          "@type": "EducationalOccupationalCredential",
          "credentialCategory": "license",
          "identifier": "MPL 46504"
        },
        "sameAs": ["https://www.linkedin.com/in/real-profile"]
      }
    ],
    "memberOf": { "@type": "Organization", "name": "Better Business Bureau" },
    "sameAs": [
      "https://www.google.com/maps/place/real-gbp",
      "https://www.facebook.com/real-page"
    ]
  }
}
```

**Per-person bio pages (larger teams):** type the page `ProfilePage` with `mainEntity` a `Person` carrying `name`, `jobTitle`, `image`, `description`, `hasCredential`, and `sameAs` to real off-site profiles ([Google ProfilePage](https://developers.google.com/search/docs/appearance/structured-data/profile-page)). Only mark up people, credentials, and numbers that are visibly rendered and true. `sameAs` links must resolve to profiles that actually exist; build or omit, never fabricate.

---

## 11. Finished-page checklist

The page is not done until every line passes. This is the QA gate `/qa` runs; every fail returns a specific error, fix and re-run.

Structure and trust:
- [ ] Hero answers who/what/city with a real name, real year, and a real photo (not stock), in server-rendered text.
- [ ] Origin is the earned-competence path with one checkable local specific and a real friction moment. No fake "we built it for ourselves," no milestone timeline.
- [ ] Every team card: real name, real in-context photo, role, one hard credential, exactly one human detail. Zero stock or undisclosed-synthetic faces. Names in rendered text.
- [ ] Credentials block shows checkable specifics (license number as copyable text, named certs, real memberships), all confirmed in `brand.yaml`.
- [ ] Local-roots section names at least one real neighborhood/local specific and one real community tie; NAP byte-identical to GBP; no inflated coverage.
- [ ] Proof block: real sourced counts and dated named awards; at least one third-party-verifiable proof; reviewer PII respected.
- [ ] Values are behavioral and falsifiable (pass the Lencioni inversion and mask tests); the promise is one concrete sentence.
- [ ] One primary CTA in the fold and one after proof; `tel:` on mobile matching NAP.

Compliance and integrity (hard gates):
- [ ] No fabricated credential, license number, team member, review count, award, or year. Every claim traces to `brand.yaml` or the SME.
- [ ] JSON-LD marks up only visible, true content; every schema number matches the visible number; no self-`Review`/`AggregateRating`; `sameAs` links all resolve. Validated in Rich Results Test + schema.org validator.
- [ ] Regulated vertical (legal/medical/dental/financial): no result guarantees; process/access promises only; compliance read done.
- [ ] Documented employee consent on file; removal process and maintenance cadence set; no departed staff shown; role-based contact for non-leadership.
- [ ] WCAG 2.2 AA: contrast on text and CTA, no hover-only bios, name-bearing alt text, reduced-motion respected.

Voice and answer-engine readiness:
- [ ] Passes the mask test against the three closest local competitors.
- [ ] Vocabulary blocklist scan clean (no "passionate about excellence," "nestled in the heart of," "trusted partner," "team of dedicated professionals").
- [ ] An AI engine asked "who is [business]" can answer correctly from the page text (extractable identity sentences present).
- [ ] Zero em dash (U+2014). Voice matches `brand.yaml` `voice:` block.

Output contract (per CLAUDE.md): the finished package is `page.md`, `schema.json` (validated), `internal-links.md`, `compliance-report.md`, and `sources.md`, written to `output/<client>/about/`. A draft with no compliance report is an unfinished draft.

---

## Sources read live (2026-07-20)

- [Google, Structured Data General Guidelines / policies](https://developers.google.com/search/docs/appearance/structured-data/sd-policies) - visible-content rule, manual action does not affect ranking.
- [Google, Creating helpful, reliable, people-first content](https://developers.google.com/search/docs/fundamentals/creating-helpful-content) - the Who/How/Why self-assessment and the named recommendation to demonstrate authority via an About page.
- [Google, ProfilePage structured data](https://developers.google.com/search/docs/appearance/structured-data/profile-page) - required `mainEntity` Person/Organization, recommended properties, no ranking claim.
- [Google, LocalBusiness structured data](https://developers.google.com/search/docs/appearance/structured-data/local-business) - LocalBusiness subtype markup.
- [Chambliss Plumbing, About](https://www.chamblissplumbing.com/about-us/) - live best-in-class local teardown (founded 1991, license MPL 46504, dated awards, family + team proof).
- [ABC Home & Commercial, Austin About](https://www.abchomeandcommercial.com/austin/about) - live best-in-class local teardown (family-owned since 1965, named owner with civic authority, local-vs-PE positioning).

Every benchmark in this file is directional. No live A/B test was run. Re-verify the two teardowns and the Google docs before quoting externally; Google's guidance and live pages both drift.
