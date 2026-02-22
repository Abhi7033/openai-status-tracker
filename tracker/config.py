"""
YAML configuration loader.

Reads config.yaml and produces typed ProviderConfig / TrackerSettings objects.
Falls back to sensible defaults if the config file is missing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

import yaml

from tracker.models import ProviderConfig, TrackerSettings

# Default path: config.yaml next to the project root
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

# Fallback if no config file exists at all
_DEFAULT_PROVIDER = ProviderConfig(
    name="OpenAI",
    feed_url="https://status.openai.com/history.atom",
    feed_type="atom",
    poll_interval=30,
)


def load_config(
    path: str | Path | None = None,
) -> Tuple[List[ProviderConfig], TrackerSettings]:
    """
    Load and parse the YAML configuration file.

    Returns:
        A tuple of (list of ProviderConfig, TrackerSettings).
    """
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH

    if not config_path.exists():
        print(f"⚠  Config file not found at {config_path}, using defaults.")
        return [_DEFAULT_PROVIDER], TrackerSettings()

    with open(config_path, "r") as fh:
        raw = yaml.safe_load(fh)

    # Parse providers
    providers: List[ProviderConfig] = []
    for entry in raw.get("providers", []):
        providers.append(
            ProviderConfig(
                name=entry["name"],
                feed_url=entry["feed_url"],
                feed_type=entry.get("feed_type", "atom"),
                poll_interval=entry.get("poll_interval", 30),
            )
        )

    if not providers:
        providers = [_DEFAULT_PROVIDER]

    # Parse global settings
    raw_settings = raw.get("settings", {})
    settings = TrackerSettings(
        log_level=raw_settings.get("log_level", "INFO"),
        max_retries=raw_settings.get("max_retries", 5),
        base_backoff=raw_settings.get("base_backoff", 2),
        show_historical=raw_settings.get("show_historical", True),
        max_historical=raw_settings.get("max_historical", 10),
    )

    return providers, settings
