#!/usr/bin/env python3
"""
S.M.T.H.
Send Me To Heaven
A CLI-only benchmark utility for systems you own or are authorized to test.
"""

from __future__ import annotations

import argparse
import random
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
    tagline: str
    requests_default: int
    threads_default: int
    timeout_default: float
    requests_cap: int
    threads_cap: int
    timeout_cap: float


MODES = {
    "good": ModeConfig(
        name="GOOD MODE",
        tagline="chill, safe, no cap (well, there's a cap, it's just small)",
        requests_default=300,
        threads_default=30,
        timeout_default=3.0,
        requests_cap=300,
        threads_cap=30,
        timeout_cap=3.0,
    ),
    "pro": ModeConfig(
        name="PRO MODE",
        tagline="main character energy, custom params",
        requests_default=2000,
        threads_default=120,
        timeout_default=5.0,
        requests_cap=10_000,
        threads_cap=200,
        timeout_cap=20.0,
    ),
    "god": ModeConfig(
        name="GOD MODE",
        tagline="unhinged but still on a leash",
        requests_default=8000,
        threads_default=250,
        timeout_default=8.0,
        requests_cap=20_000,
        threads_cap=400,
        timeout_cap=60.0,
    ),
}


# ------------------------------ Terminal colors (no emoji) ------------------------------

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"

    @staticmethod
    def wrap(code: str, text: str) -> str:
        return f"{code}{text}{C.RESET}"


# ------------------------------ UI helpers ------------------------------

ASCII_BANNER = r"""
  ____  __  __ _____ _   _ __  __
 / ___||  \/  |_   _| | | |  \/  |
 \___ \| |\/| | | | | | | | |\/| |
  ___) | |  | | | | | |_| | |  | |
 |____/|_|  |_| |_|  \___/|_|  |_|
"""

BANNER_TAGLINES = [
    "no thoughts, just load tests",
    "it's giving throughput",
    "we don't do rate limits, we RESPECT rate limits",
    "the sigma grindset of HTTP requests",
    "built different (still bounded though)",
]

FINISH_LINES_GOOD = [
    "clean run, no notes",
    "that's on periodt and also on safety caps",
]
FINISH_LINES_BAD = [
    "target said 'not today'",
    "the server has left the chat",
]


def print_banner() -> None:
    print(C.wrap(C.CYAN, ASCII_BANNER))
    print(C.wrap(C.BOLD, "S.M.T.H.") + "  |  Send Me To Heaven")
    print(C.wrap(C.DIM, random.choice(BANNER_TAGLINES)))
    print(C.wrap(C.YELLOW, "CLI-only  |  Authorized targets ONLY. No exceptions, no cap.\n"))


# ------------------------------ Parsing helpers ------------------------------

_INT_RE = re.compile(r"^[+-]?\d+$")


def parse_huge_int(text: str, *, field_name: str) -> int:
    s = (text or "").strip().replace("_", "")
    if not s:
        raise ValueError(f"{field_name}: empty input")
    if not _INT_RE.match(s):
        raise ValueError(f"{field_name}: not a valid integer")
    return int(s, 10)


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

    print("\n" + C.wrap(C.MAGENTA, "+------------------------------------------------+"))
    print(C.wrap(C.MAGENTA, "|") + C.wrap(C.BOLD, "              STARTING S.M.T.H. TEST            ") + C.wrap(C.MAGENTA, "|"))
    print(C.wrap(C.MAGENTA, "+------------------------------------------------+"))
    print(f" URL      : {C.wrap(C.CYAN, target_url)}")
    print(f" Requests : {request_count}")
    print(f" Threads  : {thread_count}")
    print(f" Timeout  : {timeout:.2f}s")
    print(C.wrap(C.YELLOW, " Authorized testing only. Locked in.\n"))

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

                    status_color = C.GREEN if (200 <= last_status < 400) else C.RED
                    line = (
                        f"status {C.wrap(status_color, f'{last_status:<3}')} | "
                        f"done {completed}/{request_count} | "
                        f"{progress:6.2f}% | "
                        f"ok {C.wrap(C.GREEN, str(success))} | fail {C.wrap(C.RED, str(failed))} | "
                        f"in_flight {in_flight} | rps {rps:8.2f}"
                    )
                    print("\r" + line.ljust(170), end="", flush=True)

    total_time = time.time() - start_time
    avg_rps = (request_count / total_time) if total_time > 0 else 0.0
    closing = random.choice(FINISH_LINES_GOOD if failed <= success else FINISH_LINES_BAD)

    print("\n\n" + C.wrap(C.MAGENTA, "+------------------------------------------------+"))
    print(C.wrap(C.MAGENTA, "|") + C.wrap(C.BOLD, "                   FINISHED                     ") + C.wrap(C.MAGENTA, "|"))
    print(C.wrap(C.MAGENTA, "+------------------------------------------------+"))
    print(f" Total time : {total_time:.2f}s")
    print(f" Avg RPS    : {avg_rps:.2f}")
    print(f" Success    : {C.wrap(C.GREEN, str(success))}")
    print(f" Failed     : {C.wrap(C.RED, str(failed))}")
    print(C.wrap(C.DIM, f" verdict: {closing}"))


# ------------------------------ Interactive UX ------------------------------


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def confirm_authorization(mode: ModeConfig, target_url: str, req: int, thr: int, tout: float) -> bool:
    """Real authorization confirmation. This does NOT let the user skip or
    change the numeric safety caps -- it only confirms they're allowed to
    point this thing at the target at all."""
    print(C.wrap(C.YELLOW, "\n[!] Reality check before we send it:"))
    print(f"    Mode      : {mode.name} ({mode.tagline})")
    print(f"    Target    : {target_url}")
    print(f"    Requests  : {req}  (capped at {mode.requests_cap}, hard ceiling {ABS_MAX_REQUESTS})")
    print(f"    Threads   : {thr}  (capped at {mode.threads_cap}, hard ceiling {ABS_MAX_THREADS})")
    print(f"    Timeout   : {tout:.2f}s (capped at {mode.timeout_cap}, hard ceiling {ABS_MAX_TIMEOUT})")
    print(C.wrap(C.RED, "    Only run this against systems you own or are explicitly authorized to test."))
    ans = ask(C.wrap(C.BOLD, "    Confirm you're authorized to test this target? [y/N]: ")).strip().lower()
    return ans in ("y", "yes")


def choose_mode() -> str:
    print(C.wrap(C.BOLD, "Choose your mode:"))
    print(f"  1) {MODES['good'].name}  - URL only, safe defaults ({MODES['good'].tagline})")
    print(f"  2) {MODES['pro'].name}   - custom params, safe caps ({MODES['pro'].tagline})")
    print(f"  3) {MODES['god'].name}   - higher caps, still bounded ({MODES['god'].tagline})")
    raw = ask("Enter 1/2/3 [default: 1]: ").strip() or "1"
    return {"1": "good", "2": "pro", "3": "god"}.get(raw, "good")


def read_params_interactive() -> Optional[Tuple[str, int, int, float]]:
    mode_key = choose_mode()
    mode = MODES[mode_key]
    print(f"\nMODE: {C.wrap(C.CYAN, mode.name)} -- {mode.tagline}")

    default_url = "https://example.com"
    while True:
        try:
            target_url = validate_url(ask(f"Target URL [{default_url}]: ").strip() or default_url)
            break
        except ValueError as e:
            print(C.wrap(C.RED, f"[!] {e}"))

    if mode_key == "good":
        req, thr, tout = mode.requests_default, mode.threads_default, mode.timeout_default
        if not confirm_authorization(mode, target_url, req, thr, tout):
            print(C.wrap(C.YELLOW, "[x] Not confirmed. Bailing out, no requests sent."))
            return None
        return target_url, req, thr, tout

    req_raw = ask(f"Requests [{mode.requests_default}] (max {mode.requests_cap}): ").strip() or str(mode.requests_default)
    thr_raw = ask(f"Threads  [{mode.threads_default}] (max {mode.threads_cap}): ").strip() or str(mode.threads_default)
    tout_raw = ask(f"Timeout  [{mode.timeout_default}] seconds (max {mode.timeout_cap}): ").strip() or str(mode.timeout_default)

    try:
        req_val = parse_huge_int(req_raw, field_name="requests")
        thr_val = parse_huge_int(thr_raw, field_name="threads")
        tout_val = parse_float(tout_raw, field_name="timeout")
    except ValueError as e:
        print(C.wrap(C.RED, f"[!] Bad input: {e}. Falling back to mode defaults."))
        req_val, thr_val, tout_val = mode.requests_default, mode.threads_default, mode.timeout_default

    if req_val <= 0:
        print(C.wrap(C.YELLOW, "[!] requests must be > 0. Using default."))
        req_val = mode.requests_default
    if thr_val <= 0:
        print(C.wrap(C.YELLOW, "[!] threads must be > 0. Using default."))
        thr_val = mode.threads_default
    if tout_val <= 0:
        print(C.wrap(C.YELLOW, "[!] timeout must be > 0. Using default."))
        tout_val = mode.timeout_default

    req = clamp_int(req_val, 1, mode.requests_cap)
    thr = clamp_int(thr_val, 1, mode.threads_cap)
    tout = clamp_float(tout_val, MIN_TIMEOUT, mode.timeout_cap)

    req = clamp_int(req, 1, ABS_MAX_REQUESTS)
    thr = clamp_int(thr, 1, ABS_MAX_THREADS)
    tout = clamp_float(tout, MIN_TIMEOUT, ABS_MAX_TIMEOUT)

    if req != req_val:
        print(C.wrap(C.DIM, f"[i] requests clamped to {req} (nice try though)"))
    if thr != thr_val:
        print(C.wrap(C.DIM, f"[i] threads clamped to {thr} (nice try though)"))
    if tout != tout_val:
        print(C.wrap(C.DIM, f"[i] timeout clamped to {tout} (nice try though)"))

    if not confirm_authorization(mode, target_url, req, thr, tout):
        print(C.wrap(C.YELLOW, "[x] Not confirmed. Bailing out, no requests sent."))
        return None

    return target_url, req, thr, tout


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="S.M.T.H.: CLI-only HTTP benchmark utility (authorized targets only)."
    )
    parser.add_argument("--mode", choices=["good", "pro", "god"], help="Run non-interactively with a mode.")
    parser.add_argument("--url", help="Target URL (http/https).")
    parser.add_argument("--requests", dest="requests_count", help="Total requests.")
    parser.add_argument("--threads", help="Concurrent threads.")
    parser.add_argument("--timeout", help="Per-request timeout in seconds.")
    parser.add_argument("--yes", action="store_true", help="Skip the interactive authorization prompt (you are still confirming authorization by passing this flag).")
    return parser.parse_args()


def resolve_noninteractive(args: argparse.Namespace) -> Tuple[str, int, int, float]:
    mode_key = args.mode or "good"
    mode = MODES[mode_key]

    target_url = validate_url(args.url or "https://example.com")

    if mode_key == "good":
        req, thr, tout = mode.requests_default, mode.threads_default, mode.timeout_default
    else:
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

    if not args.yes:
        if not confirm_authorization(mode, target_url, req, thr, tout):
            raise KeyboardInterrupt()

    return target_url, req, thr, tout


def main() -> int:
    print_banner()

    args = parse_args()
    try:
        used_cli_args = any(
            v is not None
            for v in [args.mode, args.url, args.requests_count, args.threads, args.timeout]
        ) or args.yes
        if used_cli_args:
            target_url, request_count, thread_count, timeout = resolve_noninteractive(args)
        else:
            result = read_params_interactive()
            if result is None:
                return 130
            target_url, request_count, thread_count, timeout = result
    except ValueError as e:
        print(C.wrap(C.RED, f"[x] Config error: {e}"))
        return 2
    except KeyboardInterrupt:
        print(C.wrap(C.YELLOW, "\n[x] Cancelled by user."))
        return 130

    try:
        run_test(target_url, request_count, thread_count, timeout)
    except KeyboardInterrupt:
        print(C.wrap(C.YELLOW, "\n[x] Stopped early by user."))
        return 130
    except Exception as e:
        print(C.wrap(C.RED, f"\n[x] Unexpected runtime error: {e}"))
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
