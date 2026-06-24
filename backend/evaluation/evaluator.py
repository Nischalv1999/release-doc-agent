"""Evaluation Framework - Measures quality of generated documentation.

Metrics:
1. Hallucination Rate: How much of the output is unsupported by evidence
2. Ticket Coverage: Are all tickets mentioned somewhere in the output
3. Doc Recommendation Accuracy: Are doc update suggestions valid
4. Content Quality: Length, structure, completeness checks

Handles:
- Empty generated docs
- Empty ticket list
- Missing review data
- Edge case scoring (divide by zero, etc.)
"""
import re
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("release_agent")


@dataclass
class EvaluationResult:
    """Results from evaluating generated documentation."""
    hallucination_rate: float = 0.0
    ticket_coverage: float = 0.0
    doc_recommendation_accuracy: float = 0.0
    content_quality_score: float = 0.0
    overall_score: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "hallucination_rate": round(self.hallucination_rate, 3),
            "ticket_coverage": round(self.ticket_coverage, 3),
            "doc_recommendation_accuracy": round(self.doc_recommendation_accuracy, 3),
            "content_quality_score": round(self.content_quality_score, 3),
            "overall_score": round(self.overall_score, 3),
            "details": self.details,
        }


def evaluate(
    generated_docs: dict,
    review_result: dict,
    tickets: list[dict],
    existing_docs: list[dict],
) -> EvaluationResult:
    """Evaluate generated documentation quality across multiple dimensions.
    
    Args:
        generated_docs: Output from Writer agent
        review_result: Output from Reviewer agent
        tickets: Original Jira tickets (ground truth)
        existing_docs: Existing documentation corpus
        
    Returns:
        EvaluationResult with all metrics and detailed breakdown
    """
    result = EvaluationResult()

    # 1. Hallucination rate (from reviewer agent output)
    result.hallucination_rate = _compute_hallucination_rate(review_result)

    # 2. Ticket coverage
    result.ticket_coverage = _compute_ticket_coverage(generated_docs, tickets)

    # 3. Documentation recommendation accuracy
    result.doc_recommendation_accuracy = _compute_doc_accuracy(
        generated_docs, existing_docs
    )

    # 4. Content quality (structural checks)
    result.content_quality_score = _compute_content_quality(generated_docs)

    # 5. Overall score (weighted combination)
    result.overall_score = (
        (1.0 - result.hallucination_rate) * 0.35
        + result.ticket_coverage * 0.30
        + result.doc_recommendation_accuracy * 0.15
        + result.content_quality_score * 0.20
    )

    # Detailed breakdown for transparency
    result.details = _build_details(
        result, generated_docs, review_result, tickets, existing_docs
    )

    logger.info(
        f"Evaluation complete: overall={result.overall_score:.2f}, "
        f"hallucination={result.hallucination_rate:.2f}, "
        f"coverage={result.ticket_coverage:.2f}"
    )

    return result


def _compute_hallucination_rate(review_result: dict) -> float:
    """Compute hallucination rate from reviewer findings."""
    if not review_result:
        return 0.5  # Unknown quality = assume medium risk

    hallucination_issues = review_result.get("hallucination_issues", [])
    if not isinstance(hallucination_issues, list):
        return 0.0

    # Each issue adds 10%, capped at 100%
    return min(1.0, len(hallucination_issues) * 0.1)


def _compute_ticket_coverage(generated_docs: dict, tickets: list[dict]) -> float:
    """Check if all ticket keys appear in the generated text."""
    if not tickets:
        return 1.0  # No tickets to cover = perfect coverage

    ticket_keys = set()
    for t in tickets:
        key = t.get("key", "")
        if key:
            ticket_keys.add(key)

    if not ticket_keys:
        return 1.0

    all_text = _flatten_text(generated_docs).lower()
    mentioned_keys = set()

    for key in ticket_keys:
        # Case-insensitive search
        if key.lower() in all_text:
            mentioned_keys.add(key)

    return len(mentioned_keys) / len(ticket_keys)


def _compute_doc_accuracy(generated_docs: dict, existing_docs: list[dict]) -> float:
    """Verify that doc update suggestions reference real documents."""
    doc_updates = generated_docs.get("documentation_updates", [])

    if not doc_updates:
        # No suggestions made - neutral (not penalized)
        return 0.5

    existing_paths = set()
    for d in existing_docs:
        path = d.get("path", "")
        if path:
            existing_paths.add(path)
            # Also add without extension for fuzzy match
            existing_paths.add(path.rsplit(".", 1)[0] if "." in path else path)

    valid_count = 0
    for update in doc_updates:
        if not isinstance(update, dict):
            continue
        doc_path = update.get("doc_path", "")
        action = update.get("action", "")

        # "add" actions are always valid (new doc suggestions)
        if action == "add":
            valid_count += 1
        elif doc_path in existing_paths:
            valid_count += 1
        elif _fuzzy_path_match(doc_path, existing_paths):
            valid_count += 1

    return valid_count / len(doc_updates)


def _compute_content_quality(generated_docs: dict) -> float:
    """Structural quality checks on generated content."""
    scores = []

    # Check changelog has structure (headings, bullet points)
    changelog = generated_docs.get("changelog", "")
    if changelog:
        has_headings = "#" in changelog
        has_bullets = "-" in changelog or "*" in changelog
        has_substance = len(changelog.split()) > 20
        scores.append((int(has_headings) + int(has_bullets) + int(has_substance)) / 3)
    else:
        scores.append(0.0)

    # Check internal notes exist and have substance
    internal = generated_docs.get("internal_release_notes", "")
    if internal:
        has_substance = len(internal.split()) > 30
        has_structure = "\n" in internal
        scores.append((int(has_substance) + int(has_structure)) / 2)
    else:
        scores.append(0.0)

    # Check customer notes exist and are appropriate length
    customer = generated_docs.get("customer_release_notes", "")
    if customer:
        word_count = len(customer.split())
        # Customer notes should be concise (20-500 words)
        appropriate_length = 20 <= word_count <= 500
        no_jargon = not any(
            term in customer.lower()
            for term in ["endpoint", "api call", "middleware", "stack trace", "deployment"]
        )
        scores.append((int(appropriate_length) + int(no_jargon)) / 2)
    else:
        scores.append(0.0)

    # Check doc updates have content
    doc_updates = generated_docs.get("documentation_updates", [])
    if doc_updates:
        has_content = sum(
            1 for u in doc_updates
            if isinstance(u, dict) and len(u.get("suggested_content", "")) > 10
        )
        scores.append(has_content / len(doc_updates))
    else:
        scores.append(0.5)  # Neutral

    return sum(scores) / len(scores) if scores else 0.0


def _fuzzy_path_match(path: str, existing_paths: set[str]) -> bool:
    """Check if a path roughly matches any existing doc path."""
    if not path:
        return False
    path_lower = path.lower().replace("-", "").replace("_", "").replace(" ", "")
    for existing in existing_paths:
        existing_lower = existing.lower().replace("-", "").replace("_", "").replace(" ", "")
        if path_lower in existing_lower or existing_lower in path_lower:
            return True
    return False


def _flatten_text(docs: dict) -> str:
    """Flatten all generated documentation into a single string for analysis."""
    parts = [
        docs.get("changelog", ""),
        docs.get("internal_release_notes", ""),
        docs.get("customer_release_notes", ""),
    ]
    for update in docs.get("documentation_updates", []):
        if isinstance(update, dict):
            parts.append(update.get("suggested_content", ""))
            parts.append(update.get("doc_path", ""))
    return " ".join(parts)


def _build_details(
    result: EvaluationResult,
    generated_docs: dict,
    review_result: dict,
    tickets: list[dict],
    existing_docs: list[dict],
) -> dict:
    """Build detailed evaluation breakdown."""
    ticket_keys = {t.get("key", "") for t in tickets if t.get("key")}
    all_text = _flatten_text(generated_docs).lower()
    mentioned = {k for k in ticket_keys if k.lower() in all_text}

    return {
        "tickets_total": len(ticket_keys),
        "tickets_covered": len(mentioned),
        "tickets_missing": sorted(ticket_keys - mentioned),
        "hallucination_count": len(review_result.get("hallucination_issues", [])),
        "hallucination_details": review_result.get("hallucination_issues", []),
        "doc_updates_count": len(generated_docs.get("documentation_updates", [])),
        "reviewer_score": review_result.get("overall_score", 0),
        "reviewer_approved": review_result.get("approved", False),
        "content_lengths": {
            "changelog_words": len(generated_docs.get("changelog", "").split()),
            "internal_notes_words": len(generated_docs.get("internal_release_notes", "").split()),
            "customer_notes_words": len(generated_docs.get("customer_release_notes", "").split()),
        },
    }
