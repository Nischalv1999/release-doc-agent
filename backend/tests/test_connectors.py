"""Tests for data connectors - edge cases and happy paths."""
import pytest
from pathlib import Path
from connectors.github import GitHubConnector
from connectors.jira import JiraConnector
from connectors.docs import DocsConnector


class TestGitHubConnector:
    def test_mock_commits_returns_list(self):
        gh = GitHubConnector(use_mock=True)
        commits = gh.get_commits()
        assert isinstance(commits, list)
        assert len(commits) > 0

    def test_mock_commits_have_required_fields(self):
        gh = GitHubConnector(use_mock=True)
        commits = gh.get_commits()
        for c in commits:
            assert "sha" in c
            # GitHub REST format: message lives inside the nested "commit" object
            assert "commit" in c
            assert "message" in c["commit"]

    def test_mock_prs_returns_merged(self):
        gh = GitHubConnector(use_mock=True)
        prs = gh.get_pull_requests()
        assert len(prs) > 0
        # GitHub REST: merged PRs have state=closed + merged=True/merged_at populated
        for pr in prs:
            assert pr.get("merged") is True or pr.get("merged_at")

    def test_mock_prs_have_number_and_title(self):
        gh = GitHubConnector(use_mock=True)
        prs = gh.get_pull_requests()
        for pr in prs:
            assert "number" in pr
            assert "title" in pr

    def test_real_api_raises_not_implemented(self):
        gh = GitHubConnector(use_mock=False)
        with pytest.raises(NotImplementedError):
            gh.get_commits()
        with pytest.raises(NotImplementedError):
            gh.get_pull_requests()


class TestJiraConnector:
    def test_mock_all_tickets(self):
        jira = JiraConnector(use_mock=True)
        tickets = jira.get_tickets()
        assert len(tickets) > 0

    def test_mock_filter_by_keys(self):
        jira = JiraConnector(use_mock=True)
        tickets = jira.get_tickets(ticket_keys=["PLAT-2002"])
        assert len(tickets) == 1
        assert tickets[0]["key"] == "PLAT-2002"

    def test_mock_filter_nonexistent_key(self):
        jira = JiraConnector(use_mock=True)
        tickets = jira.get_tickets(ticket_keys=["NONEXIST-999"])
        assert len(tickets) == 0

    def test_mock_filter_empty_list(self):
        jira = JiraConnector(use_mock=True)
        tickets = jira.get_tickets(ticket_keys=[])
        assert len(tickets) == 0

    def test_tickets_have_required_fields(self):
        jira = JiraConnector(use_mock=True)
        tickets = jira.get_tickets()
        for t in tickets:
            assert "key" in t
            # GitHub REST format: ticket fields are nested inside "fields"
            assert "fields" in t
            assert "summary" in t["fields"]
            assert "status" in t["fields"]

    def test_real_api_raises(self):
        jira = JiraConnector(use_mock=False)
        with pytest.raises(NotImplementedError):
            jira.get_tickets()


class TestDocsConnector:
    def test_loads_all_mock_docs(self):
        docs = DocsConnector()
        documents = docs.get_all_documents()
        assert len(documents) == 3

    def test_docs_have_required_fields(self):
        docs = DocsConnector()
        documents = docs.get_all_documents()
        for d in documents:
            assert "path" in d
            assert "title" in d
            assert "content" in d
            assert len(d["content"]) > 0

    def test_custom_docs_dir(self, tmp_path):
        # Create a temp doc
        (tmp_path / "test.md").write_text("# Test\nHello world")
        docs = DocsConnector(docs_dir=tmp_path)
        documents = docs.get_all_documents()
        assert len(documents) == 1
        assert documents[0]["content"] == "# Test\nHello world"

    def test_empty_dir(self, tmp_path):
        docs = DocsConnector(docs_dir=tmp_path)
        documents = docs.get_all_documents()
        assert documents == []
