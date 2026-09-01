"""PreToolUse hook for Write/Edit — block em-dash character (U+2014) before it lands on disk.

stdin: JSON tool call payload. Exit 0 = allow, Exit 2 = block with stderr as feedback to Claude.
"""
import json
import sys

EM_DASH = "—"

try:
    # Read bytes and decode UTF-8 explicitly: Windows stdin defaults to the
    # cp1252 locale, which would mis-decode a UTF-8 em dash and let it slip past.
    raw = sys.stdin.buffer.read()
    payload = json.loads(raw.decode("utf-8"))
except Exception:
    sys.exit(0)

tool_input = payload.get("tool_input", {}) or {}

candidates = []
for key in ("content", "new_string", "old_string"):
    val = tool_input.get(key)
    if isinstance(val, str):
        candidates.append((key, val))

bad = [k for k, v in candidates if EM_DASH in v]

if bad:
    print(
        f"BLOCKED: em dash (U+2014) present in field(s): {', '.join(bad)}. "
        "Use a regular dash '-' or rephrase. This is a hard founder preference.",
        file=sys.stderr,
    )
    sys.exit(2)

sys.exit(0)
