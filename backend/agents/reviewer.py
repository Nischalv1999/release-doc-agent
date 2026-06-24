"""Reviewer Agent - Reviews generated documentation for quality and accuracy.

Handles edge cases:
- Empty generated docs
- Missing source evidence
- Reviewer disagreeing with itself (normalized scoring)
"""
import logging
from openai import OpenAI

from .base import call_llm_with_retry, truncate_text, validate_review_output, AgentError

logger = logging.getLogger("release_agent")

SYSTEM_PROMPT = """You are a Documentation Reviewer Agent. You review generated release 
documentation for quality, accuracy, and completeness.

Check for:
1. HALLUCINATIONS: Claims not supported by source evidence (most critical)
2. MISSING COVERAGE: Tickets or changes not mentioned in any output
3. TONE CONSISTENCY: Technical for internal, friendly for customer-facing
4. COMPLETENESS: All planned sections present with sufficient detail
5. ACCURACY: Technical details (endpoints, ticket numbers) match source

Output a JSON object with EXACTLY these fields:
- "overall_score": integer 1-10 (10 = perfect, 7+ = acceptable)
- "hallucination_issues": array of {"text": string, "reason": string} (empty if none found)
- "missing_coverage": array of {"item": string, "source": string} (empty if full coverage)
- "tone_issues": array of {"section": string, "issue": string}
- "suggestions": array of strings (improvement suggestions)
- "approved": boolean (true ONLY if score >= 7 AND zero hallucinations)

Be strict about hallucinations. If a claim appears in the generated docs but has no 
corresponding evidence in the source, flag it. It is better to have false positives 
than to miss a hallucination."""


def review(
    generated_docs: dict,
    digest: dict,
    original_artifacts: dict,
    client: OpenAI,
    max_retries: int = 3,
) -> dict:
    """Review generated documentation against source evidence.
    
    Args:
        generated_docs: Output from Writer agent
        digest: Original digest for cross-reference
        original_artifacts: Raw tickets and PRs for ground truth
        client: OpenAI client instance
        max_retries: Number of retry attempts
        
    Returns:
        Validated review result dictionary
    """
    # Handle empty docs
    if not generated_docs or not any(generated_docs.values()):
        logger.warning("Reviewer received empty generated docs")
        return {
            "overall_score": 1,
            "hallucination_issues": [],
            "missing_coverage": [{"item": "all content", "source": "no docs generated"}],
            "tone_issues": [],
            "suggestions": ["No documentation was generated to review."],
            "approved": False,
        }

    user_content = _build_user_prompt(generated_docs, digest, original_artifacts)

    result = call_llm_with_retry(
        client=client,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        agent_name="Reviewer",
        temperature=0.1,
        max_retries=max_retries,
    )

    validated = validate_review_output(result)

    # Enforce approval logic: never approve if hallucinations exist
    if validated["hallucination_issues"]:
        validated["approved"] = False
    if validated["overall_score"] < 7:
        validated["approved"] = False

    return validated


def _build_user_prompt(
    generated_docs: dict,
    digest: dict,
    original_artifacts: dict,
) -> str:
    """Build review prompt with source evidence for comparison."""
    parts = ["Review this generated release documentation for quality and accuracy.\n"]

    # Generated content
    parts.append("## Generated Documentation")
    changelog = generated_docs.get("changelog", "")
    if changelog:
        parts.append(f"### Changelog\n{truncate_text(changelog, 1500)}")

    internal = generated_docs.get("internal_release_notes", "")
    if internal:
        parts.append(f"\n### Internal Notes\n{truncate_text(internal, 1500)}")

    customer = generated_docs.get("customer_release_notes", "")
    if customer:
        parts.append(f"\n### Customer Notes\n{truncate_text(customer, 1000)}")

    doc_updates = generated_docs.get("documentation_updates", [])
    if doc_updates:
        parts.append(f"\n### Doc Updates: {len(doc_updates)} suggestions")
        for u in doc_updates[:5]:
            parts.append(f"  - {u.get('doc_path', '?')}: {u.get('action', '?')}")

    # Source evidence (ground truth)
    parts.append("\n\n## Source Evidence (ground truth)")
    parts.append(f"Digest Summary: {digest.get('summary', 'N/A')}")
    parts.append(f"Features: {digest.get('features', [])}")
    parts.append(f"Bug Fixes: {digest.get('bug_fixes', [])}")
    parts.append(f"Affected Systems: {digest.get('affected_systems', [])}")

    tickets = original_artifacts.get("tickets", [])
    if tickets:
        parts.append("\n### Original Tickets")
        for t in tickets:
            key = t.get("key", "?")
            summary = t.get("summary", "?")
            parts.append(f"- [{key}] {summary}")

    prs = original_artifacts.get("pull_requests", [])
    if prs:
        parts.append("\n### Original PRs")
        for p in prs:
            parts.append(f"- PR #{p.get('id', '?')}: {p.get('title', '?')}")

    parts.append("\n\nReview thoroughly. Flag any hallucinations or missing coverage.")
    return "\n".join(parts)
