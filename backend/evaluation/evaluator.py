"""Evaluation Framework - Measures quality of generated documentation."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvaluationResult:
    """Results from evaluating generated documentation."""
    hallucination_rate: float = 0.0
    ticket_coverage: float = 0.0
    doc_recommendation_accuracy: float = 0.0
    overall_score: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "hallucination_rate": self.hallucination_rate,
            "ticket_coverage": self.ticket_coverage,
            "doc_recommendation_accuracy": self.doc_recommendation_accuracy,
            "overall_score": self.overall_score,
            "details": self.details,
        }


def evaluate(
    generated_docs: dict,
    review_result: dict,
    tickets: list[dict],
    existing_docs: list[dict],
) -> EvaluationResult:
    """Evaluate generated documentation quality."""
    result = EvaluationResult()

    # 1. Hallucination rate (from reviewer agent output)
    hallucination_issues = review_result.get("hallucination_issues", [])
    # Normalize: 0 issues = 0% rate, each issue adds ~10%
    result.hallucination_rate = min(1.0, len(hallucination_issues) * 0.1)

    # 2. Ticket coverage - check if all tickets are referenced
    ticket_keys = {t["key"] for t in tickets}
    mentioned_keys = set()
    all_text = _flatten_text(generated_docs)
    for key in ticket_keys:
        if key.lower() in all_text.lower():
            mentioned_keys.add(key)
    result.ticket_coverage = len(mentioned_keys) / max(len(ticket_keys), 1)

    # 3. Documentation recommendation accuracy
    doc_updates = generated_docs.get("documentation_updates", [])
    existing_paths = {d["path"] for d in existing_docs}
    if doc_updates:
        valid_recommendations = sum(
            1 for u in doc_updates
            if u.get("doc_path", "") in existing_paths or u.get("action") == "add"
        )
        result.doc_recommendation_accuracy = valid_recommendations / len(doc_updates)
    else:
        result.doc_recommendation_accuracy = 0.0

    # 4. Overall score (weighted combination)
    result.overall_score = (
        (1.0 - result.hallucination_rate) * 0.4
        + result.ticket_coverage * 0.35
        + result.doc_recommendation_accuracy * 0.25
    )

    result.details = {
        "tickets_total": len(ticket_keys),
        "tickets_covered": len(mentioned_keys),
        "tickets_missing": list(ticket_keys - mentioned_keys),
        "hallucination_count": len(hallucination_issues),
        "hallucination_details": hallucination_issues,
        "doc_updates_count": len(doc_updates),
        "reviewer_score": review_result.get("overall_score", 0),
        "reviewer_approved": review_result.get("approved", False),
    }

    return result


def _flatten_text(docs: dict) -> str:
    """Flatten all generated documentation into a single string for analysis."""
    parts = [
        docs.get("changelog", ""),
        docs.get("internal_release_notes", ""),
        docs.get("customer_release_notes", ""),
    ]
    for update in docs.get("documentation_updates", []):
        parts.append(update.get("suggested_content", ""))
    return " ".join(parts)
