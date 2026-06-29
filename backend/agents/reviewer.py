"""Reviewer Agent - Reviews generated documentation for quality and accuracy.

Handles edge cases:
- Empty generated docs
- Missing source evidence
- Reviewer disagreeing with itself (normalized scoring)

Security exclusion verification is DETERMINISTIC: _verify_exclusions() checks in Python
that no excluded identifying terms (CVE IDs, ticket keys) appear in customer_release_notes.
This is independent of the LLM review and cannot be overridden by the LLM.
"""
import re
import logging

from .base import call_llm_with_retry, truncate_text, validate_review_output, AgentError
from .planner import extract_security_tokens

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
    client,
    plan: dict | None = None,
    max_retries: int = 3,
) -> dict:
    """Review generated documentation against source evidence.

    Args:
        generated_docs: Output from Writer agent
        digest: Original digest for cross-reference
        original_artifacts: Raw tickets and PRs for ground truth
        client: LLM client instance
        plan: Documentation plan from Planner (used for deterministic exclusion verification)
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

    # DETERMINISTIC STEP: verify security exclusions held.
    # This runs in Python and cannot be bypassed by LLM output.
    if plan:
        exclusion_leaks = _verify_exclusions(generated_docs, plan)
        if exclusion_leaks:
            validated["hallucination_issues"].extend(exclusion_leaks)
            validated["approved"] = False
            logger.warning(
                f"Reviewer: {len(exclusion_leaks)} security exclusion leak(s) detected — forcing approved=False"
            )

    # Enforce approval logic: never approve if hallucinations exist
    if validated["hallucination_issues"]:
        validated["approved"] = False
    if validated["overall_score"] < 7:
        validated["approved"] = False

    return validated


def _verify_exclusions(generated_docs: dict, plan: dict) -> list[dict]:
    """Python verification that security-excluded items did not leak into customer_release_notes.

    Extracts identifying tokens (CVE IDs, ticket keys) from each excluded item and
    checks if any appear literally in the customer_release_notes text.

    Returns a list of hallucination_issue dicts (empty = clean).
    """
    customer_notes = generated_docs.get("customer_release_notes", "") or ""
    exclusion_list = plan.get("exclusion_list", [])
    leaks: list[dict] = []

    for entry in exclusion_list:
        if "customer_release_notes" not in entry.get("exclude_from", []):
            continue
        item_text = entry.get("item", "")
        tokens = extract_security_tokens(item_text)
        for token in tokens:
            if token in customer_notes:
                leaks.append({
                    "text": token,
                    "reason": (
                        f"Security exclusion violation: '{token}' (from excluded item) "
                        f"appears in customer_release_notes. Reason for exclusion: {entry.get('reason', '')}"
                    ),
                })

    return leaks


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
        parts.append("\n### Original Jira Tickets")
        for t in tickets:
            key = t.get("key", "?")
            fields = t.get("fields", t)
            summary = fields.get("summary", t.get("summary", "?"))
            issuetype = (fields.get("issuetype") or {}).get("name", fields.get("type", "?"))
            priority = (fields.get("priority") or {}).get("name", fields.get("priority", "?"))
            parts.append(f"- [{key}] ({issuetype}, {priority}) {summary}")

    prs = original_artifacts.get("pull_requests", [])
    if prs:
        parts.append("\n### Original GitHub PRs")
        for p in prs:
            number = p.get("number", p.get("id", "?"))
            title = p.get("title", "?")
            labels = [lbl.get("name", str(lbl)) if isinstance(lbl, dict) else str(lbl) for lbl in p.get("labels", [])]
            parts.append(f"- PR #{number}: {title} (labels: {', '.join(labels)})")

    commits = original_artifacts.get("commits", [])
    if commits:
        parts.append("\n### Original GitHub Commits (summary)")
        for c in commits[:10]:
            sha = c.get("sha", "?")[:8]
            msg = (c.get("commit") or {}).get("message", c.get("message", "?"))
            first_line = msg.split("\n")[0] if msg else "?"
            parts.append(f"- [{sha}] {truncate_text(first_line, 120)}")
        if len(commits) > 10:
            parts.append(f"  ... and {len(commits) - 10} more commits")

    parts.append("\n\nReview thoroughly. Flag any hallucinations or missing coverage.")
    return "\n".join(parts)
