# Scan-Layer Formatting (NN/g F-Pattern) + Message Match

Canonical spec. Defined once here; playbooks reference this file. This is the best-evidenced framework in the library.

## What it is
People scan, they do not read. Nielsen Norman Group's eye-tracking corpus (stable 20+ years) shows the **F-pattern** is the default scan of text-heavy content, users read roughly **a quarter of the words** on a page, and content on the right and lower-left is routinely missed. The **scan layer** is the bolded-and-headed skeleton of the page that must carry the whole argument on its own for the majority who never read the body.

## When to use for local (emergency vs considered)
- **Every page, both intents.** Most local pages are read on a phone, often under stress. This is a formatting lever on every draft.
- **Emergency:** the scan layer must surface the answer, the phone number, and one trust signal without any scrolling or hunting.

## Local adaptation
- **Build a real scan layer:** bold the load-bearing phrases, use question-headed H2/H3, keep paragraphs to 1-3 sentences. The bold-and-heading layer alone must carry the argument for the ~75% who never read the body.
- **Front-load the answer and the CTA** (BLUF / inverted pyramid). The answer to the page's implied question sits in the first 100 words.
- **Good subheads break the F** into a cleaner layer-cake scan; that is what well-structured headings buy you.
- **Message match:** the H1 and CTA language mirror the search query ("emergency plumbing" for "emergency plumber near me"). Query-to-page mismatch is a well-established conversion leak.
- **Click-to-call is non-negotiable on mobile:** a real `tel:` link, a thumb-reachable sticky call button, NAP-consistent number. Tap target >= 44px.
- **One attention ratio** (Oli Gardner): clickable primary actions approach the number of goals. Two co-equal primary CTAs split intent; demote everything but the one action to a text link.

## PASS test
- **The argument survives being read at the bold-and-heading level only** (strip the body paragraphs; the page still makes its case and its ask).
- Paragraphs are short (1-3 sentences); no section is a wall of text.
- A NAP-consistent **click-to-call** is present and thumb-reachable on mobile.
- H1/CTA language **matches the target query**; exactly one primary action.

## Anti-pattern
- A wall of unbolded prose with no scan anchors.
- The CTA or phone number buried, requiring a hunt or a scroll on mobile.
- H1 language that does not match the query the page targets.
- Two co-equal primary CTAs.

## Evidence grade
**Strong, empirical, primary-source (controlled-proof).** NN/g eye-tracking is the most evidence-backed territory in this library. The scan-layer, F-pattern, and 25%-of-words-read findings are directly measured. Message match and single-attention-ratio are strong principled CRO consensus. **Note:** the related "first-person CTA lifts clicks 90%" figure is **folklore** (single Aagaard/Unbounce test); use the first-person tactic, never quote the number (see README and `copyhackers-hero-and-belief.md`).

Sources: [NN/g, F-pattern](https://www.nngroup.com/videos/f-pattern-reading-digital-content/); [home services CTA stats](https://cubecreative.design/blog/small-business-marketing/top-10-cta-stats-home-services); [CTA statistics roundup, folklore figure flagged](https://wisernotify.com/blog/call-to-action-stats/) (fetched 2026-07-20).
