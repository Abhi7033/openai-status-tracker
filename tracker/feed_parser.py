"""
Atom / RSS Feed Parser.

Parses XML feed content into structured Incident objects.
Supports both Atom and RSS 2.0 formats, extracting:
  - Incident title, ID, link, and update timestamp
  - Status (Resolved, Investigating, etc.)
  - Affected components/products with their operational state

Uses only the Python standard library (xml.etree) — no heavy
third-party XML dependencies needed.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List, Optional
from xml.etree import ElementTree as ET

from dateutil import parser as dateutil_parser

from tracker.models import Component, Incident

# Atom namespace
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

# Regex patterns for extracting structured data from HTML content
_STATUS_RE = re.compile(r"<b>Status:\s*(.+?)</b>", re.IGNORECASE)
_COMPONENT_RE = re.compile(r"<li>(.+?)</li>", re.IGNORECASE | re.DOTALL)
_COMPONENT_SPLIT_RE = re.compile(r"^(.+?)\s*\(([^)]+)\)\s*$")
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    clean = _HTML_TAG_RE.sub(" ", text)
    return " ".join(clean.split()).strip()


def _parse_status(html_content: str) -> str:
    """Extract the status string from HTML content (e.g. 'Resolved')."""
    match = _STATUS_RE.search(html_content)
    if match:
        return _strip_html(match.group(1)).strip()
    return "Unknown"


def _parse_components(html_content: str) -> List[Component]:
    """
    Extract affected components from HTML <li> tags.

    Each component may look like "Chat Completions (Operational)" or just
    "Chat Completions". We split on the trailing parenthesized status.
    """
    components: List[Component] = []
    seen: set = set()  # deduplicate

    for match in _COMPONENT_RE.finditer(html_content):
        raw = _strip_html(match.group(1)).strip()
        if not raw or raw in seen:
            continue
        seen.add(raw)

        split = _COMPONENT_SPLIT_RE.match(raw)
        if split:
            components.append(Component(name=split.group(1).strip(), status=split.group(2).strip()))
        else:
            components.append(Component(name=raw, status=""))

    return components


def _parse_summary_text(html_content: str) -> str:
    """
    Extract the human-readable summary, stripping status prefix
    and component lists for a cleaner message.
    """
    # Remove the status prefix
    text = _STATUS_RE.sub("", html_content)
    # Remove the affected components section
    idx = text.lower().find("<b>affected components</b>")
    if idx != -1:
        text = text[:idx]
    return _strip_html(text).strip()


def _safe_parse_datetime(dt_string: str) -> datetime:
    """Parse a datetime string flexibly, defaulting to UTC now on failure."""
    try:
        return dateutil_parser.parse(dt_string)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


# ─── Public API ───────────────────────────────────────────────


def parse_atom_feed(xml_text: str, provider_name: str = "") -> List[Incident]:
    """
    Parse an Atom feed XML string into a list of Incident objects.

    Args:
        xml_text: Raw XML string of the Atom feed.
        provider_name: Name to attach as the provider on each incident.

    Returns:
        List of Incident objects, newest first.
    """
    root = ET.fromstring(xml_text)
    incidents: List[Incident] = []

    for entry in root.findall("atom:entry", _ATOM_NS):
        entry_id = _get_text(entry, "atom:id", _ATOM_NS) or ""
        title = _strip_html(_get_text(entry, "atom:title", _ATOM_NS) or "")
        updated_str = _get_text(entry, "atom:updated", _ATOM_NS) or ""
        content = _get_text(entry, "atom:content", _ATOM_NS) or ""
        summary_html = _get_text(entry, "atom:summary", _ATOM_NS) or content

        # Link — prefer the href attribute
        link_el = entry.find("atom:link", _ATOM_NS)
        link = link_el.attrib.get("href", "") if link_el is not None else ""

        incidents.append(
            Incident(
                id=entry_id,
                title=title,
                status=_parse_status(summary_html),
                updated=_safe_parse_datetime(updated_str),
                link=link,
                summary=_parse_summary_text(summary_html),
                components=_parse_components(summary_html),
                provider=provider_name,
            )
        )

    return incidents


def parse_rss_feed(xml_text: str, provider_name: str = "") -> List[Incident]:
    """
    Parse an RSS 2.0 feed XML string into a list of Incident objects.

    Args:
        xml_text: Raw XML string of the RSS feed.
        provider_name: Name to attach as the provider on each incident.

    Returns:
        List of Incident objects, newest first.
    """
    root = ET.fromstring(xml_text)
    incidents: List[Incident] = []

    for item in root.iter("item"):
        guid = _get_text(item, "guid") or _get_text(item, "link") or ""
        title = _strip_html(_get_text(item, "title") or "")
        link = _get_text(item, "link") or ""
        pub_date = _get_text(item, "pubDate") or ""
        description = _get_text(item, "description") or ""

        # Try <content:encoded> first (richer), fall back to <description>
        content_encoded = _get_text(
            item,
            "{http://purl.org/rss/1.0/modules/content/}encoded",
        ) or description

        incidents.append(
            Incident(
                id=guid,
                title=title,
                status=_parse_status(content_encoded),
                updated=_safe_parse_datetime(pub_date),
                link=link,
                summary=_parse_summary_text(content_encoded),
                components=_parse_components(content_encoded),
                provider=provider_name,
            )
        )

    return incidents


def parse_feed(xml_text: str, feed_type: str = "atom", provider_name: str = "") -> List[Incident]:
    """
    Dispatch to the correct parser based on feed type.

    Args:
        xml_text: Raw XML feed content.
        feed_type: "atom" or "rss".
        provider_name: Provider display name.

    Returns:
        List of parsed Incident objects.
    """
    if feed_type.lower() == "rss":
        return parse_rss_feed(xml_text, provider_name)
    return parse_atom_feed(xml_text, provider_name)


# ─── Helpers ──────────────────────────────────────────────────


def _get_text(element: ET.Element, tag: str, ns: dict | None = None) -> Optional[str]:
    """Safely get text content from a child element."""
    child = element.find(tag, ns) if ns else element.find(tag)
    if child is not None and child.text:
        return child.text
    return None
