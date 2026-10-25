"""Small authenticated, read-only API concurrency check for a running local instance.

Set LOAD_TEST_EMAIL and LOAD_TEST_PASSWORD in the shell. The test logs in once,
then simulates concurrent authenticated readers; it does not create or mutate records.
"""
from __future__ import annotations

import asyncio
import os
import statistics
import time
from collections import defaultdict

import httpx


API_BASE = os.getenv('LOAD_TEST_API_BASE', 'http://127.0.0.1:8000/api/v1').rstrip('/')
API_ROOT = API_BASE[:-len('/api/v1')] if API_BASE.endswith('/api/v1') else API_BASE
PORTAL = os.getenv('LOAD_TEST_PORTAL', 'admin')
EMAIL = os.getenv('LOAD_TEST_EMAIL', '')
PASSWORD = os.getenv('LOAD_TEST_PASSWORD', '')
USERS = int(os.getenv('LOAD_TEST_USERS', '100'))
ROUNDS = int(os.getenv('LOAD_TEST_ROUNDS', '5'))
READ_PATHS = (
    '/health',
    '/dashboard/bureau',
    '/fdrs',
    '/workflows',
    '/admin/operations/health',
    '/admin/ml/gates',
)


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int((percent / 100) * len(ordered) + 0.999) - 1))
    return ordered[index]


async def main() -> None:
    if not EMAIL or not PASSWORD:
        raise SystemExit('Set LOAD_TEST_EMAIL and LOAD_TEST_PASSWORD; credentials are never printed.')
    if not 1 <= USERS <= 500 or not 1 <= ROUNDS <= 100:
        raise SystemExit('Use 1–500 users and 1–100 rounds.')

    limits = httpx.Limits(max_connections=USERS, max_keepalive_connections=USERS)
    timeout = httpx.Timeout(20.0, connect=5.0)
    async with httpx.AsyncClient(base_url=API_BASE, limits=limits, timeout=timeout) as client:
        response = await client.post(f'/auth/login/{PORTAL}', json={'email': EMAIL, 'password': PASSWORD})
        if response.status_code != 200 or response.json().get('mfa_required'):
            raise SystemExit(f'Load-test login failed with HTTP {response.status_code}; no load was sent.')

        samples: dict[str, list[float]] = defaultdict(list)
        failures: dict[str, int] = defaultdict(int)
        start = time.perf_counter()

        async def request(path: str) -> None:
            tick = time.perf_counter()
            try:
                target = f'{API_ROOT}/health' if path == '/health' else path
                result = await client.get(target)
                elapsed = (time.perf_counter() - tick) * 1000
                samples[path].append(elapsed)
                if result.status_code >= 400:
                    failures[f'{path} HTTP {result.status_code}'] += 1
            except Exception as exc:
                failures[f'{path} {type(exc).__name__}'] += 1

        for round_index in range(ROUNDS):
            paths = [READ_PATHS[(user_index + round_index) % len(READ_PATHS)] for user_index in range(USERS)]
            await asyncio.gather(*(request(path) for path in paths))

        elapsed_total = time.perf_counter() - start
        print(f'Concurrency: {USERS} authenticated readers; rounds: {ROUNDS}; methods: GET only')
        print(f'Total requests: {sum(map(len, samples.values())) + sum(failures.values())}; elapsed: {elapsed_total:.2f}s')
        for path, values in sorted(samples.items()):
            print(f'{path}: n={len(values)} mean={statistics.mean(values):.1f}ms '
                  f'p50={percentile(values, 50):.1f}ms p95={percentile(values, 95):.1f}ms '
                  f'p99={percentile(values, 99):.1f}ms max={max(values):.1f}ms')
        if failures:
            print('Failures:')
            for label, count in sorted(failures.items()):
                print(f'  {label}: {count}')
        else:
            print('Failures: 0')
        print(f'Throughput: {(USERS * ROUNDS) / elapsed_total:.1f} requests/second')
        if failures:
            raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
