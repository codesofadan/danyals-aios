"""The publish path, end to end, against a REAL platform. Opt-in.

WHY THIS EXISTS. On 2026-08-30 this module published for the first time: three articles
live on dev.to, each carrying one followed link to the client's site. Nothing protected
that. Every unit test in the suite passed while `web2_properties.account_id` was never
written, which meant a correctly registered account resolved NO credential and every
placement silently bounced back to review - after the drafting spend. A defect that
survives the entire suite and only shows up against a live platform needs a test that
talks to a live platform.

SKIPPED BY DEFAULT. It costs a real post on a real account, so it runs only when
WEB2_LIVE_PUBLISH=1 and a Postgres DSN are both set. It is written to be safe to repeat:
it publishes to the platform passed in WEB2_LIVE_PLATFORM (default dev.to), and dev.to
posts created via the API can be left unpublished - see `_DRAFT_NOTE`.

WHAT IT ASSERTS, and why each one caught something real:
  * the placement binds an account          (it did not - the defect above)
  * the worker resolves that account's label (it read the wrong column)
  * the post URL comes back and RESOLVES     (a 201 is not a live page)
  * our link is ON the page                  (platforms strip and rewrite links)
  * `link_found` is True, not None           ("could not check" is not "checked")
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.integration

_DSN_KEYS = ("DATABASE_MIGRATE_URL", "DATABASE_ADMIN_URL", "DATABASE_URL")
_DRAFT_NOTE = "dev.to posts published through the API remain editable and can be unpublished."


def _enabled() -> bool:
    return os.environ.get("WEB2_LIVE_PUBLISH", "") == "1"


@pytest.fixture
def live() -> Any:
    if not _enabled():
        pytest.skip("live publish is opt-in: set WEB2_LIVE_PUBLISH=1 (it posts for real)")
    dsn = next((os.environ[k] for k in _DSN_KEYS if os.environ.get(k)), None)
    if not dsn:
        pytest.skip(f"no Postgres configured (set one of {', '.join(_DSN_KEYS)})")
    # The suite deliberately refuses to read backend/.env (conftest `_ignore_developer_dotenv`),
    # so a real vault key has to come from the ACTUAL environment. Without it the sealed
    # credential cannot be opened, `_publisher_for` swallows the error, and this test would
    # report "publisher unconfigured" - blaming the code for a missing key.
    if not os.environ.get("VAULT_MASTER_KEY"):
        pytest.skip("VAULT_MASTER_KEY must be exported to open the sealed credential")
    pytest.importorskip("psycopg_pool")
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    from app.db.database import clear_pools, set_pools

    pool = ConnectionPool(dsn, min_size=1, max_size=2, kwargs={"row_factory": dict_row}, open=True)
    try:
        set_pools(rls=pool, admin=pool)
        yield pool
    finally:
        clear_pools()
        pool.close()


def test_a_registered_account_publishes_and_the_link_is_verified_on_the_page(live: Any) -> None:
    from app.config import get_settings
    from app.db.database import privileged_connection
    from app.db.offpage_repo import ServiceOffpageStore
    from workers.tasks.offpage import execute_web2_publish

    platform = os.environ.get("WEB2_LIVE_PLATFORM", "dev.to")
    settings = get_settings()

    with privileged_connection() as cur:
        cur.execute(
            "select a.id, a.client_id, a.vault_label, c.name "
            "from public.web2_accounts a join public.clients c on c.id = a.client_id "
            "where a.platform = %s and a.health not in ('suspended','deleted') limit 1",
            (platform,),
        )
        account = cur.fetchone()
    if account is None:
        pytest.skip(f"no usable {platform} account is registered in this database")

    marker = uuid.uuid4().hex[:8]
    target = f"https://example.test/live-check-{marker}"
    body = (
        f"# Live publish check {marker}\n\n"
        "This post verifies the publishing path end to end: that a registered account "
        "resolves its credential, that the platform accepts the post, and that the "
        f"outbound link survives on the rendered page. [reference]({target})\n\n"
        f"_{_DRAFT_NOTE}_\n"
    )

    with privileged_connection() as cur:
        cur.execute(
            "insert into public.web2_properties "
            "(client_id, client_name, platform, anchor, target_url, topic, page_type, "
            " framework, source_pack, status, body_md, account_id) "
            "values (%s,%s,%s,'reference',%s,%s,'blog','PAS','{}'::jsonb,'publishing',%s,%s) "
            "returning id",
            (account["client_id"], account["name"], platform, target,
             f"live publish check {marker}", body, account["id"]),
        )
        web2_id = str(cur.fetchone()["id"])

    try:
        outcome = execute_web2_publish(ServiceOffpageStore(), settings, web2_id)
        with privileged_connection() as cur:
            cur.execute(
                "select status, post_url, error, link_found, link_rel, account_id "
                "from public.web2_properties where id = %s",
                (web2_id,),
            )
            row = dict(cur.fetchone())

        assert row["account_id"] is not None, (
            "the placement lost its account - the publish worker cannot find the credential"
        )
        assert row["status"] == "published", (
            f"publish failed: {row['error'] or outcome.reason}"
        )
        assert row["post_url"], "published with no URL"

        # A 201 is not a live page. Fetch what the platform actually rendered.
        import httpx

        page = httpx.get(row["post_url"], follow_redirects=True, timeout=40,
                         headers={"User-Agent": "Mozilla/5.0"})
        assert page.status_code == 200, f"{row['post_url']} -> {page.status_code}"
        assert target in page.text, "our link is not on the published page"

        assert row["link_found"] is True, (
            "link_found must be True, not None - 'could not check' is not 'checked and fine'"
        )
    finally:
        # A test that leaves a live article on the client's account is not a clean test.
        # dev.to has no delete endpoint, so unpublishing is the strongest cleanup there is:
        # it drops the post from the feed and returns 404 to visitors.
        _unpublish_best_effort(platform, web2_id)
        with privileged_connection() as cur:  # never leave a probe row behind
            cur.execute("delete from public.web2_doc_fingerprints where web2_id = %s", (web2_id,))
            cur.execute("delete from public.web2_properties where id = %s", (web2_id,))


def _unpublish_best_effort(platform: str, web2_id: str) -> None:
    """Retract the test post. Never raises - cleanup must not mask the real assertion."""
    if platform != "dev.to":
        return
    try:
        import json

        import httpx

        from app.db.database import privileged_connection
        from app.services.vault import open_sealed

        with privileged_connection() as cur:
            cur.execute(
                "select external_id from public.web2_properties where id = %s", (web2_id,)
            )
            row = cur.fetchone()
            external_id = str((row or {}).get("external_id") or "")
            cur.execute(
                "select v.secret_sealed from public.web2_accounts a "
                "join public.vault_keys v "
                "  on v.label = a.vault_label and v.provider = a.vault_provider "
                "where a.platform = 'dev.to' limit 1"
            )
            secret = cur.fetchone()
        if not external_id or secret is None:
            return
        api_key = json.loads(open_sealed(bytes(secret["secret_sealed"])))["api_key"]
        httpx.put(
            f"https://dev.to/api/articles/{external_id}",
            headers={"api-key": api_key, "content-type": "application/json"},
            json={"article": {"published": False}},
            timeout=30,
        )
    except Exception:
        pass
