"""
Async Feed Monitor — the core engine.

Each FeedMonitor instance tracks a single status page provider.
It uses:
  - Conditional HTTP (ETag / If-Modified-Since) to skip unchanged feeds
  - Content hashing (SHA-256) for fast change detection
  - Seen-ID tracking to only surface genuinely new/updated incidents
  - Exponential backoff with jitter on transient failures

Multiple FeedMonitor instances run concurrently in a single asyncio
event loop, making this scale efficiently to 100+ providers.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

import aiohttp

from tracker.feed_parser import parse_feed
from tracker.models import Incident, ProviderConfig, TrackerSettings
from tracker import notifier
import tracker as _tracker


class FeedMonitor:
    """
    Monitors a single status page feed asynchronously.

    Attributes:
        config: Provider configuration (URL, type, interval).
        settings: Global tracker settings.
    """

    def __init__(self, config: ProviderConfig, settings: TrackerSettings) -> None:
        self.config = config
        self.settings = settings

        # Conditional HTTP state
        self._etag: Optional[str] = None
        self._last_modified: Optional[str] = None

        # Change detection
        self._last_hash: Optional[str] = None
        self._seen_ids: Set[str] = set()
        self._seen_updates: Dict[str, str] = {}  # id -> last update hash

        # Backoff state
        self._consecutive_errors = 0

        # First-run flag
        self._first_run = True

    async def start(self, session: aiohttp.ClientSession) -> None:
        """
        Begin the monitoring loop. Runs indefinitely until cancelled.

        On the first run, fetches historical incidents. After that,
        only reports new or updated incidents.
        """
        notifier.print_monitoring_start(
            self.config.name,
            self.config.feed_url,
            self.config.poll_interval,
        )

        while True:
            try:
                await self._poll(session)
                self._consecutive_errors = 0
                await asyncio.sleep(self.config.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._consecutive_errors += 1
                wait = self._backoff_delay()
                notifier.print_error(self.config.name, str(exc))
                notifier.print_retry(
                    self.config.name,
                    self._consecutive_errors,
                    wait,
                )
                await asyncio.sleep(wait)

    async def _poll(self, session: aiohttp.ClientSession) -> None:
        """
        Execute a single poll cycle:
        1. Fetch feed with conditional HTTP headers
        2. Skip if 304 Not Modified
        3. Skip if content hash unchanged
        4. Parse incidents and diff against seen set
        5. Notify on new/updated incidents
        """
        # ── Build conditional headers ─────────────────────
        headers: Dict[str, str] = {
            "Accept": "application/atom+xml, application/rss+xml, application/xml",
        }
        if self._etag:
            headers["If-None-Match"] = self._etag
        if self._last_modified:
            headers["If-Modified-Since"] = self._last_modified

        # ── Fetch ─────────────────────────────────────────
        async with session.get(
            self.config.feed_url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            # 304 — nothing changed, server confirmed via ETag/Last-Modified
            if resp.status == 304:
                if self.settings.log_level == "DEBUG":
                    notifier.print_no_changes(self.config.name)
                return

            resp.raise_for_status()
            body = await resp.text()

            # Store conditional headers for next request
            if "ETag" in resp.headers:
                self._etag = resp.headers["ETag"]
            if "Last-Modified" in resp.headers:
                self._last_modified = resp.headers["Last-Modified"]

        # ── Content hash check ────────────────────────────
        content_hash = hashlib.sha256(body.encode()).hexdigest()
        if content_hash == self._last_hash:
            if self.settings.log_level == "DEBUG":
                notifier.print_no_changes(self.config.name)
            return
        self._last_hash = content_hash

        # ── Parse ─────────────────────────────────────────
        incidents = parse_feed(
            body,
            feed_type=self.config.feed_type,
            provider_name=self.config.name,
        )

        if not incidents:
            return

        # ── First run: show historical ────────────────────
        if self._first_run:
            self._first_run = False
            if self.settings.show_historical:
                historical = incidents[: self.settings.max_historical]
                notifier.print_historical_header(len(historical))
                for inc in historical:
                    notifier.print_incident(inc, is_new=False)
            # Seed the seen set with ALL current incidents
            for inc in incidents:
                self._seen_ids.add(inc.id)
                self._seen_updates[inc.id] = self._incident_hash(inc)
                _tracker.incident_count += 1
            notifier.print_watching()
            return

        # ── Diff: find new or updated incidents ───────────
        for inc in incidents:
            inc_hash = self._incident_hash(inc)

            if inc.id not in self._seen_ids:
                # Brand new incident
                notifier.print_separator()
                notifier.print_incident(inc, is_new=True)
                self._seen_ids.add(inc.id)
                self._seen_updates[inc.id] = inc_hash
                _tracker.incident_count += 1

            elif self._seen_updates.get(inc.id) != inc_hash:
                # Existing incident got updated
                notifier.print_separator()
                notifier.print_incident(inc, is_new=False)
                self._seen_updates[inc.id] = inc_hash
                _tracker.incident_count += 1

    def _backoff_delay(self) -> float:
        """
        Calculate exponential backoff with jitter.

        delay = base * 2^(attempts-1) + random jitter
        Capped at 5 minutes.
        """
        exp = min(self._consecutive_errors, self.settings.max_retries)
        base_delay = self.settings.base_backoff * (2 ** (exp - 1))
        jitter = random.uniform(0, base_delay * 0.5)
        return min(base_delay + jitter, 300.0)

    @staticmethod
    def _incident_hash(incident: Incident) -> str:
        """
        Create a lightweight hash of an incident's mutable fields.
        Used to detect updates to existing incidents.
        """
        fingerprint = f"{incident.status}|{incident.summary}|{incident.product_names}"
        return hashlib.md5(fingerprint.encode()).hexdigest()
