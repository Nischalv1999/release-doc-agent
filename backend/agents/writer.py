"""Writer Agent - Generates the actual release documentation content."""
from openai import OpenAI

SYSTEM_PROMPT = """You are a Release Writer Agent. You produce polished documentation 
based on a plan and source evidence.

Rules:
1. Only include facts supported by the source evidence
2. Write clearly and concisely
3. Use appropriate tone for each audience (technical vs customer-facing)
4. Include specific details (ticket numbers, affected endpoints) where relevant
5. Flag any areas where information is incomplete

Output a JSON object with:
- "changelog": markdown-formatted changelog
- "internal_release_notes": markdown-formatted internal notes
- "customer_release_notes": markdown-formatted customer-facing notes  
- "documentation_updates": list of {"doc_path": str, "section": str, "suggested_content": str, "action": str}"""


def write(digest: dict, plan: dict, relevant_docs: list[dict], client: OpenAI) -> dict:
    """Generate all release documentation artifacts."""
    user_content = f"""Write release documentation based on:

## Release Digest
Summary: {digest.get('summary', '')}
Risk Level: {digest.get('risk_level', '')}
Features: {digest.get('features', [])}
Bug Fixes: {digest.get('bug_fixes', [])}
Breaking Changes: {digest.get('breaking_changes', [])}
Affected Systems: {digest.get('affected_systems', [])}

## Documentation Plan
{_format_plan(plan)}

## Relevant Existing Documentation (for context and update suggestions)
{_format_docs(relevant_docs)}

Generate all documentation artifacts. Be thorough but concise."""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    import json
    return json.loads(response.choices[0].message.content)


def _format_plan(plan: dict) -> str:
    import json
    return json.dumps(plan, indent=2)


def _format_docs(docs: list[dict]) -> str:
    parts = []
    for d in docs:
        parts.append(f"### {d.get('path', 'unknown')}\n{d.get('content', '')[:500]}")
    return "\n\n".join(parts)
