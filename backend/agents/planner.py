"""Planner Agent - Decides documentation structure based on digest and existing docs.

Handles edge cases:
- Empty digest (no features/fixes)
- No existing documentation
- Very large doc corpora (truncation)
"""
import logging
from openai import OpenAI

from .base import call_llm_with_retry, truncate_text, AgentError

logger = logging.getLogger("release_agent")

SYSTEM_PROMPT = """You are a Release Documentation Planner Agent. Given a release digest summary 
and a list of existing documentation, you plan what documentation artifacts to produce.

Output a JSON object with EXACTLY these fields:
- "changelog_plan": {"sections": [...], "tone": "technical"}
- "internal_notes_plan": {"audience": "engineering", "sections": [...], "include_risk": true}
- "customer_notes_plan": {"audience": "end-users", "sections": [...], "tone": "friendly"}
- "doc_update_plan": array of {"doc_path": string, "section": string, "action": "add"|"update"|"review", "reason": string}

Rules:
1. If no existing docs match the changes, doc_update_plan should suggest new sections
2. Consider what level of detail each audience needs
3. Always include risk assessment in internal notes if risk_level is medium or high
4. For customer notes, never include internal implementation details
5. If the release is a bug fix only, keep customer notes brief"""


def plan(
    digest: dict,
    existing_docs: list[dict],
    client: OpenAI,
    max_retries: int = 3,
) -> dict:
    """Create a documentation plan based on the digest and existing docs.
    
    Args:
        digest: Structured release digest from Digester agent
        existing_docs: List of existing documentation documents
        client: OpenAI client instance
        max_retries: Number of retry attempts
        
    Returns:
        Documentation plan dictionary
    """
    # Handle edge case: empty digest
    if not digest.get("features") and not digest.get("bug_fixes"):
        logger.warning("Planner received empty digest - generating minimal plan")
        return _minimal_plan()

    user_content = _build_user_prompt(digest, existing_docs)

    result = call_llm_with_retry(
        client=client,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        agent_name="Planner",
        temperature=0.2,
        max_retries=max_retries,
    )

    return _validate_plan(result)


def _build_user_prompt(digest: dict, existing_docs: list[dict]) -> str:
    parts = ["Based on this release digest, plan the documentation artifacts:\n"]

    parts.append("## Release Digest")
    parts.append(f"Summary: {digest.get('summary', 'N/A')}")
    parts.append(f"Risk Level: {digest.get('risk_level', 'unknown')}")
    parts.append(f"Affected Systems: {', '.join(digest.get('affected_systems', []))}")

    features = digest.get("features", [])
    if features:
        parts.append("Features:")
        for f in features[:20]:  # Cap at 20
            parts.append(f"  - {truncate_text(str(f), 200)}")

    bug_fixes = digest.get("bug_fixes", [])
    if bug_fixes:
        parts.append("Bug Fixes:")
        for b in bug_fixes[:20]:
            parts.append(f"  - {truncate_text(str(b), 200)}")

    breaking = digest.get("breaking_changes", [])
    if breaking:
        parts.append("BREAKING CHANGES:")
        for bc in breaking:
            parts.append(f"  - {truncate_text(str(bc), 200)}")

    if existing_docs:
        parts.append("\n## Existing Documentation")
        for d in existing_docs[:20]:  # Cap at 20 docs
            path = d.get("path", "unknown")
            content_preview = truncate_text(d.get("content", ""), 150)
            parts.append(f"- {path}: {content_preview}")
    else:
        parts.append("\n## Existing Documentation\nNo existing documentation found.")

    parts.append("\nCreate a structured plan for all documentation artifacts.")
    return "\n".join(parts)


def _minimal_plan() -> dict:
    """Return a minimal plan when there's nothing substantial to document."""
    return {
        "changelog_plan": {"sections": ["maintenance"], "tone": "technical"},
        "internal_notes_plan": {
            "audience": "engineering",
            "sections": ["summary"],
            "include_risk": False,
        },
        "customer_notes_plan": {
            "audience": "end-users",
            "sections": ["summary"],
            "tone": "friendly",
        },
        "doc_update_plan": [],
    }


def _validate_plan(result: dict) -> dict:
    """Ensure plan has required structure."""
    if "changelog_plan" not in result:
        result["changelog_plan"] = {"sections": ["changes"], "tone": "technical"}
    if "internal_notes_plan" not in result:
        result["internal_notes_plan"] = {
            "audience": "engineering",
            "sections": ["summary", "changes"],
            "include_risk": True,
        }
    if "customer_notes_plan" not in result:
        result["customer_notes_plan"] = {
            "audience": "end-users",
            "sections": ["summary"],
            "tone": "friendly",
        }
    if "doc_update_plan" not in result:
        result["doc_update_plan"] = []

    # Validate doc_update_plan entries
    valid_actions = {"add", "update", "review"}
    validated_updates = []
    for entry in result.get("doc_update_plan", []):
        if isinstance(entry, dict) and "doc_path" in entry:
            action = entry.get("action", "review")
            if action not in valid_actions:
                action = "review"
            validated_updates.append({
                "doc_path": str(entry["doc_path"]),
                "section": str(entry.get("section", "")),
                "action": action,
                "reason": str(entry.get("reason", "")),
            })
    result["doc_update_plan"] = validated_updates
    return result
