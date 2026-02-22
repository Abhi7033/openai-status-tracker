"""
OpenAI Status Tracker — Real-time service monitor.

An async, event-driven status page monitor that tracks incidents
from OpenAI (and any Atom/RSS-based status page) efficiently.
"""

__version__ = "1.0.0"

# Shared incident counter for the health-check endpoint
incident_count = 0
