"""Claude-agent dispatcher for the 87 ai-assisted YAML checks.

The 21 specialist agent definitions live at ``.claude/agents/**/*.md``. This
module loads each agent's system prompt, scopes its work to the YAML checks it
owns, and dispatches them in parallel via the Anthropic API. Their structured
JSON output is parsed into ``Finding`` rows and merged with the deterministic
findings before scoring.

Free path: skip - deterministic findings only.
Paid path: gate behind --agents on/ask. ~$0.50-2 per audit on Sonnet 4.6.
"""

from audit_engine.agents.dispatcher import dispatch_agents

__all__ = ["dispatch_agents"]
