"""Jira connector - loads ticket data from mock files or real API.

Supports:
- Mock data loading (default)
- Filtering by ticket keys
- Real Jira API (stubbed, requires JIRA_TOKEN + JIRA_BASE_URL)
"""
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("release_agent")
MOCK_DIR = Path(__file__).parent.parent / "mock_data"


class JiraConnector:
    """Fetches Jira tickets. Uses mock data by default."""

    def __init__(
        self, use_mock: bool = True, base_url: str = "", token: str = ""
    ):
        self.use_mock = use_mock
        self.base_url = base_url
        self.token = token

    def get_tickets(
        self, ticket_keys: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Get Jira tickets, optionally filtered by keys.
        
        Args:
            ticket_keys: If provided, only return tickets with these keys.
                         If empty list, returns empty. If None, returns all.
                         
        Returns:
            List of ticket objects
        """
        if self.use_mock:
            return self._load_and_filter(ticket_keys)

        if not self.token or not self.base_url:
            raise NotImplementedError(
                "Real Jira API requires JIRA_TOKEN and JIRA_BASE_URL. "
                "Set use_mock_data=True to use sample data."
            )
        raise NotImplementedError("Real Jira API integration not yet implemented")

    def _load_and_filter(
        self, ticket_keys: list[str] | None
    ) -> list[dict[str, Any]]:
        """Load mock data and apply optional key filter."""
        filepath = MOCK_DIR / "jira_tickets.json"
        if not filepath.exists():
            logger.error(f"Mock data file not found: {filepath}")
            return []
        try:
            tickets = json.loads(filepath.read_text())
            if not isinstance(tickets, list):
                return []
        except json.JSONDecodeError:
            return []

        if ticket_keys is None:
            return tickets
        if not ticket_keys:
            return []
        key_set = set(ticket_keys)
        return [t for t in tickets if t.get("key") in key_set]
