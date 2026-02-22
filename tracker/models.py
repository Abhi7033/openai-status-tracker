"""
Data models for the status tracker.

Defines structured representations for incidents, affected components,
and provider configurations — keeping the codebase type-safe and clean.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass(frozen=True)
class Component:
    """A single affected service/product component."""

    name: str
    status: str  # e.g. "Operational", "Degraded Performance", "Major Outage"

    def __str__(self) -> str:
        return f"{self.name} ({self.status})" if self.status else self.name


@dataclass(frozen=True)
class Incident:
    """
    Represents a single incident from a status page feed.

    Attributes:
        id: Unique identifier (feed entry ID / GUID).
        title: Human-readable incident title.
        status: Current status (Resolved, Investigating, etc.).
        updated: When the incident was last updated.
        link: URL to the full incident page.
        summary: Cleaned text summary of the incident.
        components: List of affected components/products.
        provider: Name of the status page provider.
    """

    id: str
    title: str
    status: str
    updated: datetime
    link: str
    summary: str
    components: List[Component] = field(default_factory=list)
    provider: str = ""

    @property
    def product_names(self) -> str:
        """Comma-separated list of affected product names."""
        if not self.components:
            return "N/A"
        return ", ".join(c.name for c in self.components)


@dataclass
class ProviderConfig:
    """Configuration for a single status page provider."""

    name: str
    feed_url: str
    feed_type: str = "atom"  # "atom" or "rss"
    poll_interval: int = 30  # seconds


@dataclass
class TrackerSettings:
    """Global tracker settings."""

    log_level: str = "INFO"
    max_retries: int = 5
    base_backoff: int = 2
    show_historical: bool = True
    max_historical: int = 10
