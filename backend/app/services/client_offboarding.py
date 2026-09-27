"""Leaving a client means leaving completely: withdraw, delete, and say what was destroyed.

WHAT WAS WRONG. ``DELETE /clients/{id}`` removes the client row, and the audits table links
with ``on delete set null`` (0008) - deliberately, so the job ledger survives a client being
removed. The consequence nobody had looked at: the audits stay, and so does any PUBLIC PAGE
they published. A withdrawn client's report remained openable by anyone holding the URL,
their generated pages kept sitting on disk, and there was no answer at all to "delete my
data" beyond deleting one row.

THE SHAPE OF THE FIX, and it is two operations rather than one:

    preview()   what WOULD be destroyed, counted. Nothing is touched.
    purge()     do it: withdraw every published page, delete the artifacts, remove the rows.

Two, because a destructive action an operator cannot inspect first is one they will avoid
using - and then the data stays anyway. The preview is also what the confirmation dialog
renders, so the number in front of the operator is the number the purge will act on.

WHAT IS DELIBERATELY NOT DELETED:

  * THE COST LEDGER. ``cost_log`` is the agency's own financial record of money it actually
    spent; a client leaving does not un-spend it, and a books entry that vanishes with its
    subject is not a book. It carries no client-supplied content - a feature key, a
    provider, an amount - so keeping it discloses nothing about them.
  * THE ACTIVITY LOG. Same reason, plus it is append-only by design (invariant #10): it is
    the record of what staff did, not of the client's data.
  * SHARED CONTENT IMAGES. Generated images are stored under a CONTENT-HASH filename, so two
    clients whose pages contain the same picture share one file. Deleting by hash would
    break another client's live page, so images are left and reported as such rather than
    silently skipped. This is a known limit, stated rather than hidden.

Owner-only at the route, and every count it reports is measured, not estimated.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.db.database import privileged_connection
from app.logging_setup import get_logger

logger = get_logger("services.client_offboarding")


@dataclass(slots=True)
class OffboardPlan:
    """What offboarding this client will destroy. Every number is a count of real rows."""

    client_id: str
    client_name: str = ""
    audits: int = 0
    published_pages: int = 0
    content_jobs: int = 0
    published_content: int = 0
    artifact_dirs: int = 0
    #: Things that will NOT be removed, in words the operator can read out.
    kept: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "clientId": self.client_id,
            "client": self.client_name,
            "audits": self.audits,
            "publishedPages": self.published_pages,
            "contentJobs": self.content_jobs,
            "publishedContent": self.published_content,
            "artifactDirs": self.artifact_dirs,
            "kept": self.kept,
        }


@dataclass(slots=True)
class OffboardResult:
    """What was actually destroyed, measured after the fact."""

    client_id: str
    client_name: str = ""
    pages_withdrawn: int = 0
    audits_deleted: int = 0
    content_jobs_deleted: int = 0
    artifact_dirs_removed: int = 0
    client_deleted: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "clientId": self.client_id,
            "client": self.client_name,
            "pagesWithdrawn": self.pages_withdrawn,
            "auditsDeleted": self.audits_deleted,
            "contentJobsDeleted": self.content_jobs_deleted,
            "artifactDirsRemoved": self.artifact_dirs_removed,
            "clientDeleted": self.client_deleted,
            "notes": self.notes,
        }


#: What offboarding never removes, and why - shown to the operator BEFORE they confirm, so
#: "delete everything" cannot be read as a promise the platform does not keep.
KEPT_ALWAYS: tuple[str, ...] = (
    "the cost ledger (the agency's own record of money it spent; it holds no client content)",
    "the activity log (append-only by design; it records what staff did, not client data)",
    "generated images shared with another client's pages (stored by content hash, so one "
    "file can serve two clients)",
)


def preview(client_id: str) -> OffboardPlan:
    """Count what offboarding would destroy. Touches nothing.

    This is what the confirmation dialog renders, so the numbers an operator approves are
    the numbers the purge acts on - not an estimate written beside it.
    """
    plan = OffboardPlan(client_id=client_id, kept=list(KEPT_ALWAYS))
    with privileged_connection() as cur:
        cur.execute("select name from public.clients where id = %s::uuid", (client_id,))
        row = cur.fetchone()
        plan.client_name = str((row or {}).get("name") or "")

        cur.execute(
            "select count(*)::int as n, "
            "  count(*) filter (where artifact_dir is not null and artifact_dir <> '')::int"
            "    as dirs "
            "from public.audits where client_id = %s::uuid",
            (client_id,),
        )
        got = cur.fetchone() or {}
        plan.audits = int(got.get("n") or 0)
        plan.artifact_dirs = int(got.get("dirs") or 0)

        cur.execute(
            """select count(*)::int as n from public.public_audit_pages p
               join public.audits a on a.id = p.audit_id
               where a.client_id = %s::uuid and p.published""",
            (client_id,),
        )
        plan.published_pages = int((cur.fetchone() or {}).get("n") or 0)

        cur.execute(
            "select count(*)::int as n, "
            "  count(*) filter (where wp_post_id is not null)::int as live "
            "from public.content_jobs where client_id = %s::uuid",
            (client_id,),
        )
        got = cur.fetchone() or {}
        plan.content_jobs = int(got.get("n") or 0)
        plan.published_content = int(got.get("live") or 0)

    if plan.published_content:
        # The pages on the CLIENT'S OWN SITE are theirs and are not ours to remove. Saying
        # so is the difference between an operator who knows to unpublish them and one who
        # believes the platform did.
        plan.kept.append(
            f"{plan.published_content} page(s) already published to the client's own "
            "website - those live on their site, not ours, and only they can remove them"
        )
    return plan


def purge(client_id: str, *, artifact_root: str | None = None) -> OffboardResult:
    """Withdraw, delete, remove. Returns what was actually destroyed.

    ORDER MATTERS AND IS DELIBERATE:

      1. WITHDRAW the public pages first. If anything later fails, the links are already
         dead - which is the one consequence that is visible to the outside world, and the
         one an operator most needs to be certain of.
      2. Remove artifacts from disk, reading the paths BEFORE the rows go.
      3. Delete the audits and content jobs, then the client row.

    Artifact removal is best-effort per directory: a file the OS will not release must not
    leave a client's rows in place, because the rows are the part that keeps the platform
    rendering their data. Anything skipped is reported in ``notes`` rather than swallowed.
    """
    result = OffboardResult(client_id=client_id)
    with privileged_connection() as cur:
        cur.execute("select name from public.clients where id = %s::uuid", (client_id,))
        row = cur.fetchone()
        result.client_name = str((row or {}).get("name") or "")

        # 1. the links the outside world can open.
        cur.execute(
            """update public.public_audit_pages p set published = false
               where p.published and p.audit_id in (
                 select id from public.audits where client_id = %s::uuid
               )""",
            (client_id,),
        )
        result.pages_withdrawn = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

        # 2. the artifact directories, read before the rows that name them.
        cur.execute(
            "select artifact_dir from public.audits "
            "where client_id = %s::uuid and artifact_dir is not null and artifact_dir <> ''",
            (client_id,),
        )
        dirs = [str(r["artifact_dir"]) for r in cur.fetchall()]

    root = Path(artifact_root).resolve() if artifact_root else None
    for raw in dirs:
        target = Path(raw)
        if root is not None:
            # TRAVERSAL GUARD, the same rule the artifact stores use: a path that does not
            # resolve inside the configured root is not ours to delete, however it got into
            # the column.
            try:
                resolved = target.resolve()
                resolved.relative_to(root)
            except (OSError, ValueError):
                result.notes.append(f"skipped an artifact path outside the store: {raw}")
                continue
        try:
            if target.exists():
                shutil.rmtree(target)
                result.artifact_dirs_removed += 1
        except OSError as exc:
            result.notes.append(f"could not remove {raw} ({type(exc).__name__})")

    with privileged_connection() as cur:
        # 3. the rows. Audits and content jobs are deleted explicitly rather than left to a
        # cascade, because both link with ON DELETE SET NULL by design - that is what keeps
        # the job ledger intact when a client is merely removed, and it is exactly what
        # would leave their data behind here.
        cur.execute("delete from public.audits where client_id = %s::uuid", (client_id,))
        result.audits_deleted = max(cur.rowcount, 0)
        cur.execute("delete from public.content_jobs where client_id = %s::uuid", (client_id,))
        result.content_jobs_deleted = max(cur.rowcount, 0)
        cur.execute("delete from public.clients where id = %s::uuid", (client_id,))
        result.client_deleted = cur.rowcount > 0

    logger.info(
        "client_offboarded",
        client_id=client_id,
        pages_withdrawn=result.pages_withdrawn,
        audits=result.audits_deleted,
        content=result.content_jobs_deleted,
        dirs=result.artifact_dirs_removed,
    )
    return result
