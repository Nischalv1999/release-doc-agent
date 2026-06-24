"""Tests for the evaluation framework."""
from evaluation.evaluator import evaluate, EvaluationResult


def test_perfect_evaluation():
    generated = {
        "changelog": "## Changes\n- AUTH-1234: SSO\n- AUTH-1235: fix\n- AUTH-1236: provisioning",
        "internal_release_notes": "AUTH-1234 AUTH-1235 AUTH-1236",
        "customer_release_notes": "SSO support",
        "documentation_updates": [
            {"doc_path": "auth-guide.md", "action": "update", "suggested_content": "..."},
        ],
    }
    review = {"hallucination_issues": [], "overall_score": 9, "approved": True}
    tickets = [
        {"key": "AUTH-1234", "summary": "SSO"},
        {"key": "AUTH-1235", "summary": "fix"},
        {"key": "AUTH-1236", "summary": "provisioning"},
    ]
    existing_docs = [{"path": "auth-guide.md", "title": "Auth", "content": "..."}]

    result = evaluate(generated, review, tickets, existing_docs)
    assert result.hallucination_rate == 0.0
    assert result.ticket_coverage == 1.0
    assert result.doc_recommendation_accuracy == 1.0
    assert result.overall_score > 0.9


def test_missing_tickets():
    generated = {
        "changelog": "AUTH-1234 only",
        "internal_release_notes": "",
        "customer_release_notes": "",
        "documentation_updates": [],
    }
    review = {"hallucination_issues": [], "overall_score": 5, "approved": False}
    tickets = [
        {"key": "AUTH-1234", "summary": "SSO"},
        {"key": "AUTH-1235", "summary": "fix"},
        {"key": "AUTH-1236", "summary": "provisioning"},
    ]
    existing_docs = []

    result = evaluate(generated, review, tickets, existing_docs)
    assert result.ticket_coverage == pytest.approx(1 / 3, abs=0.01)


def test_hallucination_detected():
    generated = {
        "changelog": "AUTH-1234 AUTH-1235 AUTH-1236",
        "internal_release_notes": "",
        "customer_release_notes": "",
        "documentation_updates": [],
    }
    review = {
        "hallucination_issues": [
            {"text": "fake claim", "reason": "not in source"},
            {"text": "another fake", "reason": "fabricated"},
        ],
        "overall_score": 4,
        "approved": False,
    }
    tickets = [{"key": "AUTH-1234", "summary": "x"}, {"key": "AUTH-1235", "summary": "y"}, {"key": "AUTH-1236", "summary": "z"}]
    existing_docs = []

    result = evaluate(generated, review, tickets, existing_docs)
    assert result.hallucination_rate == 0.2


def test_evaluation_to_dict():
    result = EvaluationResult(
        hallucination_rate=0.1,
        ticket_coverage=0.8,
        doc_recommendation_accuracy=0.9,
        overall_score=0.85,
    )
    d = result.to_dict()
    assert d["hallucination_rate"] == 0.1
    assert "details" in d


# Import pytest for approx
import pytest
