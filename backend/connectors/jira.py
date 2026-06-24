"""Jira connector - loads ticket data from mock files or real API."""
import json
from pathlib import Path
from typing import Any

MOCK_DIR = Path(__file__).parent.parent / "mock_data"


class JiraConnector:
    """Fetches Jira tickets. Uses mock data by default."""

    def __init__(self, use_mock: bool = True, base_url: str = "", token: str = ""):
        self.use_mock = use_mock
        self.base_url = base_url
        self.token = token

    def get_tickets(self, ticket_keys: list[str] | None = None) -> list[dict[str, Any]]:
        if self.use_mock:
            tickets = json.loads((MOCK_DIR / "jira_tickets.json").read_text())
            if ticket_keys:
                return [t for t in tickets if t["key"] in ticket_keys]
            return tickets
        raise NotImplementedError("Real Jira API integration requires JIRA_TOKEN")
