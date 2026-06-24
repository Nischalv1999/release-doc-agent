"""Digester Agent - Analyzes raw engineering artifacts and produces structured summaries.

Handles edge cases:
- Empty commit lists
- PRs with no description
- Tickets with missing fields
- Extremely long inputs (truncation)
"""
import logging
from openai import OpenAI

from .base import (
    call_llm_with_retry,
    truncate_text,
    validate_digest_output,
    AgentError,
)

logger = logging.getLogger("release_agent")

SYSTEM_PROMPT = """You are a Release Digester Agent. Your job is to analyze raw engineering 
artifacts (commits, PRs, tickets) and produce a structured summary of what changed.

Output a JSON object with EXACTLY these fields:
- "features": array of strings describing new features
- "bug_fixes": array of strings describing bugs fixed
- "breaking_changes": array of strings (empty if none)
- "affected_systems": array of system/service names impacted
- "risk_level": exactly one of "low", "medium", "high"
- "summary": 2-3 sentence overview of the release

Rules:
1. ONLY include information directly supported by the input artifacts
2. Do NOT hallucinate or infer details not present in the data
3. If information is ambiguous, note it in the summary
4. Group related commits into single feature descriptions
5. Identify risk based on: scope of changes, systems affected, presence of breaking changes"""


def digest(
    commits: list,
    pull_requests: list,
    tickets: list,
    client: OpenAI,
    max_retries: int = 3,
) -> dict:
    """Digest raw artifacts into a structured release summary.
    
    Args:
        commits: List of commit objects
        pull_requests: List of PR objects
        tickets: List of Jira ticket objects
        client: OpenAI client instance
        max_retries: Number of retry attempts
        
    Returns:
        Validated digest dictionary
        
    Raises:
        AgentError: If digestion fails after retries
    """
    # Handle empty inputs gracefully
    if not commits and not pull_requests and not tickets:
        logger.warning("Digester received empty inputs")
        return {
            "features": [],
            "bug_fixes": [],
            "breaking_changes": [],
            "affected_systems": [],
            "risk_level": "low",
            "summary": "No artifacts found for this release.",
        }

    user_content = _build_user_prompt(commits, pull_requests, tickets)

    result = call_llm_with_retry(
        client=client,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        agent_name="Digester",
        temperature=0.1,
        max_retries=max_retries,
    )

    return validate_digest_output(result)


def _build_user_prompt(commits: list, pull_requests: list, tickets: list) -> str:
    """Build user prompt with safe handling of missing/malformed data."""
    parts = ["Analyze these engineering artifacts for a release:\n"]

    if commits:
        parts.append("## Commits")
        parts.append(_format_commits(commits))

    if pull_requests:
        parts.append("\n## Pull Requests")
        parts.append(_format_prs(pull_requests))

    if tickets:
        parts.append("\n## Jira Tickets")
        parts.append(_format_tickets(tickets))

    parts.append("\nProduce a structured JSON summary of this release.")
    return "\n".join(parts)


def _format_commits(commits: list) -> str:
    lines = []
    for c in commits:
        sha = c.get("sha", "unknown")[:7]
        message = c.get("message", "no message")
        author = c.get("author", "unknown")
        date = c.get("date", "")
        files = c.get("files_changed", [])

        lines.append(f"- [{sha}] {truncate_text(message, 200)} (by {author}, {date})")
        if files:
            lines.append(f"  Files: {', '.join(files[:10])}")  # Cap file list
            if len(files) > 10:
                lines.append(f"  ... and {len(files) - 10} more files")
    return "\n".join(lines)


def _format_prs(prs: list) -> str:
    lines = []
    for pr in prs:
        pr_id = pr.get("id", "?")
        title = pr.get("title", "untitled")
        description = pr.get("description", "")
        labels = pr.get("labels", [])

        lines.append(f"- PR #{pr_id}: {title}")
        if description:
            lines.append(f"  Description: {truncate_text(description, 500)}")
        if labels:
            lines.append(f"  Labels: {', '.join(labels[:10])}")
    return "\n".join(lines)


def _format_tickets(tickets: list) -> str:
    lines = []
    for t in tickets:
        key = t.get("key", "UNKNOWN")
        summary = t.get("summary", "no summary")
        ticket_type = t.get("type", "unknown")
        priority = t.get("priority", "unknown")
        description = t.get("description", "")

        lines.append(f"- [{key}] {summary} ({ticket_type}, {priority})")
        if description:
            lines.append(f"  Description: {truncate_text(description, 300)}")
    return "\n".join(lines)
