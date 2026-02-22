"""
Tests for the feed parser module.

Validates that both Atom and RSS feeds are correctly parsed into
Incident objects with proper status, components, and metadata.
"""

import pytest
from datetime import datetime

from tracker.feed_parser import (
    parse_atom_feed,
    parse_rss_feed,
    parse_feed,
    _parse_status,
    _parse_components,
    _strip_html,
    _parse_summary_text,
)
from tracker.models import Component, Incident


# ─── Sample Feed Fixtures ─────────────────────────────────────

SAMPLE_ATOM_FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
    <id>https://status.openai.com/</id>
    <title>OpenAI status</title>
    <updated>2026-02-22T14:54:30.659Z</updated>
    <generator>incident.io</generator>
    <link rel="alternate" href="https://status.openai.com/"/>
    <subtitle>OpenAI status page updates</subtitle>
    <entry>
        <title type="html"><![CDATA[Increased latency in ChatGPT for some users]]></title>
        <id>https://status.openai.com//incidents/01KHYH2KT8VNWS146V0S09MF29</id>
        <link href="https://status.openai.com//incidents/01KHYH2KT8VNWS146V0S09MF29"/>
        <updated>2026-02-20T22:44:27.567Z</updated>
        <summary type="html"><![CDATA[<b>Status: Resolved</b><br/><br/>All impacted services have now fully recovered.<br/><br/><b>Affected components</b>
          <ul>
          <li>Conversations (Operational)</li>
          </ul>]]></summary>
        <content type="html"><![CDATA[<b>Status: Resolved</b><br/><br/>All impacted services have now fully recovered.<br/><br/><b>Affected components</b>
          <ul>
          <li>Conversations (Operational)</li>
          </ul>]]></content>
    </entry>
    <entry>
        <title type="html"><![CDATA[Sora 2 Degraded Performance]]></title>
        <id>https://status.openai.com//incidents/01KHRP7P1JF885BYA8SDWBDBR1</id>
        <link href="https://status.openai.com//incidents/01KHRP7P1JF885BYA8SDWBDBR1"/>
        <updated>2026-02-18T16:40:22.657Z</updated>
        <summary type="html"><![CDATA[<b>Status: Resolved</b><br/><br/>All impacted services have now fully recovered.<br/><br/><b>Affected components</b>
          <ul>
          <li>Video generation (Operational)</li>
          </ul>]]></summary>
        <content type="html"><![CDATA[<b>Status: Resolved</b><br/><br/>All impacted services have now fully recovered.<br/><br/><b>Affected components</b>
          <ul>
          <li>Video generation (Operational)</li>
          </ul>]]></content>
    </entry>
</feed>
"""

SAMPLE_RSS_FEED = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
    <channel>
        <title>OpenAI status</title>
        <link>https://status.openai.com/</link>
        <description>OpenAI status page updates</description>
        <item>
            <title><![CDATA[High error rate for Dall-e]]></title>
            <link>https://status.openai.com//incidents/01KEDRBQ2A3Y9JJ7G3F3YM4KT3</link>
            <guid>https://status.openai.com//incidents/01KEDRBQ2A3Y9JJ7G3F3YM4KT3</guid>
            <pubDate>Thu, 08 Jan 2026 02:45:00 GMT</pubDate>
            <description><![CDATA[<b>Status: Resolved</b><br/><br/>All impacted services have now fully recovered.<br/><br/><b>Affected components</b>
              <ul>
              <li>Images (Operational)</li>
              </ul>]]></description>
            <content:encoded><![CDATA[<b>Status: Resolved</b><br/><br/>All impacted services have now fully recovered.<br/><br/><b>Affected components</b>
              <ul>
              <li>Images (Operational)</li>
              </ul>]]></content:encoded>
        </item>
    </channel>
</rss>
"""


# ─── Tests ────────────────────────────────────────────────────


class TestStripHtml:
    def test_removes_tags(self):
        assert _strip_html("<b>Hello</b> <i>World</i>") == "Hello World"

    def test_collapses_whitespace(self):
        assert _strip_html("  foo   bar  ") == "foo bar"

    def test_empty_string(self):
        assert _strip_html("") == ""


class TestParseStatus:
    def test_resolved(self):
        html = "<b>Status: Resolved</b><br/>Details here"
        assert _parse_status(html) == "Resolved"

    def test_investigating(self):
        html = "<b>Status: Investigating</b><br/>Looking into it"
        assert _parse_status(html) == "Investigating"

    def test_unknown_when_missing(self):
        assert _parse_status("No status here") == "Unknown"


class TestParseComponents:
    def test_single_component(self):
        html = "<ul><li>Chat Completions (Operational)</li></ul>"
        components = _parse_components(html)
        assert len(components) == 1
        assert components[0].name == "Chat Completions"
        assert components[0].status == "Operational"

    def test_multiple_components(self):
        html = """<ul>
            <li>Conversations (Operational)</li>
            <li>Chat Completions (Degraded)</li>
            <li>Responses (Operational)</li>
        </ul>"""
        components = _parse_components(html)
        assert len(components) == 3
        assert components[1].name == "Chat Completions"
        assert components[1].status == "Degraded"

    def test_deduplication(self):
        html = "<ul><li>Images (Operational)</li><li>Images (Operational)</li></ul>"
        components = _parse_components(html)
        assert len(components) == 1

    def test_no_status_in_parens(self):
        html = "<ul><li>Some Service</li></ul>"
        components = _parse_components(html)
        assert len(components) == 1
        assert components[0].name == "Some Service"
        assert components[0].status == ""


class TestParseSummaryText:
    def test_strips_status_and_components(self):
        html = (
            "<b>Status: Resolved</b><br/><br/>All impacted services recovered."
            "<br/><br/><b>Affected components</b><ul><li>API (OK)</li></ul>"
        )
        summary = _parse_summary_text(html)
        assert "Resolved" not in summary
        assert "Affected components" not in summary
        assert "recovered" in summary


class TestParseAtomFeed:
    def test_parses_entries(self):
        incidents = parse_atom_feed(SAMPLE_ATOM_FEED, provider_name="OpenAI")
        assert len(incidents) == 2

    def test_first_entry_fields(self):
        incidents = parse_atom_feed(SAMPLE_ATOM_FEED, provider_name="OpenAI")
        inc = incidents[0]
        assert inc.title == "Increased latency in ChatGPT for some users"
        assert inc.status == "Resolved"
        assert inc.provider == "OpenAI"
        assert len(inc.components) == 1
        assert inc.components[0].name == "Conversations"
        assert "01KHYH2KT8VNWS146V0S09MF29" in inc.id

    def test_second_entry_fields(self):
        incidents = parse_atom_feed(SAMPLE_ATOM_FEED, provider_name="OpenAI")
        inc = incidents[1]
        assert inc.title == "Sora 2 Degraded Performance"
        assert inc.components[0].name == "Video generation"

    def test_incidents_have_links(self):
        incidents = parse_atom_feed(SAMPLE_ATOM_FEED)
        for inc in incidents:
            assert inc.link.startswith("https://")


class TestParseRssFeed:
    def test_parses_items(self):
        incidents = parse_rss_feed(SAMPLE_RSS_FEED, provider_name="OpenAI")
        assert len(incidents) == 1

    def test_item_fields(self):
        incidents = parse_rss_feed(SAMPLE_RSS_FEED, provider_name="OpenAI")
        inc = incidents[0]
        assert inc.title == "High error rate for Dall-e"
        assert inc.status == "Resolved"
        assert inc.components[0].name == "Images"


class TestParseFeedDispatch:
    def test_atom_dispatch(self):
        incidents = parse_feed(SAMPLE_ATOM_FEED, feed_type="atom", provider_name="Test")
        assert len(incidents) == 2

    def test_rss_dispatch(self):
        incidents = parse_feed(SAMPLE_RSS_FEED, feed_type="rss", provider_name="Test")
        assert len(incidents) == 1


class TestIncidentModel:
    def test_product_names(self):
        inc = Incident(
            id="1",
            title="Test",
            status="Resolved",
            updated=datetime.now(),
            link="",
            summary="",
            components=[
                Component(name="API", status="Operational"),
                Component(name="Chat", status="Degraded"),
            ],
        )
        assert inc.product_names == "API, Chat"

    def test_product_names_empty(self):
        inc = Incident(
            id="1",
            title="Test",
            status="Resolved",
            updated=datetime.now(),
            link="",
            summary="",
        )
        assert inc.product_names == "N/A"
