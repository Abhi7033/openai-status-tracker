"""
Console Notifier — Clean, structured console output.

Formats Incident objects into timestamped console logs matching the
exact specification format, with ANSI colors for readability.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import List

from tracker.models import Incident

# ANSI color codes for terminal styling
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[91m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_BLUE = "\033[94m"
_MAGENTA = "\033[95m"
_CYAN = "\033[96m"
_WHITE = "\033[97m"
_GRAY = "\033[90m"


def _status_color(status: str) -> str:
    """Pick a color based on incident status."""
    s = status.lower()
    if "resolved" in s:
        return _GREEN
    elif "monitoring" in s:
        return _CYAN
    elif "identified" in s:
        return _YELLOW
    elif "investigating" in s:
        return _RED
    elif "degraded" in s:
        return _YELLOW
    else:
        return _MAGENTA


def print_banner() -> None:
    """Print the startup banner."""
    banner = f"""
{_BOLD}{_CYAN}+------------------------------------------------------------------+
|          OpenAI Status Tracker -- Live Monitor                   |
|          Event-driven * Async * Scalable                         |
+------------------------------------------------------------------+{_RESET}
"""
    print(banner)


def print_monitoring_start(provider_name: str, feed_url: str, poll_interval: int) -> None:
    """Print a message when monitoring begins for a provider."""
    print(
        f"  {_BOLD}{_BLUE}> Monitoring:{_RESET} {_WHITE}{provider_name}{_RESET}"
        f"  {_DIM}({feed_url}){_RESET}"
        f"  {_DIM}[every {poll_interval}s]{_RESET}"
    )


def print_separator() -> None:
    """Print a visual separator line."""
    print(f"{_DIM}{'─' * 68}{_RESET}")


def print_incident(incident: Incident, is_new: bool = True) -> None:
    """
    Print a single incident with:
    1. The spec-required format ([timestamp] Product / Status)
    2. Additional context (Title, Detail, Link) for richer output
    """
    color = _status_color(incident.status)
    ts = incident.updated.strftime("%Y-%m-%d %H:%M:%S")
    tag = "NEW INCIDENT" if is_new else "INCIDENT UPDATE"

    # Build descriptive status message
    if incident.summary:
        status_msg = f"{incident.status} - {incident.summary}"
    else:
        status_msg = incident.status

    # -- Spec-required output ----------------------------------------
    # [2025-11-03 14:32:00] Product: OpenAI API - Chat Completions
    # Status: Degraded performance due to upstream issue
    if incident.components:
        for comp in incident.components:
            product_label = (
                f"{incident.provider} API - {comp.name}"
                if incident.provider
                else comp.name
            )
            print(f"[{ts}] Product: {product_label}")
            print(f"Status: {status_msg}")
    else:
        product_label = (
            f"{incident.provider} - {incident.title}"
            if incident.provider
            else incident.title
        )
        print(f"[{ts}] Product: {product_label}")
        print(f"Status: {status_msg}")

    # -- Extended detail block ----------------------------------------
    print()
    print(
        f"  {_GRAY}[{ts}]{_RESET} "
        f"{_BOLD}{color}{tag}{_RESET}"
    )
    print(f"    {_BOLD}Provider :{_RESET} {incident.provider}")
    print(f"    {_BOLD}Title    :{_RESET} {incident.title}")
    print(
        f"    {_BOLD}Status   :{_RESET} {color}{incident.status}{_RESET}"
    )
    print(f"    {_BOLD}Products :{_RESET} {incident.product_names}")

    if incident.summary:
        summary = (
            incident.summary[:200] + "..."
            if len(incident.summary) > 200
            else incident.summary
        )
        print(f"    {_BOLD}Detail   :{_RESET} {_DIM}{summary}{_RESET}")

    if incident.link:
        print(f"    {_BOLD}Link     :{_RESET} {_DIM}{incident.link}{_RESET}")

    print()


def print_historical_header(count: int) -> None:
    """Print header before showing historical incidents."""
    print(
        f"\n  {_BOLD}{_YELLOW}Showing {count} most recent historical incidents:{_RESET}\n"
    )


def print_watching() -> None:
    """Print the 'now watching' message after historical incidents."""
    print(
        f"\n  {_BOLD}{_GREEN}Now watching for new updates...{_RESET}"
        f"  {_DIM}(Press Ctrl+C to stop){_RESET}\n"
    )


def print_no_changes(provider_name: str) -> None:
    """Print a subtle heartbeat when no changes are detected (debug level)."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"  {_DIM}[{ts}] {provider_name}: No changes{_RESET}", end="\r")
    sys.stdout.flush()


def print_error(provider_name: str, message: str) -> None:
    """Print an error message."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"  {_GRAY}[{ts}]{_RESET} {_RED}ERROR{_RESET} "
        f"{_BOLD}{provider_name}:{_RESET} {message}"
    )


def print_retry(provider_name: str, attempt: int, wait: float) -> None:
    """Print a retry message with backoff info."""
    print(
        f"  {_DIM}{provider_name}: Retrying in {wait:.1f}s "
        f"(attempt {attempt})...{_RESET}"
    )


def print_shutdown() -> None:
    """Print shutdown message."""
    print(f"\n{_BOLD}{_CYAN}Tracker stopped. Goodbye!{_RESET}\n")
