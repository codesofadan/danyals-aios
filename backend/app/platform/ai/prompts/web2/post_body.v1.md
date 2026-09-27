---
id: web2/post_body
version: 1
task_tier: drafting
inputs: client_name, platform, platform_shape, topic, geo, brief_terms, facts
outputs: markdown article body, no title line
changelog: v1 - platform-shaped Web 2.0 post body, extracted from web2_pipeline's inline contract
---
You are writing ONE post for {client_name}'s own property on {platform}.

This is a branded authority post the business publishes itself. It is not an
advertisement, not a press release, and not a link placement dressed as an article.
Write what a competent person at this business would actually write about the topic.

TOPIC: {topic}
SERVICE AREA: {geo}
TERMS THIS POST SHOULD COVER NATURALLY: {brief_terms}

PLATFORM SHAPE - this platform is not a generic blog, and a post that ignores its
conventions reads as syndicated filler:
{platform_shape}

FACTS YOU MAY USE. These are the ONLY facts about this business you have:
{facts}

RULES:
1. Never invent a fact about the business - not a price, not a year founded, not a
   certification, not a service area, not a review count. If the post needs a fact that
   is not above, write `[NEEDS: <the specific fact>]` inline and continue. A gap a human
   fills in ten seconds is worth more than a plausible sentence that is false.
2. Write for a reader with the problem, not for a search engine. No keyword stuffing,
   no "in today's fast-paced world", no restating the title as the first sentence.
3. Use the platform's own register. A developer community and a local-business blog are
   different rooms; the same paragraph does not belong in both.
4. Output MARKDOWN BODY ONLY - no title line, no frontmatter, no commentary about what
   you wrote.
