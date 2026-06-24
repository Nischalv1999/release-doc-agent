"""Reviewer Agent - Reviews generated documentation for quality and accuracy."""
from openai import OpenAI

SYSTEM_PROMPT = """You are a Documentation Reviewer Agent. You review generated release 
documentation for quality, accuracy, and completeness.

Check for:
1. Hallucinations - claims not supported by source evidence
2. Missing coverage - tickets or changes not mentioned
3. Tone consistency - appropriate for the audience
4. Completeness - all planned sections present
5. Accuracy - technical details match the source

Output a JSON object with:
- "overall_score": 1-10 rating
- "hallucination_issues": list of {"text": str, "reason": str}
- "missing_coverage": list of {"item": str, "source": str}
- "tone_issues": list of {"section": str, "issue": str}
- "suggestions": list of improvement suggestions
- "approved": boolean (true if score >= 7 and no hallucinations)"""


def review(
    generated_docs: dict,
    digest: dict,
    original_artifacts: dict,
    client: OpenAI,
) -> dict:
    """Review generated documentation against source evidence."""
    user_content = f"""Review this generated release documentation for quality and accuracy.

## Generated Documentation
Changelog: {generated_docs.get('changelog', '')}

Internal Notes: {generated_docs.get('internal_release_notes', '')}

Customer Notes: {generated_docs.get('customer_release_notes', '')}

Doc Updates: {generated_docs.get('documentation_updates', [])}

## Source Evidence (ground truth)
Digest Summary: {digest.get('summary', '')}
Features: {digest.get('features', [])}
Bug Fixes: {digest.get('bug_fixes', [])}
Affected Systems: {digest.get('affected_systems', [])}

## Original Tickets
{_format_tickets(original_artifacts.get('tickets', []))}

## Original PRs
{_format_prs(original_artifacts.get('pull_requests', []))}

Review thoroughly. Flag any hallucinations or missing coverage."""

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


def _format_tickets(tickets: list) -> str:
    return "\n".join(f"- [{t['key']}] {t['summary']}" for t in tickets)


def _format_prs(prs: list) -> str:
    return "\n".join(f"- PR #{p['id']}: {p['title']}" for p in prs)
