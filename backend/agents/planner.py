"""Planner Agent - Decides what documentation artifacts to generate and their structure."""
from openai import OpenAI

SYSTEM_PROMPT = """You are a Release Documentation Planner Agent. Given a release digest summary 
and a list of existing documentation, you plan what documentation artifacts to produce.

Output a JSON object with:
- "changelog_plan": {"sections": [...], "tone": "technical"}
- "internal_notes_plan": {"audience": "engineering", "sections": [...], "include_risk": true}
- "customer_notes_plan": {"audience": "end-users", "sections": [...], "tone": "friendly"}
- "doc_update_plan": list of {"doc_path": str, "section": str, "action": "add|update|review", "reason": str}

Consider:
1. What level of detail each audience needs
2. Which existing docs are impacted by the changes
3. What new documentation sections might be needed
4. Risk level and whether to highlight breaking changes"""


def plan(digest: dict, existing_docs: list[dict], client: OpenAI) -> dict:
    """Create a documentation plan based on the digest and existing docs."""
    doc_list = "\n".join(
        f"- {d['path']}: {d['content'][:200]}..." for d in existing_docs
    )

    user_content = f"""Based on this release digest, plan the documentation artifacts:

## Release Digest
{_format_digest(digest)}

## Existing Documentation
{doc_list}

Create a structured plan for all documentation artifacts."""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    import json
    return json.loads(response.choices[0].message.content)


def _format_digest(digest: dict) -> str:
    lines = [f"Summary: {digest.get('summary', 'N/A')}"]
    lines.append(f"Risk Level: {digest.get('risk_level', 'unknown')}")
    lines.append(f"Affected Systems: {', '.join(digest.get('affected_systems', []))}")
    lines.append("Features:")
    for f in digest.get("features", []):
        lines.append(f"  - {f}")
    lines.append("Bug Fixes:")
    for b in digest.get("bug_fixes", []):
        lines.append(f"  - {b}")
    return "\n".join(lines)
