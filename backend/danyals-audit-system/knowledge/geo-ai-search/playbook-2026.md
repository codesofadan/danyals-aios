# Generative Engine Optimization (GEO) playbook - 2026

Loaded by: A5 (GEO + AI Search), C4 (Brand Authority).
Sources: Otterly methodology; Profound research; SEMrush AI Visibility studies; manual probing patterns.

## The four engines worth auditing for in 2026

1. **Google AI Overviews** - the largest distribution surface; cited URLs visible in the answer
2. **ChatGPT search** (with web) - growing rapidly; cites links inline
3. **Perplexity** - cites every claim with a numbered footnote; the cleanest citation behavior
4. **Claude with web** - cites selectively; behavior is closer to ChatGPT

Bing (Copilot) overlaps with ChatGPT search in many cases.

## What makes a page get cited

Across all four engines, the same patterns increase citation probability:

1. **Direct answer at the top** - a 40-80 word paragraph that directly answers the likely query, before any context-setting fluff
2. **Self-contained passages** - each subheading + the first 2-3 sentences should make sense lifted out of context
3. **Structured data** - tables with `<th>`, lists with proper `<ol>`/`<ul>`, FAQ with `<dt>`/`<dd>` or schema
4. **Canonical entity references** - call entities by their canonical Wikipedia/Wikidata names where possible
5. **Recency signals** - dated updates, current-year mentions, freshness in URL
6. **Authoritative tone** - first-person, dated, specific. Hedge phrases ("might", "could") get filtered in favor of declarative content
7. **Clean semantic HTML** - no critical content gated behind JS render; LLMs see what crawlers see

## What does not (yet) move citation probability

- **llms.txt** - widely adopted in 2026 (800K+ sites) but no engine has confirmed reading it. Implement it, but mark the finding "expected best practice, no confirmed signal".
- **Meta tags claiming AI-friendliness** - no engine reads ai-content-declaration or similar yet.
- **Word count** - longer is not better. Citation-worthy passages are usually 100-300 words.

## AI crawler robots directives

Crawlers Google uses for AI Overviews and beyond:
- **Google-Extended** - Google's opt-out token for Bard/Gemini training; does not affect AI Overviews
- **GPTBot** - OpenAI's training crawler; blocking it does not block ChatGPT search
- **OAI-SearchBot** - OpenAI's search-time crawler; this is the one that affects ChatGPT citations
- **ClaudeBot** - Anthropic's training crawler
- **Claude-Web** - Anthropic's search-time fetcher
- **PerplexityBot** - Perplexity's training crawler
- **Perplexity-User** - Perplexity's user-time fetcher
- **Applebot-Extended** - Apple's AI training opt-out token

Default audit recommendation: allow all unless the client wants explicit opt-out for training. Citation behavior follows the search-time crawlers, not the training ones.

## Measurement: what to track for agency clients

Even without an Otterly subscription, monthly manual probing on the top 10 commercial queries provides a reasonable baseline:

1. Run the query in ChatGPT (with web), Perplexity, Google (looking for AI Overview), and Claude.
2. Record whether the client's site is cited, in which position.
3. Record the competitors that are cited.
4. Track month-over-month.

A 15-minute monthly task. The output is a simple table that goes in the report appendix.

## How A5 uses this

A5 maps page structure to citation eligibility. "First paragraph is 142 words and answers the query implicitly but not directly; the H2 'Why Lahore plumbers charge differently' is search-quotable but the paragraph below opens with a date instead of the answer. Restructure to lead with the 60-word answer; passage citability score 6 -> 9 expected."
