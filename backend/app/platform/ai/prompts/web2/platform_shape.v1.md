---
id: web2/platform_shape
version: 1
task_tier: structured
inputs: platform, capabilities
outputs: one paragraph describing how a post should be shaped for this platform
changelog: v1 - turns the capability matrix row into the register note the drafting prompt consumes
---
Describe, in ONE tight paragraph, how a post should be shaped for {platform}.

The platform's measured capabilities:
{capabilities}

Cover only what changes the writing: expected length, whether the audience is technical
or general, whether headings and lists are conventional there, how links are normally
used, and what would read as out of place. State it as instructions to a writer.

Do not invent capabilities that are not listed. If the capabilities say a platform has
no heading support, do not suggest headings. Output the paragraph only.
