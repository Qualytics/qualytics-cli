"""CLI doctor command — diagnostic health checks."""

import os
import sys
import time
from datetime import datetime, timezone

import jwt
import requests
import typer
from rich import print

from ..config import CONFIG_PATH, __version__, load_config
from . import BRAND, print_banner


def _check_mark(ok: bool, warn: bool = False) -> str:
    if ok and not warn:
        return f"[{BRAND}]✓[/{BRAND}]"
    if warn:
        return "[yellow]⚠[/yellow]"
    return "[red]✗[/red]"


def doctor() -> None:
    """Run diagnostic checks on the Qualytics CLI setup."""
    print_banner(subtitle="[bold]Doctor[/bold]")

    passed = 0
    warned = 0
    failed = 0

    # ── 1. CLI version ────────────────────────────────────────────────
    print(
        f"  {_check_mark(True)} [bold]CLI version[/bold]      Qualytics CLI v{__version__}"
    )
    passed += 1

    # ── 2. Python version ─────────────────────────────────────────────
    py_ver = (
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    py_ok = sys.version_info >= (3, 10)
    if py_ok:
        print(f"  {_check_mark(True)} [bold]Python version[/bold]   {py_ver}")
        passed += 1
    else:
        print(
            f"  {_check_mark(False, warn=True)} [bold]Python version[/bold]   "
            f"{py_ver} [yellow]— 3.10+ recommended[/yellow]"
        )
        warned += 1

    # ── 3. Configuration ──────────────────────────────────────────────
    config = None
    if os.path.exists(CONFIG_PATH):
        config = load_config()

    if config:
        print(
            f"  {_check_mark(True)} [bold]Configuration[/bold]   Config found at {CONFIG_PATH}"
        )
        passed += 1
    else:
        print(
            f"  {_check_mark(False)} [bold]Configuration[/bold]   "
            f"No config file — run [bold]'qualytics auth init'[/bold]"
        )
        failed += 1
        # Can't continue without config
        _print_summary(passed, warned, failed)
        raise typer.Exit(code=1)

    # ── 4. Auth token ─────────────────────────────────────────────────
    token = config.get("token", "")
    if token:
        print(f"  {_check_mark(True)} [bold]Authentication[/bold]  Token configured")
        passed += 1
    else:
        print(
            f"  {_check_mark(False)} [bold]Authentication[/bold]  "
            f"No auth token — run [bold]'qualytics auth login'[/bold]"
        )
        failed += 1
        _print_summary(passed, warned, failed)
        raise typer.Exit(code=1)

    # ── 5. Token expiry ───────────────────────────────────────────────
    try:
        decoded = jwt.decode(
            token, algorithms=["none"], options={"verify_signature": False}
        )
        exp = decoded.get("exp")
        if exp is not None:
            exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
            now = datetime.now(timezone.utc)
            delta = exp_dt - now
            total_secs = delta.total_seconds()

            if total_secs <= 0:
                days_ago = abs(delta.days)
                print(
                    f"  {_check_mark(False)} [bold]Token validity[/bold]  "
                    f"[red]Expired {days_ago} day(s) ago[/red]"
                )
                failed += 1
            elif delta.days < 7:
                if delta.days > 0:
                    label = f"in {delta.days} day(s)"
                else:
                    label = f"in {int(total_secs // 3600)} hour(s)"
                print(
                    f"  {_check_mark(False, warn=True)} [bold]Token validity[/bold]  "
                    f"[yellow]Expires {label}[/yellow]"
                )
                warned += 1
            else:
                print(
                    f"  {_check_mark(True)} [bold]Token validity[/bold]  "
                    f"Valid (expires in {delta.days} days)"
                )
                passed += 1
        else:
            print(
                f"  {_check_mark(True)} [bold]Token validity[/bold]  "
                "Valid (no expiry set)"
            )
            passed += 1
    except Exception:
        print(
            f"  {_check_mark(False, warn=True)} [bold]Token validity[/bold]  "
            "[yellow]Could not decode token[/yellow]"
        )
        warned += 1

    # ── 6. API connectivity ───────────────────────────────────────────
    base_url = config.get("url", "")
    ssl_verify = config.get("ssl_verify", True)

    if base_url:
        try:
            start = time.monotonic()
            resp = requests.get(
                base_url,
                headers={"Authorization": f"Bearer {token}"},
                verify=ssl_verify,
                timeout=10,
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)
            display_url = base_url.rstrip("/")

            if resp.ok or resp.status_code in (401, 403, 404):
                # Server is reachable (even 401/403/404 means server responded)
                print(
                    f"  {_check_mark(True)} [bold]API connection[/bold]  "
                    f"Reachable at {display_url} ({elapsed_ms}ms)"
                )
                passed += 1
            else:
                print(
                    f"  {_check_mark(False, warn=True)} [bold]API connection[/bold]  "
                    f"[yellow]{display_url} responded with HTTP {resp.status_code}[/yellow]"
                )
                warned += 1

        except requests.exceptions.SSLError as e:
            print(
                f"  {_check_mark(False)} [bold]API connection[/bold]  "
                f"[red]SSL error: {e}[/red]"
            )
            failed += 1
        except requests.exceptions.ConnectionError:
            display_url = base_url.rstrip("/")
            print(
                f"  {_check_mark(False)} [bold]API connection[/bold]  "
                f"[red]Cannot reach {display_url} — check URL and network[/red]"
            )
            failed += 1
        except requests.exceptions.Timeout:
            print(
                f"  {_check_mark(False)} [bold]API connection[/bold]  "
                "[red]Connection timed out[/red]"
            )
            failed += 1
    else:
        print(
            f"  {_check_mark(False)} [bold]API connection[/bold]  "
            "[red]No URL configured[/red]"
        )
        failed += 1

    # ── 7. SSL certificate ────────────────────────────────────────────
    if not ssl_verify:
        print(
            f"  {_check_mark(False, warn=True)} [bold]SSL certificate[/bold] "
            "[yellow]Verification disabled (--no-verify-ssl)[/yellow]"
        )
        warned += 1
    elif base_url:
        try:
            requests.get(base_url, verify=True, timeout=10)
            print(f"  {_check_mark(True)} [bold]SSL certificate[/bold] Valid")
            passed += 1
        except requests.exceptions.SSLError:
            print(
                f"  {_check_mark(False, warn=True)} [bold]SSL certificate[/bold] "
                "[yellow]Certificate validation failed[/yellow]"
            )
            warned += 1
        except Exception:
            # Connection error already reported above — skip SSL check
            print(
                f"  {_check_mark(False, warn=True)} [bold]SSL certificate[/bold] "
                "[yellow]Could not verify (connection failed)[/yellow]"
            )
            warned += 1
    else:
        print(
            f"  {_check_mark(False)} [bold]SSL certificate[/bold] "
            "[red]No URL configured[/red]"
        )
        failed += 1

    _print_summary(passed, warned, failed)

    if failed > 0:
        raise typer.Exit(code=1)


def _print_summary(passed: int, warned: int, failed: int) -> None:
    """Print the doctor summary line."""
    parts = []
    if passed:
        parts.append(f"[{BRAND}]{passed} passed[/{BRAND}]")
    if warned:
        parts.append(f"[yellow]{warned} warning(s)[/yellow]")
    if failed:
        parts.append(f"[red]{failed} failed[/red]")

    print()
    if failed == 0 and warned == 0:
        print(f"  [bold {BRAND}]All checks passed![/bold {BRAND}]")
    else:
        print(f"  {', '.join(parts)}")
    print()
