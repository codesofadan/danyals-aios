# llms.txt: The Do-Not-Build Verdict

**Verdict: SEO-CONTENT-OS does not ship an llms.txt generator as a citation feature. The evidence for a citation lift is absent, and building it as a "GEO win" would be a fabricated-benefit claim.**

This note exists so the hype does not creep back in. llms.txt is a proposed convention: a `/llms.txt` markdown file at the site root that lists a site's key pages for large language models, pitched as a robots.txt-style aid for AI crawlers. It sounds plausible and adjacent to everything this system does, which is exactly why it needs a written verdict rather than a shrug.

Grounding: `research/expansion-2026-07/04-geo-ai-search.md` Section 3, fetched live 2026-07-20 PKT.

---

## The evidence

**Crawlers do not fetch it.** Adoption is about 10% of sites (SE Ranking, 300k domains), but the AI crawlers overwhelmingly do not request `/llms.txt`. GPTBot, ClaudeBot, PerplexityBot, OAI-SearchBot, and Google-Extended crawl HTML directly. A file that the crawlers do not fetch cannot influence what they cite.

**Google will not support it.** Gary Illyes (Google, July 2025) confirmed Google does not support llms.txt and is not planning to. John Mueller compared it to the discredited keywords meta tag. Anthropic and Perplexity have said they *may* read it when present, but no engine's answer-surface citation is measurably improved by it today.

**No measured citation lift exists.** There is no study showing llms.txt moves citation share on any answer surface. Contrast that with the levers in `knowledge/foundations/geo-ai-citation.md`, which trace to the controlled Princeton GEO study (arXiv 2311.09735). llms.txt has nothing comparable behind it.

---

## The rule

Under the no-fabricated-success rule and Law 8 (optimize the reward function, not a proxy), building llms.txt into the doctrine as a citation feature would be selling a benefit that does not exist. So:

- **Do not** build an llms.txt generator, gate, or "GEO score" line item around it.
- **Do not** tell a client an llms.txt file will improve their AI citation. It will not, on today's evidence.
- **If a client asks for one,** it is a cheap, harmless nicety. Frame it honestly as "low-cost, unproven, optional," ship it as a courtesy if they insist, and never count it as a citation lever or a deliverable that moves the measured metric.

The winning move is the parallel-discipline framing (Aleyda Solis, via Search Engine Land's LLMO guide and Learning AI Search): LLMO is a discipline alongside SEO, not a replacement, and the LLMO-specific work is structure (extractability), entity (corroboration), and freshness, not a magic file. Spend the effort on the evidenced levers in `geo-ai-citation.md`, not on a file the crawlers skip.

Sources:
- llms.txt adoption and impact: https://organikpi.com/blog/distribution/llms-txt-adoption-impact/
- llms.txt guide and crawler behavior: https://okara.ai/blog/llms-txt-guide
- Entity SEO / Knowledge Graph (where the effort should go instead): https://www.digitalapplied.com/blog/entity-seo-knowledge-graph-optimization-guide-2026
- LLMO as a parallel discipline: https://searchengineland.com/guides/large-language-model-optimization-llmo and https://learningaisearch.com/

*Re-verify quarterly. If an engine begins measurably weighting llms.txt for answer-surface citation, this verdict changes and the note gets updated with the new evidence. It has not, as of 2026-07-20 PKT.*
