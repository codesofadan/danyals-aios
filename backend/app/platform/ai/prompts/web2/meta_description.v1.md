---
id: web2/meta_description
version: 1
task_tier: bulk
inputs: title, topic, client_name, excerpt, max_chars
outputs: one meta description, plain text
changelog: v1 - meta description for platforms that expose the field (REQ-W2-008)
---
Write ONE meta description for this page.

TITLE: {title}
TOPIC: {topic}
BUSINESS: {client_name}

THE PAGE OPENS:
{excerpt}

RULES:
1. At most {max_chars} characters. Search engines truncate past that, and a description
   cut mid-word is worse than a shorter one.
2. Describe what the reader gets from THIS page. Do not restate the title.
3. No quotes around it, no "In this article we will", no business boilerplate, no
   keyword stuffing, no trailing ellipsis.
4. State only what the excerpt above supports. Invent nothing about the business.
5. One sentence, or two short ones.

Output the description text only.
