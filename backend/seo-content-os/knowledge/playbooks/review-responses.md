# Review Responses - Deep Playbook

**Artifact:** the owner's public reply to a customer review (Google, Yelp, Facebook, BBB, Angi). Not a web page - a short, public, permanent piece of copy written in the business owner's voice and posted under the review. A batch of these is a genuine content deliverable: 89% of consumers expect a business to respond to reviews, and the response text becomes part of the review corpus Google reads to understand the business.

**Command:** `/write-review-responses`. Load order per `CLAUDE.md`: doctrine -> google-compliance-spine -> `foundations/review-content-strategy.md` -> `foundations/local-gbp-signals.md` -> this playbook -> voice -> client `brand.yaml`.

**The one governing fact.** A review response has two readers and both are permanent. The first is the reviewer, who wants to feel heard. The second, and the larger one, is every future prospect reading the reviews before they buy, plus the search engine reading the text. A good response is written for the second reader while sounding like it was written only for the first. It reassures the prospect, corroborates the entity (real service, real place, real outcome), and never once reads like a template or a keyword play. The failure mode is copy-paste sameness: forty reviews answered with the same three sentences, or every reply stuffed with "best plumber in Austin." Both are visible to humans and discounted by the engine.

**Reading contract.** This playbook does not fabricate. A response never invents a detail the review does not contain, never claims an outcome that did not happen, never names a person or address the reviewer did not disclose, and never manufactures a fact to insert a keyword. Every response is grounded in the actual review text and `brand.yaml` voice. This is Law 8 (real value, not proxy-gaming) and Law 16 (experience shown, not asserted) and Law 20 (no fabricated proof). Numbers cited below are directional priors from the sources named inline; re-verify before quoting to a client.

---

## 1. Why response copy is a real content asset

Three evidence threads make response copy worth writing well, not dashing off:

1. **Consumers expect it, and read it.** BrightLocal's Local Consumer Review Survey: 89% of consumers expect businesses to respond to both positive and negative reviews; 41% now "always" read reviews (up from 29%), only 4% never do (https://www.brightlocal.com/research/local-consumer-review-survey/, fetched 2026-07-20 PKT). A visible, human, specific response is itself a trust signal to the next prospect.
2. **The response text feeds the review corpus.** Sterling Sky's near-me study found Google relies on review *content* to understand business offerings, and reviews with text rank stronger (https://www.sterlingsky.ca/what-gets-you-ranking-for-near-me-2025/). The owner's reply is additional text under the review; when it naturally names the real service performed and the real place, it corroborates relevance. When it stuffs keywords, it is spam.
3. **Responded-to reviews correlate with top-3 map performance.** LocalFalcon's GBP field guide lists steady, responded-to reviews among the profile signals tied to ranking performance (https://www.localfalcon.com/blog/what-information-impacts-your-google-business-profile-ranking). Correlation, not causation - but the direction is consistent across sources.

The honest limit: responding does not directly move rank the way a fresh reviewed *review* does. Its value is trust, corroboration, and profile activity. Sell it as that, never as a direct ranking lever.

---

## 2. The three response types, and the different job each does

### 2.1 Positive review response

The job: reinforce the specific praise, corroborate the entity, and leave the next prospect more confident. Not "Thanks for the 5 stars!" forty times.

**Structure (4 beats, ~40-80 words):**
1. **Thank, by name if the reviewer used a first name** (never add a name they did not disclose). "Thanks, Marcus."
2. **Reflect the specific thing they praised**, in the owner's words, which naturally surfaces the real service and often the real place. "Glad the crew got the water heater swapped the same morning you called."
3. **A genuine human beat** - a small, true detail or warmth. "Cold showers are no way to start a week."
4. **A soft forward-looking close.** "We're here if anything ever acts up again."

**What this does for SEO without stuffing:** beat 2 names the actual service ("water heater swap") and often the real event, in natural language. That is relevance corroboration done the Law 8 way - it is true and specific, so it reads human and helps the engine at once. You never write "Thanks for choosing the best emergency plumber in Austin for your water heater installation Austin service."

### 2.2 Negative review response

The highest-stakes copy in this playbook. The reviewer is one reader; every future prospect judging how the business handles a problem is the real audience. The response is a public de-escalation and a trust demonstration.

**Structure (5 beats, ~50-90 words), the LATER pattern:**
1. **Listen / acknowledge** the specific frustration without defensiveness. "You're right to be frustrated that the technician ran late."
2. **Apologize** for the experience, sincerely, without admitting legal liability where liability is contested. "I'm sorry the appointment didn't go the way it should have."
3. **Take it offline** - name a real contact path (a manager, a direct line, an email) to resolve it privately. "I'd like to make this right. Please reach me directly at [real contact]."
4. **Explain briefly only if it adds trust, never to argue.** One sentence max, and only if true and non-blaming.
5. **Reaffirm the standard.** "This isn't the experience we hold ourselves to."

**Hard rules for negative responses:**
- **Never argue, never call the reviewer a liar, never litigate the facts in public.** Even a false review is answered with composure; the audience is the future prospect, and defensiveness loses them.
- **Never disclose the customer's private details** to "prove" your side (that they were behind on payment, that they were rude, that it was their fault). This is a PII and privacy violation and reads terribly. Enforced by the lint.
- **Never admit legal liability** in a regulated vertical (medical, legal, contracting) without a compliance check. In healthcare, a response must not confirm the person was even a patient (HIPAA); acknowledge generically and move offline.
- **Suspected fake / extortion review:** respond calmly and factually ("We have no record of a job matching this and would like to understand what happened - please contact us at [real path]"), and separately flag to the operator to report it through the platform. Do not accuse in the public reply.

### 2.3 Fake / suspicious review response

A subset of negative handling. The public reply stays composed and non-accusatory; the real remedy (reporting the review, gathering evidence) is an operator action the writer flags. The reply's only job is to show future readers a level-headed business, not to win an argument. Never confirm details that would validate a fabricated claim, never insult, never threaten.

---

## 3. The hard rules (non-negotiable, enforced by the lint)

1. **No PII.** Never publish or confirm a customer's full name, address, phone, account number, medical or legal detail, or any private fact the reviewer did not themselves disclose. In health and legal verticals, do not even confirm the person was a patient or client.
2. **No fabrication.** Never claim a detail the review does not support, invent an outcome, or manufacture a specific to sound personal. If the review is a bare "5 stars" with no text, the response is warm and generic-but-human, not a fabricated story.
3. **No keyword stuffing.** The service name may appear once, naturally, when it is genuinely what the review is about. Repeating "[service] [city]" to farm relevance is spam, reads robotic, and is flagged by the lint. Naturalness first, always.
4. **Owner voice, one human writing.** Every response sounds like the same real person replying, not a marketing department. Contractions, plain words, warmth, variation. No corporate boilerplate ("We value your feedback and strive to provide exceptional service").
5. **No templated near-duplication across a batch.** Ten responses that share the same skeleton and swap one word are visible sameness. Each response is anchored in *its own* review's specifics. The lint flags near-duplicate responses in a batch.
6. **No incentive, no gating, no quid-pro-quo** in a response ("Update your review and we'll refund you" is prohibited).
7. **Composure on negatives, always.** No argument, no blame, no sarcasm, no legal threats.

---

## 4. Best-in-class vs worst: the transferable patterns

These illustrate the pattern; they are archetypes drawn from the consensus of the cited sources, not live-URL teardowns (review threads are volatile and often carry PII, so this playbook teaches the pattern rather than quoting real customers' names).

### 4.1 Positive - best vs worst

**Worst (templated, stuffed):**
> "Thank you for choosing [Company], the best HVAC company in Phoenix! We are the top-rated air conditioning repair Phoenix and AC installation Phoenix service. We look forward to serving all your air conditioning repair Phoenix needs!"

Why it loses: identical across every review, keyword-stuffed, zero acknowledgment of what the reviewer actually said, reads like a bot. Discounted by humans and engine.

**Best (specific, human, naturally relevant):**
> "Thanks, Denise. Glad Marco got the AC cooling again before the weekend heat rolled in - a dead compressor in July is the worst timing. Appreciate you trusting us with the install, and we're a phone call away if the new unit ever needs a look."

Why it wins: names the real tech, the real service (AC/compressor/install), the real timing, in the owner's voice. It corroborates the entity (AC service, summer, install) *because it is true*, not because it was stuffed. This is the Law 8 thesis in one reply.

### 4.2 Negative - best vs worst

**Worst (defensive, discloses PII, argues):**
> "This is completely false. You were 3 weeks late paying your last invoice and our tech told you the part was on backorder. We have your signature on the work order. We will not apologize."

Why it loses: publicly discloses the customer's payment history (PII/privacy), argues, admits nothing, and reads as a business that will humiliate you if you complain. Every future prospect is now nervous.

**Best (composed, offline, trust-building):**
> "I'm sorry the repair didn't go the way it should have, and I understand the frustration with the timing. That's not the standard we hold ourselves to. I'd like to understand what happened and make it right - please reach me directly at [real name / real line]. - [Owner name]"

Why it wins: acknowledges, apologizes without conceding contested facts, moves the detail offline, signs as a real human, and leaves the audience thinking "they handle problems like adults." The reviewer may or may not update; the hundred people who read it next are the win.

---

## 5. Voice and craft notes

- **Match `brand.yaml.voice`.** A plumber, a dentist, and a family-law attorney do not reply alike. Pull `one_line_direction`, `tone_by_context`, `good_examples`, and `banned_phrases`. A dental practice reply is warm and reassuring; a contractor reply is plain and direct; a law-firm reply is measured and careful (and, for negatives, extra-careful on confidentiality).
- **Vary the openings across a batch.** Not every reply starts "Thank you for your review." Rotate real human openers.
- **Length matches the review.** A two-word review gets a one-line warm reply; a detailed paragraph gets a proportionate one. Do not pad.
- **No em dash** (U+2014); the Write hook blocks it. Use hyphens or rewrite.
- **Sign-off consistency.** If the brand signs replies with the owner's first name, do it every time; it is an entity/consistency detail and a trust one.
- **Kill the AI tells:** "We value your feedback", "We strive to", "Your satisfaction is our top priority", "We apologize for any inconvenience this may have caused." These are the sameness signal both readers and the engine punish.

---

## 6. Vertical overlays

- **Medical / dental (YMYL, HIPAA):** never confirm the person is a patient; never reference any clinical detail; keep responses generic and move to a private channel. "We take all feedback seriously and would welcome the chance to speak with you directly at [line]." Confidentiality is a legal line, not a style choice.
- **Legal (YMYL, bar rules):** never confirm representation or case facts; a public reply that discusses a client's matter can breach confidentiality and advertising rules. Acknowledge generically, move offline, flag for the firm's compliance review.
- **Financial:** no specifics about a customer's accounts or situation; move offline.
- **Home services (core lane):** the most latitude - you can name the service and the general job type, still without the customer's private data. This is where the specific, warm, real-detail response shines.

---

## 7. The output contract for a response batch

`/write-review-responses` emits, per batch, to `output/<client>/review-responses/<date>/`:

- `responses.md` - each response paired with the review it answers (review text quoted for context, PII redacted), labeled positive / negative / fake, ready for the operator to paste.
- `lint-report.md` - the `scripts/review_response_lint.py` output: PII check, keyword-stuffing check, near-duplication check across the batch, off-voice check. Every response passes or is flagged with a specific fix.
- `flags.md` - operator actions the writer cannot take: reviews to report as fake, negatives that need a real offline follow-up, any response the operator must fact-check before posting.

A batch is not done until the lint passes clean on every response and the flags file names any review needing operator action.

---

## 8. Finished-batch checklist

- [ ] Every response is grounded in its own review's real content; no fabricated detail.
- [ ] No PII: no customer name/address/account/medical/legal fact beyond what the reviewer disclosed; health and legal replies confirm nothing.
- [ ] No keyword stuffing: service name appears at most once, naturally; lint passes.
- [ ] No templated near-duplication across the batch; each reply is review-specific; lint passes.
- [ ] Negatives are composed, non-defensive, move offline to a real contact path, disclose no private facts, admit no contested/legal liability.
- [ ] Fake/suspicious reviews: composed public reply + operator flag to report; no public accusation.
- [ ] Voice matches `brand.yaml`; AI tells killed; openings varied; sign-off consistent.
- [ ] Vertical overlay applied (HIPAA / bar rules / financial confidentiality where relevant).
- [ ] No em dash; no incentive/gating language.
- [ ] Output contract emitted: `responses.md`, `lint-report.md`, `flags.md`; lint clean.
</content>
</invoke>
