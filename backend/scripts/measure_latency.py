"""Measure what the API actually costs in TIME, under concurrency, before tuning a timeout.

WHY THIS EXISTS. The reverse proxy in front of production carries a 180s `proxyTimeout`
because a synchronous call - content research, a site-design analysis - can outlive the
default 30s. That number was set by a failure, not by a measurement: nobody knew the real
distribution, so nobody knew whether 180 was generous or already too tight, and a client
sprint of thirty pages had never been timed at all.

The decision on the table was "measure first, then raise the timeout". This is the measure.

WHAT IT MEASURES, AND WHAT IT DELIBERATELY DOES NOT SPEND.

  * READ ENDPOINTS, concurrently, at a concurrency you choose: p50 / p95 / max wall-clock
    per endpoint. These are free, repeatable, and they are where a proxy timeout bites a
    dashboard first - a list that takes 40s under load is the same outage as one that fails.
  * THE PAID SYNCHRONOUS PATHS ARE NOT CALLED. Timing them by running them would spend real
    money per sample, and a sample of one is not a distribution. Their durations are read
    from what the platform ALREADY RECORDED (`job_runs.started_at/finished_at`, and the
    content jobs' own timestamps), so the recommendation comes from real runs.
  * The recommendation is stated as arithmetic over the measurements, never as a round
    number somebody liked.

Usage (the local stack, an owner token):

    ./.venv/Scripts/python scripts/measure_latency.py --base http://127.0.0.1:8010 \\
        --token "$TOKEN" --concurrency 12 --rounds 3

Exit code is 0 unless a request FAILED (a non-2xx or a transport error); a slow response is
data, not an error, because deciding what "too slow" means is the point of running this.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

#: Read endpoints worth timing: the ones a dashboard screen waits on, plus the two that do
#: real work in-request (the report build and the comparison read every finding of two runs).
DEFAULT_PATHS: tuple[str, ...] = (
    "/api/v1/audits",
    "/api/v1/audits/stats",
    "/api/v1/content/jobs",
    "/api/v1/content/jobs/stats",
    "/api/v1/content/batches",
    "/api/v1/integrations/readiness",
    "/api/v1/cost/dial",
    "/api/v1/activity",
)


@dataclass
class Sample:
    path: str
    ms: list[float] = field(default_factory=list)
    failures: int = 0
    statuses: dict[int, int] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        ordered = sorted(self.ms)
        return {
            "path": self.path,
            "n": len(ordered),
            "failures": self.failures,
            "p50_ms": round(statistics.median(ordered), 1) if ordered else None,
            "p95_ms": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 1) if ordered else None,
            "max_ms": round(ordered[-1], 1) if ordered else None,
            "statuses": self.statuses,
        }


async def _one(client: httpx.AsyncClient, sample: Sample, path: str) -> None:
    started = time.perf_counter()
    try:
        resp = await client.get(path)
    except Exception as exc:  # a transport error is a failure, and it is named
        sample.failures += 1
        print(f"  ! {path} {type(exc).__name__}", file=sys.stderr)
        return
    sample.ms.append((time.perf_counter() - started) * 1000)
    sample.statuses[resp.status_code] = sample.statuses.get(resp.status_code, 0) + 1
    if resp.status_code >= 300:
        sample.failures += 1


async def measure_reads(
    base: str, token: str, paths: tuple[str, ...], *, concurrency: int, rounds: int
) -> list[dict[str, Any]]:
    """Every path hit ``concurrency * rounds`` times, all paths in flight together.

    Hitting them TOGETHER is the point: one endpoint measured alone tells you about the
    endpoint, and what a sprint does to a dashboard is a question about the pool.
    """
    samples = {p: Sample(p) for p in paths}
    limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency)
    timeout = httpx.Timeout(300.0)
    async with httpx.AsyncClient(
        base_url=base, headers={"authorization": f"Bearer {token}"}, limits=limits, timeout=timeout
    ) as client:
        for round_no in range(rounds):
            print(f"round {round_no + 1}/{rounds} at concurrency {concurrency}...")
            tasks = [
                _one(client, samples[p], p) for p in paths for _ in range(concurrency)
            ]
            await asyncio.gather(*tasks)
    return [samples[p].summary() for p in paths]


def recorded_durations(dsn: str) -> dict[str, Any]:
    """What the platform already measured about its own long work. No new spend.

    Two sources, because they answer different halves: ``job_runs`` times every job that
    went through the job contract, and the content jobs' own row timestamps cover the
    pipeline runs (which is the work a sprint actually queues).
    """
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:  # pragma: no cover - psycopg is a hard dependency of the app
        return {"error": "psycopg is not importable"}

    out: dict[str, Any] = {}
    try:
        with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute(
                """select job_name,
                          count(*)::int as runs,
                          round(avg(extract(epoch from (finished_at - started_at)))::numeric, 1)
                            as avg_s,
                          round(max(extract(epoch from (finished_at - started_at)))::numeric, 1)
                            as max_s
                   from public.job_runs
                   where started_at is not null and finished_at is not null
                   group by job_name order by max_s desc nulls last limit 20"""
            )
            out["job_runs"] = [dict(r) for r in cur.fetchall()]
            cur.execute(
                """select status,
                          count(*)::int as pages,
                          round(avg(extract(epoch from (updated_at - created_at)))::numeric, 1)
                            as avg_s,
                          round(max(extract(epoch from (updated_at - created_at)))::numeric, 1)
                            as max_s
                   from public.content_jobs
                   where updated_at is not null
                   group by status order by max_s desc nulls last"""
            )
            out["content_jobs"] = [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return out


def recommend(reads: list[dict[str, Any]], recorded: dict[str, Any]) -> list[str]:
    """Say what the numbers imply, with the arithmetic shown.

    A recommendation with no derivation is the thing this script exists to replace.
    """
    lines: list[str] = []
    worst = max((r for r in reads if r["max_ms"]), key=lambda r: r["max_ms"], default=None)
    if worst:
        lines.append(
            f"slowest read under load: {worst['path']} at {worst['max_ms']}ms max "
            f"(p95 {worst['p95_ms']}ms) - a read that slow is a dashboard problem before it "
            "is a proxy one"
        )
    longest = 0.0
    for row in recorded.get("content_jobs", []) or []:
        longest = max(longest, float(row.get("max_s") or 0))
    for row in recorded.get("job_runs", []) or []:
        longest = max(longest, float(row.get("max_s") or 0))
    if longest:
        # Headroom of 2x the longest OBSERVED run, because the observed max is a sample of
        # the distribution's middle, not its tail.
        lines.append(
            f"longest recorded background run: {longest:.0f}s -> a synchronous caller would "
            f"need ~{longest * 2:.0f}s of headroom (2x observed max); anything of that order "
            "belongs on the queue, not in a request"
        )
    else:
        lines.append(
            "no completed runs are recorded yet, so nothing can be said about the long paths - "
            "run real work first; this is the honest answer, not a zero"
        )
    return lines


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8010")
    ap.add_argument("--token", required=True, help="a staff bearer token")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--dsn", default=None, help="DATABASE_ADMIN_URL; omit to read Settings")
    ap.add_argument("--json", action="store_true", help="machine-readable output only")
    args = ap.parse_args()

    reads = await measure_reads(
        args.base, args.token, DEFAULT_PATHS,
        concurrency=args.concurrency, rounds=args.rounds,
    )
    dsn = args.dsn
    if not dsn:
        from app.config import get_settings

        dsn = get_settings().database_admin_url or ""
    recorded = recorded_durations(dsn) if dsn else {"error": "no DSN"}
    advice = recommend(reads, recorded)

    if args.json:
        print(json.dumps({"reads": reads, "recorded": recorded, "advice": advice}, default=str))
    else:
        print("\n--- reads under concurrency", args.concurrency, "---")
        for row in reads:
            print(
                f"  {row['path']:<38} n={row['n']:<4} p50={row['p50_ms']:<8} "
                f"p95={row['p95_ms']:<8} max={row['max_ms']:<8} failures={row['failures']}"
            )
        print("\n--- what the platform already recorded ---")
        for key in ("job_runs", "content_jobs"):
            for row in recorded.get(key, []) or []:
                print(f"  {key}: {row}")
        if recorded.get("error"):
            print("  (unavailable:", recorded["error"], ")")
        print("\n--- what that implies ---")
        for line in advice:
            print("  *", line)

    failed = sum(r["failures"] for r in reads)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
