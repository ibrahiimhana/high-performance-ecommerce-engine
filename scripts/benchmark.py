"""
Latency benchmark — supports Req #10 (Benchmarking & Bottleneck Analysis).

Drives a single endpoint with a configurable number of total requests at a
configurable concurrency level, then prints percentile latencies and
throughput. Outputs in a markdown-friendly table so the result can be
pasted straight into BENCHMARK_REPORT.md.

Usage from inside a web container:

    python scripts/benchmark.py \
        --url http://nginx/api/catalog/products/1/ \
        --requests 1000 \
        --concurrency 30 \
        --label "baseline"
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


def time_one(session: requests.Session, url: str) -> tuple[int, float]:
    t0 = time.perf_counter()
    try:
        r = session.get(url, timeout=30)
        return r.status_code, (time.perf_counter() - t0) * 1000
    except Exception:
        return 0, (time.perf_counter() - t0) * 1000


def percentile(sorted_data, pct):
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_data) - 1)
    if f == c:
        return sorted_data[f]
    return sorted_data[f] + (sorted_data[c] - sorted_data[f]) * (k - f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--requests", type=int, default=1000)
    ap.add_argument("--concurrency", type=int, default=30)
    ap.add_argument("--label", default="run")
    ap.add_argument("--warmup", type=int, default=20,
                    help="warm-up requests (results discarded)")
    args = ap.parse_args()

    session = requests.Session()

    # Warm-up: prime caches, JIT, connection pool — keeps the first 20
    # requests out of the measurement window.
    for _ in range(args.warmup):
        try:
            session.get(args.url, timeout=10)
        except Exception:
            pass

    print(f"Starting benchmark label={args.label!r} url={args.url} "
          f"requests={args.requests} concurrency={args.concurrency}")

    latencies: list[float] = []
    status_counts: dict[int, int] = {}
    t_start = time.perf_counter()

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = [pool.submit(time_one, session, args.url)
                for _ in range(args.requests)]
        for f in as_completed(futs):
            code, lat = f.result()
            latencies.append(lat)
            status_counts[code] = status_counts.get(code, 0) + 1

    wall = time.perf_counter() - t_start
    latencies.sort()

    avg = statistics.mean(latencies)
    p50 = percentile(latencies, 50)
    p90 = percentile(latencies, 90)
    p95 = percentile(latencies, 95)
    p99 = percentile(latencies, 99)
    tput = len(latencies) / wall

    print(f"\n## Benchmark — {args.label}")
    print(f"- URL: `{args.url}`")
    print(f"- Total requests: {len(latencies)}  (concurrency {args.concurrency})")
    print(f"- Wall time: {wall:.2f} s")
    print(f"- Throughput: **{tput:.1f} req/s**")
    print(f"- Status codes: {status_counts}")
    print()
    print("| metric  | latency (ms) |")
    print("|---------|-------------:|")
    print(f"| avg     | {avg:8.2f}     |")
    print(f"| p50     | {p50:8.2f}     |")
    print(f"| p90     | {p90:8.2f}     |")
    print(f"| p95     | {p95:8.2f}     |")
    print(f"| p99     | {p99:8.2f}     |")
    print(f"| max     | {latencies[-1]:8.2f}     |")

    # Non-zero exit if anything errored
    bad = sum(c for code, c in status_counts.items() if code >= 500 or code == 0)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
