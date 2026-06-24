"""Tests for data connectors."""
import pytest
from connectors.github import GitHubConnector
from connectors.jira import JiraConnector
from connectors.docs import DocsConnector


def test_github_mock_commits():
    gh = GitHubConnector(use_mock=True)
    commits = gh.get_commits()
    assert len(commits) == 7
    assert commits[0]["sha"] == "a1b2c3d"
    assert "files_changed" in commits[0]


def test_github_mock_prs():
    gh = GitHubConnector(use_mock=True)
    prs = gh.get_pull_requests()
    assert len(prs) == 2
    assert prs[0]["state"] == "merged"


def test_jira_mock_all_tickets():
    jira = JiraConnector(use_mock=True)
    tickets = jira.get_tickets()
    assert len(tickets) == 3


def test_jira_mock_filtered():
    jira = JiraConnector(use_mock=True)
    tickets = jira.get_tickets(ticket_keys=["AUTH-1234"])
    assert len(tickets) == 1
    assert tickets[0]["key"] == "AUTH-1234"


def test_docs_connector():
    docs = DocsConnector()
    documents = docs.get_all_documents()
    assert len(documents) == 3
    assert all("content" in d for d in documents)
    assert all("path" in d for d in documents)


def test_github_real_raises():
    gh = GitHubConnector(use_mock=False)
    with pytest.raises(NotImplementedError):
        gh.get_commits()
