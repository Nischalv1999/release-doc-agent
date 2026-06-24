"""GitHub connector - loads commit and PR data from mock files or real API."""
import json
from pathlib import Path
from typing import Any

MOCK_DIR = Path(__file__).parent.parent / "mock_data"


class GitHubConnector:
    """Fetches commits and pull requests. Uses mock data by default."""

    def __init__(self, use_mock: bool = True, token: str | None = None):
        self.use_mock = use_mock
        self.token = token

    def get_commits(self, repo: str = "", since: str = "", until: str = "") -> list[dict[str, Any]]:
        if self.use_mock:
            return json.loads((MOCK_DIR / "commits.json").read_text())
        raise NotImplementedError("Real GitHub API integration requires GITHUB_TOKEN")

    def get_pull_requests(self, repo: str = "", state: str = "merged") -> list[dict[str, Any]]:
        if self.use_mock:
            return json.loads((MOCK_DIR / "pull_requests.json").read_text())
        raise NotImplementedError("Real GitHub API integration requires GITHUB_TOKEN")
