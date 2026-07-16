"""The Skills MCP gateway: authenticate a skill token, then dispatch a SAFE,
scoped subset of backend operations to LOCAL Claude Code skills (Part 9 / P9-1).

WHAT THIS IS. A client runs Claude Code skills on their own machine. Those skills
talk to this backend through an MCP server (``mcp_server_backend``). Each MCP tool
call presents a SKILL TOKEN; this gateway (1) authenticates it via
``app.services.skill_tokens.verify_skill_token`` into a :class:`ScopedPrincipal`,
(2) authorizes the requested tool against that principal's capped RBAC/tier scope,
(3) cost-gates any paid tool against the principal's OWN client budget, and (4)
dispatches to the backend operation with ``client_id`` PINNED from the token.

WHY IT CANNOT BYPASS THE GUARANTEES (invariants #3/#9/#10). The gateway never
widens a token's authority: authorization is a pure check of the tool's requirement
against the granted scope; the cost-gate is the SAME ``CostGate`` every paid path
uses (a leaked token still cannot outspend the client cap or the daily stop); and
``client_id`` is taken from the verified token, NEVER from the call arguments, so a
token for tenant A can never address tenant B (any ``client_id`` in the args is
dropped). Nothing here can read the vault or mint/reveal a secret.

SCOPE OF THIS CHUNK (core + thin adapter stub). The AUTH + AUTHORIZE + COST-GATE +
DISPATCH CORE is complete and unit-tested (see ``tests/test_skill_tokens.py``): it
runs against an injected handler registry + cost-gate so it is provider-agnostic
and fully testable with fakes. The MCP wire adapter is a THIN, DEPENDENCY-FREE stub
(:func:`describe_tools` emits MCP tool descriptors; :func:`run_stdio_server` documents
the remaining wiring). REMAINING (a follow-up chunk): add the ``mcp`` package as a
dep, back each tool with a real handler that calls the existing FastAPI
route/service with the pinned ``client_id`` (executing as a dedicated service
identity so RLS + the review-gate triggers still apply), and boot the stdio server.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from app.services.cost_gate import CostGate, GateContext
from app.services.skill_tokens import ScopedPrincipal, verify_skill_token

# The MCP server name the local Claude Code client connects to.
MCP_SERVER_NAME = "mcp_server_backend"

# A handler executes one tool for a resolved principal. It receives the capped
# principal + the (client_id-stripped) call args and returns a JSON-able result.
SkillHandler = Callable[[ScopedPrincipal, dict[str, Any]], Any]


class SkillGatewayError(RuntimeError):
    """Base for gateway failures (never carries a secret)."""


class SkillAuthError(SkillGatewayError):
    """The presented token failed to authenticate (unknown/expired/revoked/malformed)."""


class SkillScopeError(SkillGatewayError):
    """The token authenticated but lacks the scope (perm/feature/tier) for the tool."""


class UnknownSkillToolError(SkillGatewayError):
    """The requested tool name is not part of the exposed safe subset."""


@dataclass(frozen=True)
class SkillTool:
    """One exposed MCP tool = a safe, scoped mapping to a backend operation.

    ``required_perm``/``required_feature`` are the RBAC gate; ``min_tier`` is the
    delivery-tier floor; ``paid`` marks a tool whose backend op makes a metered
    provider call (so the gateway cost-gates it on ``cost_feature`` - a money-dial
    key). ``method``/``path`` document the FastAPI route the real handler targets.
    """

    name: str
    module: str
    method: str
    path: str
    description: str
    required_perm: str | None = None
    required_feature: str | None = None
    min_tier: str = "free"
    paid: bool = False
    cost_feature: str = ""
    cost_estimate: float = 0.0
    provider: str = "internal"
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )


# The SAFE subset exposed to Claude Code. Deliberately EXCLUDES vault, team/access,
# billing, provisioning, cost-dial writes - a skill can operate a client's delivery
# work, never the agency's secrets or governance. READS are unpaid; the two write
# tools (audit run, content create) are paid + cost-gated.
SKILL_TOOLS: dict[str, SkillTool] = {
    "audit.run": SkillTool(
        name="audit.run", module="audits", method="POST", path="/api/v1/audits",
        description="Queue a URL audit for the token's client (Free is $0; Paid is gated + metered).",
        required_perm="run_audits", paid=True, cost_feature="tech_audit",
        cost_estimate=1.5, provider="audit_engine",
        input_schema={"type": "object", "properties": {"url": {"type": "string"},
                      "tier": {"type": "string"}, "types": {"type": "array"}},
                      "required": ["url"]},
    ),
    "audit.read": SkillTool(
        name="audit.read", module="audits", method="GET", path="/api/v1/audits",
        description="List / read the client's audits and scores.",
        required_perm="view_reports",
    ),
    "content.create": SkillTool(
        name="content.create", module="content", method="POST", path="/api/v1/content/jobs",
        description="Create a content job for the client (enqueues the drafting pipeline; metered).",
        required_perm="publish_content", paid=True, cost_feature="content",
        cost_estimate=0.15, provider="anthropic",
        input_schema={"type": "object", "properties": {"page_type": {"type": "string"},
                      "topic": {"type": "string"}}, "required": ["page_type", "topic"]},
    ),
    "content.review": SkillTool(
        name="content.review", module="content", method="POST",
        path="/api/v1/content/jobs/{code}/review",
        description="Approve / edit / reject a content job at the human review gate.",
        required_perm="publish_content",
    ),
    "content.read": SkillTool(
        name="content.read", module="content", method="GET", path="/api/v1/content/jobs",
        description="List / read the client's content jobs.",
        required_perm="view_reports",
    ),
    "offpage.read": SkillTool(
        name="offpage.read", module="offpage", method="GET", path="/api/v1/offpage/backlinks",
        description="Read the client's backlink profile, citations and off-page KPIs.",
        required_perm="view_reports",
    ),
    "policy.read": SkillTool(
        name="policy.read", module="policy", method="GET", path="/api/v1/policy/recommendations",
        description="Read policy-radar sources, changes, KB and recommendations.",
        required_perm="view_reports",
    ),
    "reports.read": SkillTool(
        name="reports.read", module="reports", method="GET", path="/api/v1/reports/workbooks",
        description="Read the client's report workbooks and sync status.",
        required_perm="view_reports",
    ),
    "command_center.read": SkillTool(
        name="command_center.read", module="command_center", method="GET",
        path="/api/v1/command-center",
        description="Read the command-center roll-up for the client.",
        required_perm="view_reports",
    ),
}


@dataclass(frozen=True)
class GatewayResult:
    """The outcome of one dispatched tool call (safe to return to the skill)."""

    status: Literal["ok", "blocked"]
    tool: str
    client_id: str
    data: Any = None
    reason: str = ""
    cost: float = 0.0


def authorize_tool(principal: ScopedPrincipal, tool: SkillTool) -> None:
    """Raise :class:`SkillScopeError` unless the principal's scope covers ``tool``.

    A token can NEVER exceed its granted perms/features/tier: each requirement is
    checked against the capped principal, so a token missing ``publish_content`` can
    never drive ``content.create`` even though the endpoint exists.
    """
    if tool.required_perm is not None and not principal.has_perm(tool.required_perm):
        raise SkillScopeError(
            f"token lacks permission '{tool.required_perm}' required by tool '{tool.name}'"
        )
    if tool.required_feature is not None and not principal.has_feature(tool.required_feature):
        raise SkillScopeError(
            f"token lacks feature '{tool.required_feature}' required by tool '{tool.name}'"
        )
    if not principal.allows_tier(tool.min_tier):
        raise SkillScopeError(
            f"token tier '{principal.tier}' is below tier '{tool.min_tier}' required by "
            f"tool '{tool.name}'"
        )


class SkillGateway:
    """Authenticate -> authorize -> cost-gate -> dispatch, with fakes injectable.

    ``verify`` resolves a raw token to a principal (defaults to the real
    ``verify_skill_token``); ``cost_gate`` is the shared :class:`CostGate` used for
    paid tools; ``handlers`` maps a tool name to the callable that performs it. In
    THIS chunk ``handlers`` is empty by default (the real handlers are the documented
    remaining wiring), so the auth/authorize/cost-gate CORE is exercised with fakes.
    """

    def __init__(
        self,
        *,
        verify: Callable[[str], ScopedPrincipal | None] = verify_skill_token,
        cost_gate: CostGate | None = None,
        handlers: dict[str, SkillHandler] | None = None,
    ) -> None:
        self._verify = verify
        self._cost_gate = cost_gate
        self._handlers: dict[str, SkillHandler] = dict(handlers or {})

    def authenticate(self, raw_token: str) -> ScopedPrincipal:
        """Resolve a raw skill token to its principal, or raise :class:`SkillAuthError`."""
        principal = self._verify(raw_token)
        if principal is None:
            raise SkillAuthError("invalid, expired, or revoked skill token")
        return principal

    def dispatch(
        self,
        principal: ScopedPrincipal,
        tool_name: str,
        args: dict[str, Any] | None = None,
    ) -> GatewayResult:
        """Authorize + cost-gate + run one tool for an already-authenticated principal."""
        tool = SKILL_TOOLS.get(tool_name)
        if tool is None:
            raise UnknownSkillToolError(f"unknown skill tool '{tool_name}'")
        authorize_tool(principal, tool)

        call_args = dict(args or {})
        # BLAST-RADIUS: the tenant is ALWAYS the token's own client_id. Any client_id
        # a caller tries to pass is dropped, so a token for A can never reach B.
        call_args.pop("client_id", None)

        ctx: GateContext | None = None
        if tool.paid and self._cost_gate is not None:
            ctx = GateContext(
                feature_key=tool.cost_feature,
                client_id=principal.client_id,
                provider=tool.provider,
                estimated_cost=tool.cost_estimate,
                job_type=tool.name,
            )
            decision = self._cost_gate.evaluate(ctx)
            if not decision.allowed:
                # A block DEGRADES the call - it never bypasses the gate.
                return GatewayResult(
                    status="blocked", tool=tool.name, client_id=principal.client_id,
                    reason=decision.reason or decision.outcome,
                )

        handler = self._handlers.get(tool_name)
        if handler is None:
            # The CORE is wired; the module handler is the documented remaining work.
            raise NotImplementedError(
                f"no handler registered for skill tool '{tool_name}' "
                "(the auth/authorize/cost-gate core is complete; wire the module "
                "handler per the file docstring)"
            )
        data = handler(principal, call_args)
        if ctx is not None and self._cost_gate is not None:
            self._cost_gate.commit(ctx, tool.cost_estimate)
        return GatewayResult(
            status="ok", tool=tool.name, client_id=principal.client_id,
            data=data, cost=(tool.cost_estimate if ctx is not None else 0.0),
        )

    def call(
        self, raw_token: str, tool_name: str, args: dict[str, Any] | None = None
    ) -> GatewayResult:
        """Convenience: authenticate the token then dispatch the tool in one step."""
        principal = self.authenticate(raw_token)
        return self.dispatch(principal, tool_name, args)


# --------------------------------------------------------------------------- #
# Thin MCP adapter (dependency-free stub - documents the remaining wire-up)
# --------------------------------------------------------------------------- #
def describe_tools() -> list[dict[str, Any]]:
    """Emit MCP tool descriptors for ``mcp_server_backend`` (name/description/schema).

    This is the MCP-facing catalogue a Claude Code client lists. It is pure data, so
    it needs no ``mcp`` dependency and is unit-testable; the live server (below)
    consumes it once the transport is wired.
    """
    return [
        {"name": t.name, "description": t.description, "inputSchema": t.input_schema}
        for t in SKILL_TOOLS.values()
    ]


def run_stdio_server() -> None:  # pragma: no cover - transport wiring is a follow-up
    """Boot ``mcp_server_backend`` over stdio (NOT wired in this chunk).

    Remaining wiring (documented, intentionally not implemented here):

    1. Add the ``mcp`` package to the ``[ai]``/a new ``[skills]`` optional extra.
    2. For each :data:`SKILL_TOOLS` entry, register a real handler that calls the
       existing FastAPI route/service with ``client_id`` pinned from the verified
       principal, executing as a dedicated service identity so RLS + the content
       review-gate triggers still apply (never a raw RLS bypass).
    3. Read the skill token from the MCP client's configured env, construct a
       :class:`SkillGateway` with the shared :class:`CostGate`, and route each MCP
       ``call_tool`` through :meth:`SkillGateway.call`.
    4. Serve over stdio via the ``mcp`` runtime.
    """
    raise NotImplementedError(
        "mcp_server_backend stdio transport is not wired in P9-1; the auth/authorize/"
        "cost-gate/dispatch core + tool catalogue are complete. See the docstring for "
        "the remaining steps."
    )
