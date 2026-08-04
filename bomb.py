#!/usr/bin/env python3
"""
BoomBench (safe edition)
A fun, resilient CLI for polite load testing of systems you own or are authorized to test.
"""

from __future__ import annotations

import argparse
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import urlparse

import requests


# ------------------------------ Safety/limits ------------------------------

# Absolute global safety caps (never exceeded in any mode)
ABS_MAX_REQUESTS = 20_000
ABS_MAX_THREADS = 400
ABS_MAX_TIMEOUT = 60.0
MIN_TIMEOUT = 0.2


@dataclass(frozen=True)
class ModeConfig:
    name: str
    requests_default: int
    threads_default: int
    timeout_default: float
    requests_cap: int
    threads_cap: int
    timeout_cap: float


# Per-mode defaults + individual caps (your requested "limits for all modes")
MODES = {
    "good": ModeConfig(
        name="Good Boy Mode 🐶",
        requests_default=300,
        threads_default=30,
        timeout_default=3.0,
        requests_cap=300,   # URL-only mode
        threads_cap=30,
        timeout_cap=3.0,
    ),
    "pro": ModeConfig(
        name="Pro Mode 🛠️",
        requests_default=2000,
        threads_default=120,
        timeout_default=5.0,
        requests_cap=10_000,
        threads_cap=200,
        timeout_cap=20.0,
    ),
    "god": ModeConfig(
        name="God Mode ⚡ (still safe + authorized use only)",
        requests_default=8000,
        threads_default=250,
        timeout_default=8.0,
        requests_cap=20_000,
        threads_cap=400,
        timeout_cap=60.0,
    ),
}


# ------------------------------ Parsing helpers ------------------------------

_INT_RE = re.compile(r"^[+-]?\d+$")


def parse_huge_int(text: str, *, field_name: str) -> int:
    """
    Robust integer parser:
    - Accepts very large integers
    - Rejects invalid data safely
    """
    s = (text or "").strip().replace("_", "")
    if not s:
        raise ValueError(f"{field_name}: empty input")
    if not _INT_RE.match(s):
        raise ValueError(f"{field_name}: not a valid integer")
    value = int(s, 10)  # Python int is arbitrary precision
    return value


def parse_float(text: str, *, field_name: str) -> float:
    s = (text or "").strip().replace("_", "")
    if not s:
        raise ValueError(f"{field_name}: empty input")
    try:
        return float(s)
    except ValueError as e:
        raise ValueError(f"{field_name}: not a valid number") from e


def clamp_int(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else hi if v > hi else v


def clamp_float(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def validate_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        raise ValueError("URL cannot be empty.")
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("URL must include http:// or https:// and a valid host.")
    return u


# ------------------------------ Core test logic ------------------------------

def fetch_url(session: requests.Session, url: str, timeout: float) -> Tuple[bool, Optional[int], str]:
    try:
        response = session.get(url, timeout=timeout)
        return True, response.status_code, response.text[:120]
    except requests.exceptions.RequestException as e:
        return False, None, str(e)[:120]


def run_test(target_url: str, request_count: int, thread_count: int, timeout: float) -> None:
    success = 0
    failed = 0
    completed = 0
    in_flight = 0
    last_status = 0
    lock = threading.Lock()
    start_time = time.time()

    print("\n🚀 Starting test...")
    print(f"   URL      : {target_url}")
    print(f"   Requests : {request_count}")
    print(f"   Threads  : {thread_count}")
    print(f"   Timeout  : {timeout:.2f}s")
    print("   (Authorized testing only)\n")

    with requests.Session() as session:
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=thread_count,
            pool_maxsize=thread_count,
            max_retries=0,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        def task():
            nonlocal in_flight
            with lock:
                in_flight += 1
            ok, status_code, content = fetch_url(session, target_url, timeout)
            with lock:
                in_flight -= 1
            return ok, status_code, content

        with ThreadPoolExecutor(max_workers=thread_count) as executor:
            futures = [executor.submit(task) for _ in range(request_count)]

            for future in as_completed(futures):
                ok, status_code, _ = future.result()

                with lock:
                    completed += 1
                    if ok and status_code and 200 <= status_code < 400:
                        success += 1
                        last_status = status_code
                    else:
                        failed += 1
                        last_status = status_code if status_code is not None else 0

                    progress = (completed / request_count) * 100.0
                    elapsed = time.time() - start_time
                    rps = completed / elapsed if elapsed > 0 else 0.0

                    line = (
                        f"status {last_status:<3} | "
                        f"done {completed}/{request_count} | "
                        f"{progress:6.2f}% | "
                        f"ok {success} | fail {failed} | "
                        f"in_flight {in_flight} | rps {rps:8.2f}"
                    )
                    print("\r" + line.ljust(150), end="", flush=True)

    total_time = time.time() - start_time
    avg_rps = (request_count / total_time) if total_time > 0 else 0.0
    print("\n\n✅ Finished")
    print(f"   Total time : {total_time:.2f}s")
    print(f"   Avg RPS    : {avg_rps:.2f}")
    print(f"   Success    : {success}")
    print(f"   Failed     : {failed}")


# ------------------------------ Interactive UX ------------------------------

def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def choose_mode() -> str:
    print("Choose your mode:")
    print("  1) Good Boy Mode 🐶  (URL only, safe defaults)")
    print("  2) Pro Mode 🛠️       (custom params, safe caps)")
    print("  3) God Mode ⚡        (higher caps, still safety-limited)")
    raw = ask("Enter 1/2/3 [default: 1]: ").strip() or "1"
    return {"1": "good", "2": "pro", "3": "god"}.get(raw, "good")


def read_params_interactive() -> Tuple[str, int, int, float]:
    mode_key = choose_mode()
    mode = MODES[mode_key]
    print(f"\n🎛️  {mode.name}")

    default_url = "https://example.com"
    while True:
        try:
            target_url = validate_url(ask(f"Target URL [{default_url}]: ").strip() or default_url)
            break
        except ValueError as e:
            print(f"❌ {e}")

    if mode_key == "good":
        return target_url, mode.requests_default, mode.threads_default, mode.timeout_default

    req_raw = ask(f"Requests [{mode.requests_default}] (max {mode.requests_cap}): ").strip() or str(mode.requests_default)
    thr_raw = ask(f"Threads  [{mode.threads_default}] (max {mode.threads_cap}): ").strip() or str(mode.threads_default)
    tout_raw = ask(f"Timeout  [{mode.timeout_default}] seconds (max {mode.timeout_cap}): ").strip() or str(mode.timeout_default)

    try:
        req_val = parse_huge_int(req_raw, field_name="requests")
        thr_val = parse_huge_int(thr_raw, field_name="threads")
        tout_val = parse_float(tout_raw, field_name="timeout")
    except ValueError as e:
        print(f"⚠️  Bad input: {e}. Falling back to mode defaults.")
        return target_url, mode.requests_default, mode.threads_default, mode.timeout_default

    if req_val <= 0:
        print("⚠️  requests must be > 0. Using default.")
        req_val = mode.requests_default
    if thr_val <= 0:
        print("⚠️  threads must be > 0. Using default.")
        thr_val = mode.threads_default
    if tout_val <= 0:
        print("⚠️  timeout must be > 0. Using default.")
        tout_val = mode.timeout_default

    # Apply per-mode caps first
    req = clamp_int(req_val, 1, mode.requests_cap)
    thr = clamp_int(thr_val, 1, mode.threads_cap)
    tout = clamp_float(tout_val, MIN_TIMEOUT, mode.timeout_cap)

    # Enforce absolute caps as final safeguard
    req = clamp_int(req, 1, ABS_MAX_REQUESTS)
    thr = clamp_int(thr, 1, ABS_MAX_THREADS)
    tout = clamp_float(tout, MIN_TIMEOUT, ABS_MAX_TIMEOUT)

    if req != req_val:
        print(f"ℹ️  requests clamped to {req}")
    if thr != thr_val:
        print(f"ℹ️  threads clamped to {thr}")
    if tout != tout_val:
        print(f"ℹ️  timeout clamped to {tout}")

    return target_url, req, thr, tout


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BoomBench: safe, robust HTTP load tester (authorized targets only)."
    )
    parser.add_argument("--mode", choices=["good", "pro", "god"], help="Run non-interactively with a mode.")
    parser.add_argument("--url", help="Target URL (http/https).")
    parser.add_argument("--requests", dest="requests_count", help="Total requests.")
    parser.add_argument("--threads", help="Concurrent threads.")
    parser.add_argument("--timeout", help="Per-request timeout in seconds.")
    return parser.parse_args()


def resolve_noninteractive(args: argparse.Namespace) -> Tuple[str, int, int, float]:
    mode_key = args.mode or "good"
    mode = MODES[mode_key]

    target_url = validate_url(args.url or "https://example.com")

    if mode_key == "good":
        return target_url, mode.requests_default, mode.threads_default, mode.timeout_default

    req_val = mode.requests_default
    thr_val = mode.threads_default
    tout_val = mode.timeout_default

    if args.requests_count is not None:
        req_val = parse_huge_int(args.requests_count, field_name="requests")
    if args.threads is not None:
        thr_val = parse_huge_int(args.threads, field_name="threads")
    if args.timeout is not None:
        tout_val = parse_float(args.timeout, field_name="timeout")

    if req_val <= 0 or thr_val <= 0 or tout_val <= 0:
        raise ValueError("requests, threads, timeout must all be > 0")

    req = clamp_int(req_val, 1, mode.requests_cap)
    thr = clamp_int(thr_val, 1, mode.threads_cap)
    tout = clamp_float(tout_val, MIN_TIMEOUT, mode.timeout_cap)

    req = clamp_int(req, 1, ABS_MAX_REQUESTS)
    thr = clamp_int(thr, 1, ABS_MAX_THREADS)
    tout = clamp_float(tout, MIN_TIMEOUT, ABS_MAX_TIMEOUT)

    return target_url, req, thr, tout


def main() -> int:
    print("💣 BoomBench (Safe Edition)")
    print("   Funny CLI. Serious safety rules.\n")

    args = parse_args()
    try:
        used_cli_args = any(
            v is not None
            for v in [args.mode, args.url, args.requests_count, args.threads, args.timeout]
        )
        if used_cli_args:
            target_url, request_count, thread_count, timeout = resolve_noninteractive(args)
        else:
            target_url, request_count, thread_count, timeout = read_params_interactive()
    except ValueError as e:
        print(f"❌ Config error: {e}")
        return 2
    except KeyboardInterrupt:
        print("\n🛑 Cancelled by user.")
        return 130

    try:
        run_test(target_url, request_count, thread_count, timeout)
    except KeyboardInterrupt:
        print("\n🛑 Stopped early by user.")
        return 130
    except Exception as e:
        print(f"\n❌ Unexpected runtime error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
