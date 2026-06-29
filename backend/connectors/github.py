"""GitHub connector - loads commit and PR data from mock files or real API.

Supports:
- Mock data loading (default)
- Real GitHub API (stubbed, requires GITHUB_TOKEN)
- Graceful handling of missing/corrupted data files
"""
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("release_agent")
MOCK_DIR = Path(__file__).parent.parent / "mock_data"


class GitHubConnector:
    """Fetches commits and pull requests. Uses mock data by default."""

    def __init__(self, use_mock: bool = True, token: str | None = None):
        self.use_mock = use_mock
        self.token = token

    def get_commits(
        self, repo: str = "", since: str = "", until: str = ""
    ) -> list[dict[str, Any]]:
        """Get commits from the repository.
        
        Args:
            repo: Repository name (org/repo format)
            since: ISO timestamp for start range
            until: ISO timestamp for end range
            
        Returns:
            List of commit objects
        """
        if self.use_mock:
            return self._load_mock("commits.json")

        if not self.token:
            raise NotImplementedError(
                "Real GitHub API requires GITHUB_TOKEN environment variable. "
                "Set use_mock_data=True to use sample data."
            )
        # Real implementation would use httpx to call GitHub API
        raise NotImplementedError("Real GitHub API integration not yet implemented")

    def get_pull_requests(
        self, repo: str = "", state: str = "merged"
    ) -> list[dict[str, Any]]:
        """Get pull requests from the repository.
        
        Args:
            repo: Repository name
            state: PR state filter (open, closed, merged)
            
        Returns:
            List of PR objects
        """
        if self.use_mock:
            prs = self._load_mock("pull_requests.json")
            if state == "merged":
                # GitHub API: merged PRs have state="closed" and merged=True
                prs = [pr for pr in prs if pr.get("merged") is True or pr.get("merged_at")]
            elif state:
                prs = [pr for pr in prs if pr.get("state") == state]
            return prs

        if not self.token:
            raise NotImplementedError(
                "Real GitHub API requires GITHUB_TOKEN environment variable."
            )
        raise NotImplementedError("Real GitHub API integration not yet implemented")

    def _load_mock(self, filename: str) -> list[dict[str, Any]]:
        """Load mock data with error handling."""
        filepath = MOCK_DIR / filename
        if not filepath.exists():
            logger.error(f"Mock data file not found: {filepath}")
            return []
        try:
            data = json.loads(filepath.read_text())
            if not isinstance(data, list):
                logger.error(f"Expected list in {filename}, got {type(data)}")
                return []
            return data
        except json.JSONDecodeError as e:
            logger.error(f"Corrupted mock data: {filename}: {e}")
            return []
