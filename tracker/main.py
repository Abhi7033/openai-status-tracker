"""
Main entry point — the StatusTracker orchestrator.

Creates one FeedMonitor per configured provider, launches them all
concurrently in a single asyncio event loop, and handles graceful
shutdown on Ctrl+C.

Usage:
    python -m tracker
    python tracker/main.py
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from typing import List

import aiohttp
from aiohttp import web

from tracker.config import load_config
from tracker.models import ProviderConfig, TrackerSettings
from tracker.monitor import FeedMonitor
from tracker import notifier
import tracker as _tracker


class StatusTracker:
    """
    Top-level orchestrator.

    Manages the lifecycle of all FeedMonitor instances and the shared
    aiohttp session.
    """

    def __init__(
        self,
        providers: List[ProviderConfig],
        settings: TrackerSettings,
    ) -> None:
        self.providers = providers
        self.settings = settings
        self._monitors: List[FeedMonitor] = []
        self._tasks: List[asyncio.Task] = []

    async def run(self) -> None:
        """
        Launch all monitors concurrently and wait until interrupted.
        """
        notifier.print_banner()

        # Shared session — connection pooling across all monitors
        connector = aiohttp.TCPConnector(limit_per_host=5)
        async with aiohttp.ClientSession(connector=connector) as session:
            # Spin up one monitor per provider
            for provider in self.providers:
                monitor = FeedMonitor(provider, self.settings)
                self._monitors.append(monitor)
                task = asyncio.create_task(
                    monitor.start(session),
                    name=f"monitor-{provider.name}",
                )
                self._tasks.append(task)

            # Wait for all tasks (they run forever until cancelled)
            try:
                await asyncio.gather(*self._tasks)
            except asyncio.CancelledError:
                pass

    def shutdown(self) -> None:
        """Cancel all running monitor tasks."""
        for task in self._tasks:
            task.cancel()


def _handle_signals(tracker: StatusTracker, loop: asyncio.AbstractEventLoop) -> None:
    """Register signal handlers for graceful shutdown."""
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(
                sig,
                lambda: _do_shutdown(tracker),
            )
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass


def _do_shutdown(tracker: StatusTracker) -> None:
    """Trigger graceful shutdown."""
    notifier.print_shutdown()
    tracker.shutdown()


async def async_main() -> None:
    """Async entry point."""
    providers, settings = load_config()
    tracker = StatusTracker(providers, settings)

    loop = asyncio.get_running_loop()
    _handle_signals(tracker, loop)

    # Start a minimal health-check server for hosted deployments
    port = int(os.environ.get("PORT", 10000))
    app = web.Application()
    app.router.add_get("/", lambda _: web.json_response({
        "status": "running",
        "message": "OpenAI status tracker is active",
        "tracked_incidents": _tracker.incident_count,
    }))
    app.router.add_get("/health", lambda _: web.json_response({"status": "healthy"}))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    await tracker.run()


def main() -> None:
    """Sync entry point."""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        # Signal handler already printed shutdown message
        sys.exit(0)


if __name__ == "__main__":
    main()
