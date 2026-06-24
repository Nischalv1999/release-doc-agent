"""Writer Agent - Generates polished release documentation content.

Handles edge cases:
- Empty plan
- No RAG context available
- Very large inputs (truncation to fit context)
- Malformed plan structure
"""
import logging


from .base import call_llm_with_retry, truncate_text, validate_writer_output, AgentError

logger = logging.getLogger("release_agent")

SYSTEM_PROMPT = """You are a Release Writer Agent. You produce polished documentation 
based on a plan and source evidence.

Output a JSON object with EXACTLY these fields:
- "changelog": markdown-formatted changelog (include version header, date, categorized changes)
- "internal_release_notes": markdown-formatted internal notes (technical detail, risk, affected systems)
- "customer_release_notes": markdown-formatted customer-facing notes (benefits-focused, no jargon)
- "documentation_updates": array of {"doc_path": string, "section": string, "suggested_content": string, "action": "add"|"update"|"review"}

Rules:
1. ONLY include facts supported by the source evidence
2. Write clearly and concisely; no filler
3. Changelog: use conventional format (## Added, ## Fixed, ## Changed, ## Breaking)
4. Internal notes: include ticket references, risk level, deployment notes
5. Customer notes: focus on benefits, not implementation; friendly tone
6. Doc updates: provide actual suggested content, not just "update this section"
7. If information is incomplete, note it explicitly rather than fabricating
8. Reference ticket numbers (e.g., AUTH-1234) where applicable"""


def write(
    digest: dict,
    plan: dict,
    relevant_docs: list[dict],
    client,
    max_retries: int = 3,
) -> dict:
    """Generate all release documentation artifacts.
    
    Args:
        digest: Structured release digest
        plan: Documentation plan from Planner
        relevant_docs: RAG-retrieved document chunks
        client client instance
        max_retries: Number of retry attempts
        
    Returns:
        Validated documentation artifacts dictionary
    """
    # Handle degenerate case
    if not digest.get("summary") and not digest.get("features") and not digest.get("bug_fixes"):
        logger.warning("Writer received empty digest - returning minimal output")
        return {
            "changelog": "# Changelog\n\nNo significant changes in this release.",
            "internal_release_notes": "No significant changes.",
            "customer_release_notes": "No customer-facing changes in this release.",
            "documentation_updates": [],
        }

    user_content = _build_user_prompt(digest, plan, relevant_docs)

    result = call_llm_with_retry(
        client=client,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        agent_name="Writer",
        temperature=0.3,
        max_retries=max_retries,
    )

    return validate_writer_output(result)


def _build_user_prompt(digest: dict, plan: dict, relevant_docs: list[dict]) -> str:
    """Build writer prompt with truncation safety."""
    parts = ["Write release documentation based on:\n"]

    # Digest section
    parts.append("## Release Digest")
    parts.append(f"Summary: {digest.get('summary', 'N/A')}")
    parts.append(f"Risk Level: {digest.get('risk_level', 'unknown')}")

    features = digest.get("features", [])
    if features:
        parts.append(f"Features: {features}")

    bug_fixes = digest.get("bug_fixes", [])
    if bug_fixes:
        parts.append(f"Bug Fixes: {bug_fixes}")

    breaking = digest.get("breaking_changes", [])
    if breaking:
        parts.append(f"Breaking Changes: {breaking}")

    affected = digest.get("affected_systems", [])
    if affected:
        parts.append(f"Affected Systems: {affected}")

    # Plan section (truncate if huge)
    parts.append("\n## Documentation Plan")
    import json
    plan_text = json.dumps(plan, indent=2)
    parts.append(truncate_text(plan_text, 1500))

    # RAG context
    if relevant_docs:
        parts.append("\n## Relevant Existing Documentation (for context and update suggestions)")
        for d in relevant_docs[:5]:  # Max 5 chunks
            path = d.get("path", d.get("doc_path", "unknown"))
            section = d.get("section", "")
            content = truncate_text(d.get("content", ""), 400)
            parts.append(f"\n### {path} > {section}\n{content}")
    else:
        parts.append("\n## Relevant Existing Documentation\nNo relevant docs found via RAG.")

    parts.append("\nGenerate all documentation artifacts. Be thorough but concise.")
    return "\n".join(parts)
