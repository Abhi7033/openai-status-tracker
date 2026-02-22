# OpenAI Status Tracker

A lightweight, event-driven Python application that automatically tracks and logs service updates from the [OpenAI Status Page](https://status.openai.com/). Detects new incidents, outages, and degradations in real time and prints structured updates to the console.

Built as a submission for the Bolna Backend Engineering Hackathon.

---

## Table of Contents

- [Problem Understanding](#problem-understanding)
- [Approach and Design Decisions](#approach-and-design-decisions)
- [Architecture](#architecture)
- [Installation](#installation)
- [Usage](#usage)
- [Sample Output](#sample-output)
- [Configuration](#configuration)
- [Scaling to 100+ Providers](#scaling-to-100-providers)
- [Testing](#testing)
- [Deployment](#deployment)
- [Project Structure](#project-structure)

---

## Problem Understanding

The task is to monitor the OpenAI Status Page and automatically detect when a new incident, outage, or degradation is posted. When a change is detected, the program should print:

- The affected product/service
- The latest status message

The key constraint in the problem statement:

> *"You should not rely on manually refreshing the page or polling it inefficiently — the expectation is to use a more event-based approach that can scale efficiently if the same solution were used to track 100+ similar status pages from different providers."*

This rules out naive approaches like periodic HTML scraping or brute-force polling. The solution must be bandwidth-efficient, change-aware, and architecturally ready to monitor many providers concurrently without linear resource growth.

---

## Approach and Design Decisions

### Why Atom Feeds (Not HTML Scraping)

The OpenAI status page (powered by [incident.io](https://incident.io)) exposes structured feeds at:

- `https://status.openai.com/history.atom` (Atom 1.0)
- `https://status.openai.com/history.rss` (RSS 2.0)

These are the **official machine-readable interfaces** for status updates. Most major status pages (GitHub, Stripe, Twilio, Atlassian-powered pages) expose identical feed formats. By consuming Atom/RSS instead of scraping HTML:

- We get structured data (title, timestamp, affected components, status) without fragile CSS/XPath selectors
- We're immune to UI redesigns
- We work with any provider that follows the same convention

### Why Conditional HTTP (Not Blind Polling)

The solution uses **efficient feed-based change detection with state tracking** rather than blind polling. Every request to the feed includes `ETag` and `If-Modified-Since` headers from the previous response. When the feed hasn't changed, the server responds with `304 Not Modified` — an empty response body that consumes almost zero bandwidth.

As a second layer, feed responses are SHA-256 hashed locally. Even if the server doesn't support conditional headers, we skip parsing entirely when the content hash matches the previous poll.

This makes the approach **near-zero-cost when nothing has changed**, which is the common case for status pages.

### Why Async I/O (Not Threads)

Each provider is monitored by a `FeedMonitor` coroutine running in a single `asyncio` event loop. Adding 100 providers does not spawn 100 threads or 100 processes — all I/O is multiplexed through `aiohttp` on one thread.

This is the same concurrency model used by production monitoring systems. Resource consumption stays flat regardless of provider count.

### Why Exponential Backoff with Jitter

Transient failures (network errors, 429 rate limits, DNS issues) are handled with exponential backoff and random jitter. This prevents thundering herd problems when many monitors retry simultaneously after a shared failure (e.g., local network outage).

---

## Architecture

```
+-----------------------------------------------------+
|                    StatusTracker                     |
|                   (Orchestrator)                     |
+-----------------------------------------------------+
|                                                     |
|  +-----------+   +-----------+   +---------------+  |
|  |FeedMonitor|   |FeedMonitor|   |  FeedMonitor  |  |
|  | (OpenAI)  |   | (Stripe)  |   | (Provider N)  |  |
|  +-----+-----+   +-----+-----+   +-------+-------+  |
|        |               |                 |          |
|        v               v                 v          |
|  +-----------------------------------------------------+
|  |           Async Event Loop (asyncio + aiohttp)       |
|  |     Conditional GET  |  ETag  |  If-Modified-Since   |
|  +-----------------------------------------------------+
|        |               |                 |          |
|        v               v                 v          |
|  +-----------------------------------------------------+
|  |              FeedParser (Atom / RSS)                 |
|  |      Extracts incidents, status, and components      |
|  +-----------------------------------------------------+
|        |                                                |
|        v                                                |
|  +-----------------------------------------------------+
|  |             ConsoleNotifier (Output)                 |
|  |    Timestamped, colored, structured console logs     |
|  +-----------------------------------------------------+
+-----------------------------------------------------+

Data flow:
  Feed URL --> Conditional HTTP --> Content Hash Check
    --> XML Parse --> Diff Against Seen IDs --> Print New/Updated
```

**Key components:**

| Module | Responsibility |
|---|---|
| `main.py` | Entry point. Creates one `FeedMonitor` per provider, launches them concurrently, handles graceful shutdown. |
| `monitor.py` | Core engine. Conditional HTTP fetching, content hashing, seen-ID tracking, backoff logic. |
| `feed_parser.py` | Parses Atom 1.0 and RSS 2.0 XML into structured `Incident` objects. Extracts status, summary, and affected components from HTML content. |
| `models.py` | Typed data models — `Incident`, `Component`, `ProviderConfig`, `TrackerSettings`. |
| `notifier.py` | Formats and prints incidents to the console in the specification format. |
| `config.py` | Loads `config.yaml` into typed configuration objects. Falls back to sensible defaults. |

---

## Installation

```bash
git clone https://github.com/Abhi7033/openai-status-tracker.git
cd openai-status-tracker

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

**Dependencies** (minimal, no heavy frameworks):
- `aiohttp` — async HTTP client
- `aiofiles` — async file I/O
- `pyyaml` — YAML config parsing
- `python-dateutil` — flexible datetime parsing

---

## Usage

```bash
# Activate the virtual environment
source venv/bin/activate

# Run the tracker
python -m tracker

# Or run directly
python tracker/main.py
```

The tracker will:
1. Fetch the current feed and display recent historical incidents
2. Enter a watch loop, checking for new or updated incidents every 30 seconds
3. Print any new incidents as they appear
4. Stop cleanly on `Ctrl+C`

---

## Sample Output

```
[2026-02-20 22:44:27] Product: OpenAI API - Conversations
Status: Resolved - All impacted services have now fully recovered.

  [2026-02-20 22:44:27] INCIDENT UPDATE
    Provider : OpenAI
    Title    : Increased latency in ChatGPT for some users
    Status   : Resolved
    Products : Conversations
    Detail   : All impacted services have now fully recovered.
    Link     : https://status.openai.com//incidents/01KHYH2KT8VNWS146V0S09MF29

[2026-02-18 16:40:22] Product: OpenAI API - Video generation
Status: Resolved - All impacted services have now fully recovered.

  [2026-02-18 16:40:22] INCIDENT UPDATE
    Provider : OpenAI
    Title    : Sora 2 Degraded Performance
    Status   : Resolved
    Products : Video generation
    Detail   : All impacted services have now fully recovered.
    Link     : https://status.openai.com//incidents/01KHRP7P1JF885BYA8SDWBDBR1
```

The first two lines of each block (`[timestamp] Product:` / `Status:`) match the specification format. The indented detail block provides additional context (title, link, full component list) for operational use.

---

## Configuration

All settings live in `config.yaml`:

```yaml
providers:
  - name: OpenAI
    feed_url: https://status.openai.com/history.atom
    feed_type: atom
    poll_interval: 30

settings:
  log_level: INFO
  max_retries: 5
  base_backoff: 2
  show_historical: true
  max_historical: 10
```

---

## Scaling to 100+ Providers

The problem statement specifically asks for a solution that scales to 100+ status pages. Here is how this architecture handles it:

**Adding a provider is a config change, not a code change:**

```yaml
providers:
  - name: OpenAI
    feed_url: https://status.openai.com/history.atom
    feed_type: atom
    poll_interval: 30

  - name: GitHub
    feed_url: https://www.githubstatus.com/history.atom
    feed_type: atom
    poll_interval: 30

  - name: Stripe
    feed_url: https://status.stripe.com/history.atom
    feed_type: atom
    poll_interval: 45
```

**Why it stays efficient at scale:**

| Concern | How it is handled |
|---|---|
| Concurrency | All monitors run as coroutines in a single event loop. No thread-per-provider overhead. |
| Bandwidth | Conditional HTTP (ETag/If-Modified-Since) means most polls return 304 with zero body. |
| CPU | Content hashing skips XML parsing when nothing changed. Parsing only runs on actual updates. |
| Failures | Each monitor has independent backoff. One provider failing doesn't affect others. |
| Memory | Seen-ID sets grow only with the number of incidents (tens per provider), not with poll count. |

---

## Testing

```bash
source venv/bin/activate
python -m pytest tests/ -v
```

The test suite covers:
- HTML tag stripping and whitespace normalization
- Status extraction from incident HTML content
- Component parsing (single, multiple, deduplication, missing status)
- Full Atom feed parsing with real-world feed structure
- Full RSS feed parsing
- Feed type dispatch
- Incident model behavior (product name formatting, edge cases)

---

## Deployment

### Docker

```bash
docker build -t openai-status-tracker .
docker run --rm openai-status-tracker
```

### Render

A `render.yaml` is included for one-click deployment as a background worker.

---

## Project Structure

```
openai-status-tracker/
├── config.yaml              # Provider and settings configuration
├── requirements.txt         # Python dependencies
├── Dockerfile               # Container deployment
├── render.yaml              # Render.com worker deployment
├── README.md
├── tracker/
│   ├── __init__.py
│   ├── __main__.py          # python -m tracker entry point
│   ├── main.py              # Orchestrator, signal handling, lifecycle
│   ├── monitor.py           # Async feed monitor, conditional HTTP, change detection
│   ├── feed_parser.py       # Atom/RSS XML parser, incident extraction
│   ├── models.py            # Data models (Incident, Component, ProviderConfig)
│   ├── notifier.py          # Console output formatter
│   └── config.py            # YAML config loader with defaults
└── tests/
    ├── __init__.py
    └── test_feed_parser.py  # Unit tests for parsing and models
```
