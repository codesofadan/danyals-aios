"""P6.2: re-hosting a client's own logo and photographs.

The URLs come off a page WE DID NOT WRITE, which is what makes the SSRF contract here
load-bearing rather than ceremonial: a client's site can carry an <img> pointing at
169.254.169.254, and fetching it would make this worker a proxy into the private
network.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.services.brand_assets import (
    MAX_ASSET_BYTES,
    FetchedAsset,
    SkippedAsset,
    fetch_asset,
    store_asset,
)

pytestmark = pytest.mark.unit

PNG = b"\x89PNG\r\n\x1a\n" + b"payload-bytes"
JPG = b"\xff\xd8\xff" + b"jpeg-bytes"
SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"></svg>'


class _Fetcher:
    """Records every URL it is asked for, so a test can prove the guard ran FIRST."""

    def __init__(self, status: int = 200, content_type: str = "image/png",
                 body: bytes = PNG, result: object = "use-fields") -> None:
        self.status, self.content_type, self.body = status, content_type, body
        self.result = result
        self.asked: list[str] = []

    def fetch(self, url: str, *, timeout: float) -> tuple[int, str, bytes] | None:
        self.asked.append(url)
        if self.result is None:
            return None
        return (self.status, self.content_type, self.body)


class TestTheGuardRunsBeforeTheNetwork:
    @pytest.mark.parametrize(
        "url",
        ["http://169.254.169.254/latest/meta-data/", "http://localhost:8000/logo.png",
         "http://127.0.0.1/logo.png", "http://10.0.0.5/logo.png",
         "http://[::1]/logo.png", "http://192.168.1.1/x.png"],
    )
    def test_a_private_address_is_never_fetched(self, url: str) -> None:
        """Not "fetched and discarded" - never reached. The assertion is on the
        fetcher's call log, because a guard that runs after the request has already
        made the request."""
        f = _Fetcher()
        result = fetch_asset(url, fetcher=f)
        assert isinstance(result, SkippedAsset)
        assert f.asked == [], "the guard must run before any connection is opened"

    @pytest.mark.parametrize(
        "url", ["file:///etc/passwd", "data:image/png;base64,AAAA", "ftp://x.test/a.png", ""]
    )
    def test_non_http_schemes_are_refused(self, url: str) -> None:
        """`file:` would read our own disk; `data:` is not an asset to re-host."""
        f = _Fetcher()
        assert isinstance(fetch_asset(url, fetcher=f), SkippedAsset)
        assert f.asked == []

    def test_a_refusal_is_a_value_not_an_exception(self) -> None:
        """One unreachable image on a client's page must not lose the other forty."""
        result = fetch_asset("http://127.0.0.1/a.png", fetcher=_Fetcher())
        assert isinstance(result, SkippedAsset) and result.reason


@pytest.fixture
def public_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the DNS half of the guard for tests about TYPE and SIZE, not reachability.

    Deliberately NOT applied to `TestTheGuardRunsBeforeTheNetwork`: those assert the
    real guard, and every address they use is an IP literal or resolves locally, so
    they need no DNS and must exercise the genuine article.
    """
    import app.services.brand_assets as ba

    monkeypatch.setattr(ba, "validate_public_host", lambda url: url)


@pytest.mark.usefixtures("public_host")
class TestWhatWeAreWillingToStore:
    def test_a_good_png_is_accepted_and_hashed(self) -> None:
        result = fetch_asset("https://x.test/logo.png", fetcher=_Fetcher())
        assert isinstance(result, FetchedAsset)
        assert result.sha256 == hashlib.sha256(PNG).hexdigest()
        assert result.extension == ".png"

    @pytest.mark.parametrize(
        ("content_type", "body", "ext"),
        [("image/jpeg", JPG, ".jpg"), ("image/svg+xml", SVG, ".svg"),
         ("image/png", PNG, ".png")],
    )
    def test_the_formats_a_real_site_serves(self, content_type: str, body: bytes, ext: str) -> None:
        result = fetch_asset(
            "https://x.test/a", fetcher=_Fetcher(content_type=content_type, body=body)
        )
        assert isinstance(result, FetchedAsset) and result.extension == ext

    def test_an_html_error_page_served_as_200_is_not_stored_as_an_image(self) -> None:
        """Otherwise it lands in the kit and publishes as a broken image."""
        f = _Fetcher(content_type="text/html", body=b"<html>404 not found</html>")
        result = fetch_asset("https://x.test/logo.png", fetcher=f)
        assert isinstance(result, SkippedAsset)
        assert "content-type" in result.reason

    def test_the_bytes_must_match_what_the_header_claimed(self) -> None:
        """Content-Type is whatever the remote server felt like saying. The magic
        bytes are the evidence."""
        f = _Fetcher(content_type="image/png", body=b"<html>not a png at all</html>")
        result = fetch_asset("https://x.test/logo.png", fetcher=f)
        assert isinstance(result, SkippedAsset)
        assert "do not match" in result.reason

    def test_an_empty_body_is_refused(self) -> None:
        result = fetch_asset("https://x.test/a.png", fetcher=_Fetcher(body=b""))
        assert isinstance(result, SkippedAsset)

    def test_a_non_200_is_refused(self) -> None:
        result = fetch_asset("https://x.test/a.png", fetcher=_Fetcher(status=404))
        assert isinstance(result, SkippedAsset) and "404" in result.reason

    def test_an_oversized_asset_is_refused(self) -> None:
        big = b"\x89PNG\r\n\x1a\n" + b"x" * (MAX_ASSET_BYTES + 1)
        result = fetch_asset("https://x.test/a.png", fetcher=_Fetcher(body=big))
        assert isinstance(result, SkippedAsset)

    def test_a_transport_failure_degrades(self) -> None:
        result = fetch_asset("https://x.test/a.png", fetcher=_Fetcher(result=None))
        assert isinstance(result, SkippedAsset)


@pytest.mark.usefixtures("public_host")
class TestStorage:
    def test_the_filename_is_the_content_hash(self, tmp_path: Path) -> None:
        """Identical bytes are always the same file, so two workers racing on one
        asset cannot corrupt it."""
        asset = fetch_asset("https://x.test/logo.png", fetcher=_Fetcher())
        assert isinstance(asset, FetchedAsset)
        key = store_asset(asset, tmp_path)
        assert key == f"{asset.sha256}.png"
        assert (tmp_path / key).read_bytes() == PNG

    def test_storing_the_same_bytes_twice_is_a_no_op(self, tmp_path: Path) -> None:
        asset = fetch_asset("https://x.test/logo.png", fetcher=_Fetcher())
        assert isinstance(asset, FetchedAsset)
        first = store_asset(asset, tmp_path)
        second = store_asset(asset, tmp_path)
        assert first == second
        assert len(list(tmp_path.iterdir())) == 1

    def test_the_same_logo_from_two_urls_is_one_file(self, tmp_path: Path) -> None:
        """A logo on every captured page is fetched once and stored once - which is
        the whole reason the table is content-addressed."""
        a = fetch_asset("https://x.test/logo.png", fetcher=_Fetcher())
        b = fetch_asset("https://y.test/assets/logo.png", fetcher=_Fetcher())
        assert isinstance(a, FetchedAsset) and isinstance(b, FetchedAsset)
        store_asset(a, tmp_path)
        store_asset(b, tmp_path)
        assert len(list(tmp_path.iterdir())) == 1

    def test_the_root_is_created_if_absent(self, tmp_path: Path) -> None:
        asset = fetch_asset("https://x.test/logo.png", fetcher=_Fetcher())
        assert isinstance(asset, FetchedAsset)
        store_asset(asset, tmp_path / "deep" / "nested")
        assert (tmp_path / "deep" / "nested").is_dir()


def test_a_query_string_is_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    """Asset URLs can carry signed tokens; a log line is a durable copy of them."""
    from app.services.brand_assets import _safe

    assert _safe("https://x.test/a.png?token=SECRET123") == "https://x.test/a.png"


# --------------------------------------------------------------------------- #
# The whole flow: captured URLs -> stored, deduped, recorded
# --------------------------------------------------------------------------- #
class _Recorder:
    """Stands in for `ContentPlanningStore.record_brand_asset`, including its dedup
    contract: None means those bytes were already held."""

    def __init__(self, *, raises: bool = False) -> None:
        self.rows: list[dict[str, object]] = []
        self.seen: set[str] = set()
        self.raises = raises

    def record_brand_asset(
        self, *, kit_id: str, kind: str, source_url: str, stored_key: str = "",
        sha256: str = "", width: int | None = None, height: int | None = None,
    ) -> str | None:
        if self.raises:
            raise RuntimeError("db gone")
        if sha256 in self.seen:
            return None
        self.seen.add(sha256)
        self.rows.append({"kind": kind, "source_url": source_url, "key": stored_key})
        return f"asset-{len(self.rows)}"


@pytest.mark.usefixtures("public_host")
class TestRehostingAKitsAssets:
    def _run(self, urls: list[tuple[str, str]], tmp_path: Path, **kw: object) -> object:
        from app.services.brand_assets import rehost_assets

        return rehost_assets(
            urls, kit_id="kit-1", root=tmp_path,
            fetcher=kw.pop("fetcher", None) or _Fetcher(),
            recorder=kw.pop("recorder", None) or _Recorder(),
        )

    def test_the_analyzer_kind_is_translated_to_the_enum(self, tmp_path: Path) -> None:
        """`site_analyzer` says "image"; the enum says "photo". This is the seam that
        raised InvalidTextRepresentation from inside a worker."""
        recorder = _Recorder()
        self._run([("https://x.test/team.jpg", "image")], tmp_path, recorder=recorder)
        assert recorder.rows[0]["kind"] == "photo"

    def test_a_logo_stays_a_logo(self, tmp_path: Path) -> None:
        recorder = _Recorder()
        self._run([("https://x.test/logo.png", "logo")], tmp_path, recorder=recorder)
        assert recorder.rows[0]["kind"] == "logo"

    def test_the_same_logo_from_two_pages_is_recorded_once(self, tmp_path: Path) -> None:
        recorder = _Recorder()
        report = self._run(
            [("https://x.test/logo.png", "logo"), ("https://y.test/logo.png", "logo")],
            tmp_path, recorder=recorder,
        )
        assert len(report.stored) == 1 and len(report.deduped) == 1  # type: ignore[attr-defined]
        assert len(recorder.rows) == 1

    def test_one_bad_asset_does_not_lose_the_good_ones(self, tmp_path: Path) -> None:
        """A client's page having one unreachable image must not lose the other forty.
        A partial re-host is worth far more than an exception."""
        class Mixed:
            def __init__(self) -> None:
                self.n = 0

            def fetch(self, url: str, *, timeout: float) -> tuple[int, str, bytes] | None:
                self.n += 1
                if "bad" in url:
                    return None
                return (200, "image/png", PNG + str(self.n).encode())

        report = self._run(
            [("https://x.test/a.png", "logo"), ("https://x.test/bad.png", "image"),
             ("https://x.test/c.png", "image")],
            tmp_path, fetcher=Mixed(),
        )
        assert len(report.stored) == 2 and len(report.skipped) == 1  # type: ignore[attr-defined]

    def test_every_url_is_accounted_for(self, tmp_path: Path) -> None:
        """A silent skip is a client's own photograph quietly replaced by a generated
        stock image on fifty pages."""
        report = self._run(
            [("https://x.test/a.png", "logo"), ("http://127.0.0.1/b.png", "image"),
             ("https://x.test/c.png", "nonsense_kind")],
            tmp_path,
        )
        assert report.attempted == 3  # type: ignore[attr-defined]
        assert any("nonsense_kind" in n for n in report.notes())  # type: ignore[attr-defined]

    def test_an_unmapped_kind_is_skipped_not_raised(self, tmp_path: Path) -> None:
        report = self._run([("https://x.test/a.png", "banner")], tmp_path)
        assert len(report.skipped) == 1  # type: ignore[attr-defined]

    def test_a_recorder_failure_degrades_rather_than_raising(self, tmp_path: Path) -> None:
        report = self._run(
            [("https://x.test/a.png", "logo")], tmp_path, recorder=_Recorder(raises=True)
        )
        assert len(report.skipped) == 1  # type: ignore[attr-defined]
        assert "could not record" in report.skipped[0].reason  # type: ignore[attr-defined]

    def test_an_empty_list_is_not_an_error(self, tmp_path: Path) -> None:
        report = self._run([], tmp_path)
        assert report.attempted == 0 and report.notes() == ()  # type: ignore[attr-defined]
