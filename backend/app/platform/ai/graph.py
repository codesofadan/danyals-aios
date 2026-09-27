"""The LangGraph runtime: checkpointing, resumption, and the human-approval interrupt.

``06-AI-STACK.md`` §1 and §2. LangGraph earns its place here for exactly one property -
**checkpointed, resumable graph state** - and this module is the thin layer that makes
that property real against THIS system's Postgres and THIS system's job engine.

THE PROBLEM IT SOLVES, CONCRETELY. ``web2_pipeline.run_write`` drafts one property with a
straight-line function. A thirty-property campaign is thirty of those, and a worker that
dies at property nineteen loses nothing of properties 1-18 (they are already rows) but
loses everything about property 19 - including the paid model calls that had already been
made inside its ``generate()`` fan-out, because ``track()`` only ever writes at the end.
A checkpointed graph writes state after every node, so the retry resumes at the node that
failed rather than at the beginning of the property.

HOW IT COMPOSES WITH THE JOB ENGINE. They are not competitors, they nest (§1):

    job (durable, ``app/jobs/runner.py``) - owns the lifecycle, idempotency, retries,
      the dead letter, the concurrency slot
      └── graph (LangGraph, checkpointed to the same Postgres) - owns the REASONING
            state: which nodes have run, what they produced, where it parked

The job's ``idempotency_key`` and the graph's ``thread_id`` are deliberately the same
string (:func:`thread_id_for`), so a redelivered job resumes its own graph instead of
starting a second one beside it. That single decision is what makes "retry" mean the same
thing at both layers.

NO NODE RETRIES INTERNALLY (§2). A node that catches its own provider failure and tries
again hides the failure from the retry ledger, and the ledger is the only place an
operator can see that a provider has been failing all afternoon.

EVERY IMPORT OF ``langgraph`` IS LAZY. It is an optional ``[graph]`` extra, and the base
image must stay light - ``pyproject.toml`` records the resolver backtracking that heavy
AI dependency trees caused here before. A system without the extra installed degrades to
:class:`GraphUnavailable`, which callers treat as "run the linear path", never as a crash.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from app.logging_setup import get_logger
from app.platform.ai import tracing

logger = get_logger("platform.ai.graph")


class GraphThreadMissing(RuntimeError):  # noqa: N818 - a signal the caller degrades on, not a fault
    """A resume was asked for a thread that has no checkpoint.

    A DISTINCT failure, because LangGraph's own behaviour here is dangerous for us: with
    no checkpoint to resume, ``Command(resume=...)`` falls through to a FRESH RUN of the
    graph on whatever input was passed. For this system that means the approval endpoint,
    trying to apply a lead's decision, would instead re-enter at the first node and
    re-draft the article - paying for it a second time - or fail deep inside the state
    schema with a validation error naming a field the caller never supplied.

    It happens for exactly one reason in practice: the draft ran on an IN-MEMORY
    checkpointer (no ``database_admin_url``, or migration 0148 not applied), so the
    thread died with the process that made it. Raising names that, and the caller falls
    back to the linear approval path - which still works, because the row is in Postgres.
    """


class GraphUnavailable(RuntimeError):  # noqa: N818 - same: 'use the linear path', not a fault
    """LangGraph is not installed, or no checkpointer could be opened.

    Deliberately a distinct type from any execution error: "the graph could not run"
    and "the graph ran and failed" send an operator to opposite ends of the system, and
    a single exception type would make them indistinguishable in the job ledger.
    """


@dataclass(frozen=True)
class GraphRuntime:
    """A resolved graph runtime: whether graphs can run, and what they checkpoint to.

    ``durable`` is the field that matters. An in-memory checkpointer satisfies the API
    and satisfies tests, and it silently provides NONE of the resumption this module
    exists for - a worker restart loses every checkpoint. So it is reported rather than
    assumed, and a production path that finds ``durable`` False should say so.
    """

    available: bool = False
    durable: bool = False
    backend: str = "none"
    reason: str = "langgraph not installed"

    @property
    def describe(self) -> str:
        if not self.available:
            return f"graphs unavailable ({self.reason})"
        kind = "durable" if self.durable else "IN-MEMORY (no resumption across restarts)"
        return f"graphs on -> {self.backend} checkpointer, {kind}"


def thread_id_for(*parts: str) -> str:
    """The graph ``thread_id`` for a unit of work.

    Derived from the same identity the job engine uses for idempotency, so a redelivered
    job attaches to its OWN checkpoint rather than forking a second run. Hashed rather
    than concatenated because thread ids end up in logs and URLs, and a raw
    ``client_id|target_url|topic`` is both unbounded and leaky.
    """
    seed = "|".join(part.strip() for part in parts if part and part.strip())
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def checkpoint_dsn(settings: Any) -> str:
    """The DSN the checkpointer must use: the PRIVILEGED one, not the tenant one.

    THIS IS NOT A PREFERENCE, AND GETTING IT WRONG FAILS SILENTLY - which is how it was
    found. ``PostgresSaver.setup()`` CREATES the checkpoint tables, and ``database_url``
    is the ``authenticated`` role that RLS applies to: it holds no DDL rights, so setup
    raises ``InsufficientPrivilege: permission denied for schema public``, the fallback
    below catches it, and the system runs on an in-memory saver. Everything still works.
    Nothing resumes. A deployment would have believed it had durable graph state right up
    until the first worker restart that needed it.

    Checkpoint tables are INFRASTRUCTURE, like the job ledger - they are not tenant data
    and carry no ``client_id`` to scope by, so ``database_admin_url`` (``service_role``)
    is the correct seam rather than a privilege escalation. ``database_url`` is returned
    only as a last resort, where it will fail loudly into the fallback rather than
    pretending.
    """
    if settings is None:
        return ""
    admin = str(getattr(settings, "database_admin_url", "") or "").strip()
    return admin or str(getattr(settings, "database_url", "") or "").strip()


def runtime_state(settings: Any = None) -> GraphRuntime:
    """Probe what graph support this process actually has, without opening anything."""
    try:
        import langgraph  # noqa: F401
    except ImportError:
        return GraphRuntime(reason="langgraph not installed (pip install -e '.[graph]')")
    dsn = checkpoint_dsn(settings)
    if not dsn:
        return GraphRuntime(
            available=True, durable=False, backend="memory",
            reason="no database_admin_url: checkpoints are per-process only",
        )
    try:
        from langgraph.checkpoint.postgres import PostgresSaver  # noqa: F401
    except ImportError:
        return GraphRuntime(
            available=True, durable=False, backend="memory",
            reason="langgraph-checkpoint-postgres not installed",
        )
    return GraphRuntime(available=True, durable=True, backend="postgres", reason="")


@contextmanager
def checkpointer(settings: Any = None) -> Iterator[Any]:
    """Open a checkpointer for the duration of a run.

    Postgres against the same ``database_url`` the rest of the system uses (§2: "the same
    database, in the same schema family as jobs"), falling back to the in-memory saver
    when the driver or the DSN is absent. The fallback is LOGGED at warning level,
    because a deployment that believes it has durable graph state and does not has a
    resumption story that will fail the first time it is needed.

    A context manager rather than a cached singleton because ``PostgresSaver`` owns a
    connection pool, and a pool that outlives the work it was opened for is how a worker
    ends up holding idle Postgres connections all night.
    """
    state = runtime_state(settings)
    if not state.available:
        raise GraphUnavailable(state.reason)

    if state.durable:
        try:
            from langgraph.checkpoint.postgres import PostgresSaver

            with PostgresSaver.from_conn_string(checkpoint_dsn(settings)) as saver:
                # DO NOT call saver.setup() when migration 0148 has already created the
                # tables. `setup()` opens with `CREATE TABLE IF NOT EXISTS`, and Postgres
                # checks CREATE privilege on the SCHEMA before it checks whether the table
                # exists - so on an already-migrated database it still raises
                # `InsufficientPrivilege: permission denied for schema public`, and the
                # fallback below would quietly drop a fully-provisioned deployment onto an
                # in-memory saver. Neither runtime role may create in `public` by design
                # (0000_local_platform.sql grants USAGE only); DDL belongs to migrations.
                #
                # `setup()` is still called when the tables are ABSENT, which is the
                # developer who has not applied 0148 yet: it will raise, the fallback will
                # catch it, and the warning names what to do.
                if not _checkpoint_tables_present(saver):
                    saver.setup()
                yield saver
                return
        except Exception as exc:
            logger.warning(
                "graph_checkpointer_degraded",
                error=repr(exc),
                detail="falling back to an in-memory checkpointer: this run cannot "
                       "resume after a worker restart",
            )

    from langgraph.checkpoint.memory import InMemorySaver

    yield InMemorySaver()


#: The tables migration 0148 provisions. Probed rather than assumed, so a half-applied
#: database (0148 missing, or applied to a different database than the DSN points at)
#: takes the honest in-memory path instead of failing on the first checkpoint write.
_CHECKPOINT_TABLES: tuple[str, ...] = (
    "checkpoint_migrations", "checkpoints", "checkpoint_blobs", "checkpoint_writes",
)


def _checkpoint_tables_present(saver: Any) -> bool:
    """Whether migration 0148 has provisioned this database's checkpoint schema.

    A catalogue read rather than a `CREATE TABLE IF NOT EXISTS`, because the latter needs
    a privilege the runtime roles deliberately do not have (see the caller).
    """
    try:
        with saver._cursor() as cur:
            cur.execute(
                "select count(*) as n from pg_class c "
                "join pg_namespace ns on ns.oid = c.relnamespace "
                "where ns.nspname = 'public' and c.relkind = 'r' and c.relname = any(%s)",
                (list(_CHECKPOINT_TABLES),),
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.debug("graph_checkpoint_probe_failed", error=repr(exc))
        return False
    count = int(row["n"] if isinstance(row, Mapping) else row[0]) if row else 0
    return count == len(_CHECKPOINT_TABLES)


def run(
    compiled: Any,
    state: Mapping[str, Any] | Any,
    *,
    thread_id: str,
    module: str = "",
    client_id: str | None = None,
    job_id: str = "",
    recursion_limit: int = 50,
    resume: Any = None,
) -> dict[str, Any]:
    """Invoke a compiled graph under one thread id, traced, returning its final state.

    ``resume`` carries a human decision back into a graph parked at ``interrupt()`` - the
    approval gate. Passing it resumes the EXISTING thread from its checkpoint; passing
    ``state`` starts or continues one. That is the whole human-in-the-loop mechanism:
    the graph parks, the review queue holds the item, and the operator's decision is
    injected here rather than polled for.

    ``recursion_limit`` is a runaway guard, not a capacity setting. A graph that needs
    more than 50 super-steps has a loop that does not terminate, and letting it spin is
    how a cost ceiling gets discovered by a bill.
    """
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": recursion_limit,
        "metadata": {
            "module": module,
            "client_id": client_id or "",
            "job_id": job_id,
            "thread_id": thread_id,
        },
    }
    payload: Any = state
    if resume is not None:
        from langgraph.types import Command

        # Verify the thread EXISTS before handing LangGraph a resume command. Without
        # this check a missing checkpoint silently becomes a fresh run - see
        # `GraphThreadMissing` for why that is the expensive failure mode rather than a
        # harmless one.
        if not _thread_exists(compiled, config):
            raise GraphThreadMissing(
                f"no checkpoint for thread {thread_id!r}: it was never started, or it "
                "ran on an in-memory checkpointer and did not survive the process. "
                "Resuming would re-run the graph from the beginning instead of applying "
                "the decision, so it is refused."
            )
        payload = Command(resume=resume)

    with tracing.span(
        f"graph.{module or 'run'}",
        module=module, client_id=client_id or "", job_id=job_id, thread_id=thread_id,
        resumed=resume is not None,
    ) as sp:
        result = compiled.invoke(payload, config=config)
        interrupts = _interrupts(result)
        sp.update(parked=bool(interrupts), interrupts=len(interrupts))

    logger.info(
        "graph_run",
        module=module, thread_id=thread_id, client_id=client_id or "-",
        parked=bool(_interrupts(result)),
    )
    return dict(result) if isinstance(result, Mapping) else result


def _thread_exists(compiled: Any, config: Mapping[str, Any]) -> bool:
    """Whether this thread has a checkpoint to resume from."""
    try:
        snapshot = compiled.get_state(config)
    except Exception as exc:
        logger.debug("graph_thread_probe_failed", error=repr(exc))
        return False
    # A never-started thread returns a snapshot whose values are empty and whose config
    # carries no checkpoint id. Checking both is deliberate: LangGraph has expressed
    # "nothing here" through each of them across versions.
    if getattr(snapshot, "values", None):
        return True
    created = (getattr(snapshot, "config", None) or {}).get("configurable", {})
    return bool(created.get("checkpoint_id"))


def _interrupts(result: Any) -> list[Any]:
    """The interrupts a run parked on, if any.

    LangGraph surfaces these under the ``__interrupt__`` key of the returned state. Read
    through a helper so callers ask ``did this park?`` rather than each knowing the key -
    a detail that has moved between LangGraph versions before.
    """
    if isinstance(result, Mapping):
        value = result.get("__interrupt__")
        if value:
            return list(value) if isinstance(value, list | tuple) else [value]
    return []


def parked(result: Mapping[str, Any] | Any) -> bool:
    """Whether a run stopped at a human-approval interrupt rather than completing."""
    return bool(_interrupts(result))


def interrupt_payload(result: Mapping[str, Any] | Any) -> Any:
    """What the graph handed the human when it parked (the review payload), or None."""
    found = _interrupts(result)
    if not found:
        return None
    first = found[0]
    return getattr(first, "value", first)


def node(name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a node function so it emits its own span and never swallows a failure.

    The no-internal-retry rule (§2) is enforced by NOT providing a retry here: this
    wrapper adds observability and nothing else. A node that fails propagates to the
    graph, which propagates to the job, which is the only layer with a retry budget and
    a dead letter.
    """

    def wrapped(state: Any, *args: Any, **kwargs: Any) -> Any:
        with tracing.span(f"node.{name}") as sp:
            out = fn(state, *args, **kwargs)
            if isinstance(out, Mapping):
                sp.update(keys=sorted(str(k) for k in out))
            return out

    wrapped.__name__ = getattr(fn, "__name__", name)
    wrapped.__doc__ = fn.__doc__
    return wrapped
