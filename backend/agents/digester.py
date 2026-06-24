"""Digester Agent - Analyzes raw engineering artifacts and produces structured summaries."""
from openai import OpenAI

SYSTEM_PROMPT = """You are a Release Digester Agent. Your job is to analyze raw engineering 
artifacts (commits, PRs, tickets) and produce a structured summary of what changed.

Output a JSON object with:
- "features": list of new features with brief descriptions
- "bug_fixes": list of bugs fixed with descriptions  
- "breaking_changes": list of any breaking changes
- "affected_systems": list of systems/services impacted
- "risk_level": "low" | "medium" | "high"
- "summary": 2-3 sentence overview of the release

Be precise. Only include information directly supported by the input artifacts.
Do NOT hallucinate or infer details not present in the data."""


def digest(commits: list, pull_requests: list, tickets: list, client: OpenAI) -> dict:
    """Digest raw artifacts into a structured release summary."""
    user_content = f"""Analyze these engineering artifacts for a release:

## Commits
{_format_commits(commits)}

## Pull Requests
{_format_prs(pull_requests)}

## Jira Tickets
{_format_tickets(tickets)}

Produce a structured JSON summary of this release."""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    import json
    return json.loads(response.choices[0].message.content)


def _format_commits(commits: list) -> str:
    lines = []
    for c in commits:
        lines.append(f"- [{c['sha']}] {c['message']} (by {c['author']}, {c['date']})")
        lines.append(f"  Files: {', '.join(c['files_changed'])}")
    return "\n".join(lines)


def _format_prs(prs: list) -> str:
    lines = []
    for pr in prs:
        lines.append(f"- PR #{pr['id']}: {pr['title']}")
        lines.append(f"  Description: {pr['description'][:500]}")
        lines.append(f"  Labels: {', '.join(pr['labels'])}")
    return "\n".join(lines)


def _format_tickets(tickets: list) -> str:
    lines = []
    for t in tickets:
        lines.append(f"- [{t['key']}] {t['summary']} ({t['type']}, {t['priority']})")
        lines.append(f"  Description: {t['description'][:300]}")
    return "\n".join(lines)
