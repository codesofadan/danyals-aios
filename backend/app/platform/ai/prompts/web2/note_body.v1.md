---
id: web2/note_body
version: 1
task_tier: drafting
inputs: client_name, platform, platform_shape, topic, geo, max_chars, facts
outputs: one short plain-text note, no title, no link
changelog: v1 - short-form composer for note/snippet/profile placements the article generator cannot serve
---
Write ONE short post for {client_name} on {platform}.

This is not an article and not an excerpt from one. It is a single self-contained
thought that stands on its own in a feed.

TOPIC: {topic}
SERVICE AREA: {geo}

PLATFORM: {platform_shape}

HARD LIMIT: {max_chars} characters. Going over does not get trimmed politely - the
platform cuts mid-sentence, so write inside the limit.

FACTS YOU MAY USE. These are the ONLY facts about this business you have:
{facts}

RULES:
1. Never invent a fact about the business. If the note needs one you do not have, write
   `[NEEDS: <the specific fact>]` and continue.
2. PLAIN TEXT only. No headings, no markdown, no bullet lists, no hashtags, no emoji
   unless the platform note above says otherwise. Formatting is stripped before this
   publishes, so it would appear as literal characters or vanish.
3. Do NOT write a link or a URL. The link is appended after your text automatically -
   writing one yourself produces it twice.
4. Do not open with the topic restated as a label ("CCTV drain surveys:"). Write the
   way a person posts: say the useful thing first.
5. One idea. A short post that makes one point beats a compressed article.

Output the note text only.
