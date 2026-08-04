#!/usr/bin/env python3
"""
S.M.T.H.
Send Me To Heaven
A CLI-only benchmark utility for systems you own or are authorized to test.

This is the "dashboard" build: a richer terminal UI (panels, tables, a live
layout) built with the `rich` library. It is still a terminal application --
no browser, no server -- it just looks a lot more like one.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional, Tuple
from urllib.parse import urlparse

import requests

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich.progress import (
    Progress,
    BarColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.prompt import Prompt, Confirm
from rich import box


console = Console()


# ------------------------------ Safety/limits ------------------------------

# Absolute global safety caps (never exceeded in any mode)
ABS_MAX_REQUESTS = 20_000
ABS_MAX_THREADS = 400
ABS_MAX_TIMEOUT = 60.0
MIN_TIMEOUT = 0.2


@dataclass(frozen=True)
class ModeConfig:
    key: str
    name: str
    tagline: str
    color: str
    requests_default: int
    threads_default: int
    timeout_default: float
    requests_cap: int
    threads_cap: int
    timeout_cap: float


MODES = {
    "good": ModeConfig(
        key="good",
        name="GOOD MODE",
        tagline="chill, safe, no cap (well, there's a cap, it's just small)",
        color="green",
        requests_default=300,
        threads_default=30,
        timeout_default=3.0,
        requests_cap=300,
        threads_cap=30,
        timeout_cap=3.0,
    ),
    "pro": ModeConfig(
        key="pro",
        name="PRO MODE",
        tagline="main character energy, custom params",
        color="cyan",
        requests_default=2000,
        threads_default=120,
        timeout_default=5.0,
        requests_cap=10_000,
        threads_cap=200,
        timeout_cap=20.0,
    ),
    "god": ModeConfig(
        key="god",
        name="GOD MODE",
        tagline="unhinged but still on a leash",
        color="magenta",
        requests_default=8000,
        threads_default=250,
        timeout_default=8.0,
        requests_cap=20_000,
        threads_cap=400,
        timeout_cap=60.0,
    ),
}

BANNER_TAGLINES = [
    "no thoughts, just load tests",
    "it's giving throughput",
    "we don't do rate limits, we RESPECT rate limits",
    "the sigma grindset of HTTP requests",
    "built different (still bounded though)",
]

FINISH_LINES_GOOD = ["clean run, no notes", "that's on periodt and also on safety caps"]
FINISH_LINES_BAD = ["target said 'not today'", "the server has left the chat"]

ASCII_LOGO = r"""
 ____  __  __ _____ _   _ __  __
/ ___||  \/  |_   _| | | |  \/  |
\___ \| |\/| | | | | | | | |\/| |
 ___) | |  | | | | | |_| | |  | |
|____/|_|  |_| |_|  \___/|_|  |_|
"""


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


# ------------------------------ "Webpage-style" chrome ------------------------------


def render_banner() -> Panel:
    logo = Text(ASCII_LOGO, style="bold cyan")
    sub = Text("Send Me To Heaven", style="bold white")
    tag = Text(random.choice(BANNER_TAGLINES), style="dim italic")
    warn = Text("CLI-only  |  Authorized targets ONLY. No exceptions, no cap.", style="bold yellow")
    body = Group(Align.center(logo), Align.center(sub), Align.center(tag), Align.center(warn))
    return Panel(body, box=box.DOUBLE, border_style="cyan", padding=(0, 2))


def render_navbar(active: str) -> Panel:
    """A little fake 'nav bar' across the top, webpage-style."""
    items = ["HOME", "MODES", "TARGET", "RUN", "RESULTS"]
    parts = []
    for it in items:
        if it == active:
            parts.append(f"[reverse bold] {it} [/reverse bold]")
        else:
            parts.append(f"[dim] {it} [/dim]")
    text = "   ".join(parts)
    return Panel(Align.center(Text.from_markup(text)), box=box.SQUARE, border_style="grey50", padding=(0, 0))


def render_mode_cards() -> Table:
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold white", expand=True)
    table.add_column("#", justify="center", width=3)
    table.add_column("Mode", style="bold")
    table.add_column("Vibe")
    table.add_column("Req cap", justify="right")
    table.add_column("Thread cap", justify="right")
    table.add_column("Timeout cap", justify="right")
    for i, key in enumerate(("good", "pro", "god"), start=1):
        m = MODES[key]
        table.add_row(
            str(i),
            Text(m.name, style=f"bold {m.color}"),
            m.tagline,
            str(m.requests_cap),
            str(m.threads_cap),
            f"{m.timeout_cap:.0f}s",
        )
    return table


def render_config_summary(mode: ModeConfig, url: str, req: int, thr: int, tout: float) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold grey70", justify="right")
    table.add_column()
    table.add_row("Mode", Text(f"{mode.name} — {mode.tagline}", style=f"bold {mode.color}"))
    table.add_row("Target", Text(url, style="bold white"))
    table.add_row("Requests", f"{req}  (cap {mode.requests_cap}, hard ceiling {ABS_MAX_REQUESTS})")
    table.add_row("Threads", f"{thr}  (cap {mode.threads_cap}, hard ceiling {ABS_MAX_THREADS})")
    table.add_row("Timeout", f"{tout:.2f}s  (cap {mode.timeout_cap:.0f}s, hard ceiling {ABS_MAX_TIMEOUT:.0f}s)")
    return Panel(table, title="[bold]Run Configuration[/bold]", border_style="yellow", box=box.ROUNDED)


def render_authorization_panel() -> Panel:
    body = Text(
        "Only run this against systems you own or are explicitly authorized to test.\n"
        "By confirming below you are stating that authorization exists.",
        style="bold red",
    )
    return Panel(body, title="[bold red]Authorization Check[/bold red]", border_style="red", box=box.HEAVY)


# ------------------------------ Core test logic ------------------------------


@dataclass
class RunStats:
    success: int = 0
    failed: int = 0
    completed: int = 0
    in_flight: int = 0
    last_status: int = 0
    status_log: list = field(default_factory=list)  # last N (status, ok) tuples
    lock: threading.Lock = field(default_factory=threading.Lock)


def fetch_url(session: requests.Session, url: str, timeout: float) -> Tuple[bool, Optional[int], str]:
    try:
        response = session.get(url, timeout=timeout)
        return True, response.status_code, response.text[:120]
    except requests.exceptions.RequestException as e:
        return False, None, str(e)[:120]


def build_dashboard(
    mode: ModeConfig,
    target_url: str,
    request_count: int,
    thread_count: int,
    timeout: float,
    stats: RunStats,
    progress: Progress,
    task_id,
) -> Group:
    header = render_navbar("RUN")

    cfg_table = Table.grid(padding=(0, 2))
    cfg_table.add_column(style="bold grey70", justify="right")
    cfg_table.add_column()
    cfg_table.add_row("Target", Text(target_url, style="bold white"))
    cfg_table.add_row("Mode", Text(mode.name, style=f"bold {mode.color}"))
    cfg_table.add_row("Requests", str(request_count))
    cfg_table.add_row("Threads", str(thread_count))
    cfg_table.add_row("Timeout", f"{timeout:.2f}s")
    cfg_panel = Panel(cfg_table, title="Config", border_style="grey50", box=box.ROUNDED)

    with stats.lock:
        success = stats.success
        failed = stats.failed
        completed = stats.completed
        in_flight = stats.in_flight
        last_status = stats.last_status
        recent = list(stats.status_log[-12:])

    stat_table = Table.grid(padding=(0, 3))
    stat_table.add_column(justify="center")
    stat_table.add_column(justify="center")
    stat_table.add_column(justify="center")
    stat_table.add_column(justify="center")
    stat_table.add_row(
        Text(f"{success}", style="bold green") , Text(f"{failed}", style="bold red"),
        Text(f"{in_flight}", style="bold yellow"), Text(f"{last_status}", style="bold white"),
    )
    stat_table.add_row("SUCCESS", "FAILED", "IN-FLIGHT", "LAST STATUS")
    stats_panel = Panel(stat_table, title="Live Stats", border_style="green", box=box.ROUNDED)

    log_text = Text()
    for ok, code in recent:
        style = "green" if ok and code and 200 <= code < 400 else "red"
        log_text.append(f"[{code if code else 'ERR'}] ", style=style)
    if not recent:
        log_text.append("waiting for first response...", style="dim")
    log_panel = Panel(log_text, title="Recent Responses", border_style="grey50", box=box.ROUNDED)

    body = Table.grid(expand=True)
    body.add_column(ratio=1)
    body.add_column(ratio=1)
    body.add_row(cfg_panel, stats_panel)

    progress_panel = Panel(progress, title="Progress", border_style="cyan", box=box.ROUNDED)

    return Group(header, body, log_panel, progress_panel)


def run_test(mode: ModeConfig, target_url: str, request_count: int, thread_count: int, timeout: float) -> None:
    stats = RunStats()
    start_time = time.time()

    progress = Progress(
        TextColumn("[bold]{task.description}"),
        BarColumn(bar_width=None),
        TextColumn("{task.percentage:>5.1f}%"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        expand=True,
    )
    task_id = progress.add_task("sending it...", total=request_count)

    with requests.Session() as session:
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=thread_count,
            pool_maxsize=thread_count,
            max_retries=0,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        def task():
            with stats.lock:
                stats.in_flight += 1
            ok, status_code, content = fetch_url(session, target_url, timeout)
            with stats.lock:
                stats.in_flight -= 1
            return ok, status_code, content

        with Live(console=console, refresh_per_second=12, screen=False) as live:
            with ThreadPoolExecutor(max_workers=thread_count) as executor:
                futures = [executor.submit(task) for _ in range(request_count)]

                for future in as_completed(futures):
                    ok, status_code, _ = future.result()

                    with stats.lock:
                        stats.completed += 1
                        if ok and status_code and 200 <= status_code < 400:
                            stats.success += 1
                            stats.last_status = status_code
                        else:
                            stats.failed += 1
                            stats.last_status = status_code if status_code is not None else 0
                        stats.status_log.append((ok, status_code))
                        if len(stats.status_log) > 200:
                            stats.status_log = stats.status_log[-200:]

                    progress.update(task_id, completed=stats.completed)
                    live.update(build_dashboard(mode, target_url, request_count, thread_count, timeout, stats, progress, task_id))

    total_time = time.time() - start_time
    avg_rps = (request_count / total_time) if total_time > 0 else 0.0
    closing = random.choice(FINISH_LINES_GOOD if stats.failed <= stats.success else FINISH_LINES_BAD)

    result_table = Table.grid(padding=(0, 3))
    result_table.add_column(style="bold grey70", justify="right")
    result_table.add_column()
    result_table.add_row("Total time", f"{total_time:.2f}s")
    result_table.add_row("Avg RPS", f"{avg_rps:.2f}")
    result_table.add_row("Success", Text(str(stats.success), style="bold green"))
    result_table.add_row("Failed", Text(str(stats.failed), style="bold red"))
    result_table.add_row("Verdict", Text(closing, style="italic dim"))

    console.print(render_navbar("RESULTS"))
    console.print(Panel(result_table, title="[bold]Run Complete[/bold]", border_style="green", box=box.DOUBLE))


# ------------------------------ Interactive UX ------------------------------


def confirm_authorization(mode: ModeConfig, target_url: str, req: int, thr: int, tout: float) -> bool:
    """Real authorization confirmation. This does NOT let the user skip or
    change the numeric safety caps -- it only confirms they're allowed to
    point this thing at the target at all."""
    console.print(render_config_summary(mode, target_url, req, thr, tout))
    console.print(render_authorization_panel())
    return Confirm.ask("[bold]Confirm you're authorized to test this target?[/bold]", default=False)


def choose_mode() -> str:
    console.print(render_navbar("MODES"))
    console.print(render_mode_cards())
    raw = Prompt.ask("Select mode", choices=["1", "2", "3"], default="1")
    return {"1": "good", "2": "pro", "3": "god"}[raw]


def read_params_interactive() -> Optional[Tuple[ModeConfig, str, int, int, float]]:
    mode_key = choose_mode()
    mode = MODES[mode_key]

    console.print(render_navbar("TARGET"))
    default_url = "https://example.com"
    while True:
        try:
            target_url = validate_url(Prompt.ask("Target URL", default=default_url))
            break
        except ValueError as e:
            console.print(f"[bold red][!] {e}[/bold red]")

    if mode_key == "good":
        req, thr, tout = mode.requests_default, mode.threads_default, mode.timeout_default
        if not confirm_authorization(mode, target_url, req, thr, tout):
            console.print("[yellow][x] Not confirmed. Bailing out, no requests sent.[/yellow]")
            return None
        return mode, target_url, req, thr, tout

    req_raw = Prompt.ask(f"Requests (max {mode.requests_cap})", default=str(mode.requests_default))
    thr_raw = Prompt.ask(f"Threads (max {mode.threads_cap})", default=str(mode.threads_default))
    tout_raw = Prompt.ask(f"Timeout seconds (max {mode.timeout_cap})", default=str(mode.timeout_default))

    try:
        req_val = parse_huge_int(req_raw, field_name="requests")
        thr_val = parse_huge_int(thr_raw, field_name="threads")
        tout_val = parse_float(tout_raw, field_name="timeout")
    except ValueError as e:
        console.print(f"[bold red][!] Bad input: {e}. Falling back to mode defaults.[/bold red]")
        req_val, thr_val, tout_val = mode.requests_default, mode.threads_default, mode.timeout_default

    if req_val <= 0:
        console.print("[yellow][!] requests must be > 0. Using default.[/yellow]")
        req_val = mode.requests_default
    if thr_val <= 0:
        console.print("[yellow][!] threads must be > 0. Using default.[/yellow]")
        thr_val = mode.threads_default
    if tout_val <= 0:
        console.print("[yellow][!] timeout must be > 0. Using default.[/yellow]")
        tout_val = mode.timeout_default

    req = clamp_int(req_val, 1, mode.requests_cap)
    thr = clamp_int(thr_val, 1, mode.threads_cap)
    tout = clamp_float(tout_val, MIN_TIMEOUT, mode.timeout_cap)

    req = clamp_int(req, 1, ABS_MAX_REQUESTS)
    thr = clamp_int(thr, 1, ABS_MAX_THREADS)
    tout = clamp_float(tout, MIN_TIMEOUT, ABS_MAX_TIMEOUT)

    if req != req_val:
        console.print(f"[dim][i] requests clamped to {req} (nice try though)[/dim]")
    if thr != thr_val:
        console.print(f"[dim][i] threads clamped to {thr} (nice try though)[/dim]")
    if tout != tout_val:
        console.print(f"[dim][i] timeout clamped to {tout} (nice try though)[/dim]")

    if not confirm_authorization(mode, target_url, req, thr, tout):
        console.print("[yellow][x] Not confirmed. Bailing out, no requests sent.[/yellow]")
        return None

    return mode, target_url, req, thr, tout


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="S.M.T.H.: CLI-only HTTP benchmark utility (authorized targets only)."
    )
    parser.add_argument("--mode", choices=["good", "pro", "god"], help="Run non-interactively with a mode.")
    parser.add_argument("--url", help="Target URL (http/https).")
    parser.add_argument("--requests", dest="requests_count", help="Total requests.")
    parser.add_argument("--threads", help="Concurrent threads.")
    parser.add_argument("--timeout", help="Per-request timeout in seconds.")
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip the interactive authorization prompt (you are still confirming authorization by passing this flag).",
    )
    return parser.parse_args()


def resolve_noninteractive(args: argparse.Namespace) -> Tuple[ModeConfig, str, int, int, float]:
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

    return mode, target_url, req, thr, tout


def main() -> int:
    console.print(render_banner())

    args = parse_args()
    try:
        used_cli_args = any(
            v is not None
            for v in [args.mode, args.url, args.requests_count, args.threads, args.timeout]
        ) or args.yes
        if used_cli_args:
            mode, target_url, request_count, thread_count, timeout = resolve_noninteractive(args)
        else:
            result = read_params_interactive()
            if result is None:
                return 130
            mode, target_url, request_count, thread_count, timeout = result
    except ValueError as e:
        console.print(f"[bold red][x] Config error: {e}[/bold red]")
        return 2
    except KeyboardInterrupt:
        console.print("[yellow][x] Cancelled by user.[/yellow]")
        return 130

    try:
        run_test(mode, target_url, request_count, thread_count, timeout)
    except KeyboardInterrupt:
        console.print("[yellow][x] Stopped early by user.[/yellow]")
        return 130
    except Exception as e:
        console.print(f"[bold red][x] Unexpected runtime error: {e}[/bold red]")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
