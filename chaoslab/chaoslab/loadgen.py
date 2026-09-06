import argparse
import asyncio
import statistics
import time

import httpx

PROFILES = {
    "normal": (20, 0.15),
    "burst": (30, 0.02),
    "sustained": (100, 0.05),
}


async def run_profile(base_url: str, profile: str, path: str) -> dict[str, float | int]:
    requests, delay = PROFILES[profile]
    latencies: list[float] = []
    errors = 0
    async with httpx.AsyncClient(timeout=15) as client:
        for _ in range(requests):
            start = time.perf_counter()
            try:
                response = await client.get(f"{base_url}{path}")
                if response.status_code >= 400:
                    errors += 1
            except httpx.HTTPError:
                errors += 1
            latencies.append((time.perf_counter() - start) * 1000)
            await asyncio.sleep(delay)
    ordered = sorted(latencies)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return {
        "requests": requests,
        "errors": errors,
        "mean_ms": round(statistics.mean(latencies), 3),
        "p95_ms": round(ordered[p95_index], 3),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--profile", choices=PROFILES, default="normal")
    parser.add_argument("--path", default="/checkout")
    args = parser.parse_args()
    print(await run_profile(args.base_url, args.profile, args.path))


if __name__ == "__main__":
    asyncio.run(main())
