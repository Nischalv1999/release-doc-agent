"""Tests for the evaluation framework - all edge cases."""
import pytest
from evaluation.evaluator import (
    evaluate,
    EvaluationResult,
    _compute_hallucination_rate,
    _compute_ticket_coverage,
    _compute_doc_accuracy,
    _compute_content_quality,
    _fuzzy_path_match,
)


class TestHallucinationRate:
    def test_no_issues(self):
        assert _compute_hallucination_rate({"hallucination_issues": []}) == 0.0

    def test_one_issue(self):
        result = {"hallucination_issues": [{"text": "x", "reason": "y"}]}
        assert _compute_hallucination_rate(result) == 0.1

    def test_ten_plus_issues_capped(self):
        issues = [{"text": f"issue {i}", "reason": "r"} for i in range(15)]
        result = {"hallucination_issues": issues}
        assert _compute_hallucination_rate(result) == 1.0

    def test_empty_review(self):
        assert _compute_hallucination_rate({}) == 0.5

    def test_none_review(self):
        assert _compute_hallucination_rate(None) == 0.5

    def test_invalid_type(self):
        assert _compute_hallucination_rate({"hallucination_issues": "not a list"}) == 0.0


class TestTicketCoverage:
    def test_all_tickets_covered(self):
        docs = {"changelog": "AUTH-1234 AUTH-1235", "internal_release_notes": "", "customer_release_notes": "", "documentation_updates": []}
        tickets = [{"key": "AUTH-1234"}, {"key": "AUTH-1235"}]
        assert _compute_ticket_coverage(docs, tickets) == 1.0

    def test_partial_coverage(self):
        docs = {"changelog": "AUTH-1234 only", "internal_release_notes": "", "customer_release_notes": "", "documentation_updates": []}
        tickets = [{"key": "AUTH-1234"}, {"key": "AUTH-1235"}, {"key": "AUTH-1236"}]
        assert _compute_ticket_coverage(docs, tickets) == pytest.approx(1/3, abs=0.01)

    def test_no_tickets(self):
        docs = {"changelog": "something"}
        assert _compute_ticket_coverage(docs, []) == 1.0

    def test_case_insensitive(self):
        docs = {"changelog": "auth-1234", "internal_release_notes": "", "customer_release_notes": "", "documentation_updates": []}
        tickets = [{"key": "AUTH-1234"}]
        assert _compute_ticket_coverage(docs, tickets) == 1.0

    def test_ticket_in_doc_updates(self):
        docs = {
            "changelog": "",
            "internal_release_notes": "",
            "customer_release_notes": "",
            "documentation_updates": [{"suggested_content": "AUTH-1234 changes", "doc_path": ""}],
        }
        tickets = [{"key": "AUTH-1234"}]
        assert _compute_ticket_coverage(docs, tickets) == 1.0

    def test_tickets_with_missing_keys(self):
        docs = {"changelog": "something"}
        tickets = [{"key": ""}, {"summary": "no key"}]
        assert _compute_ticket_coverage(docs, tickets) == 1.0


class TestDocAccuracy:
    def test_all_valid_paths(self):
        docs = {"documentation_updates": [
            {"doc_path": "auth-guide.md", "action": "update"},
            {"doc_path": "api-reference.md", "action": "update"},
        ]}
        existing = [{"path": "auth-guide.md"}, {"path": "api-reference.md"}]
        assert _compute_doc_accuracy(docs, existing) == 1.0

    def test_add_action_always_valid(self):
        docs = {"documentation_updates": [
            {"doc_path": "new-doc.md", "action": "add"},
        ]}
        assert _compute_doc_accuracy(docs, []) == 1.0

    def test_no_updates_neutral(self):
        docs = {"documentation_updates": []}
        assert _compute_doc_accuracy(docs, []) == 0.5

    def test_invalid_paths(self):
        docs = {"documentation_updates": [
            {"doc_path": "nonexistent.md", "action": "update"},
        ]}
        existing = [{"path": "real-doc.md"}]
        assert _compute_doc_accuracy(docs, existing) == 0.0

    def test_fuzzy_matching(self):
        docs = {"documentation_updates": [
            {"doc_path": "auth_guide", "action": "update"},
        ]}
        existing = [{"path": "auth-guide.md"}]
        # Should fuzzy match
        assert _compute_doc_accuracy(docs, existing) == 1.0


class TestContentQuality:
    def test_good_content(self):
        docs = {
            "changelog": "# Changelog\n\n## Added\n- Enterprise SSO support via Okta integration for seamless single sign-on authentication\n- User provisioning through Okta directory sync with SCIM 2.0 support\n- Automatic user attribute synchronization\n\n## Fixed\n- URL encoding bug in OAuth callback that affected orgs with special characters",
            "internal_release_notes": "This release adds enterprise SSO.\n\nAffected: auth service, user management.\nRisk: Medium.",
            "customer_release_notes": "You can now sign in with your company Okta account for seamless authentication. Enterprise organizations can enable Single Sign-On to streamline team access management and improve security across your workspace.",
            "documentation_updates": [{"suggested_content": "Add SSO configuration section with step-by-step instructions."}],
        }
        score = _compute_content_quality(docs)
        assert score > 0.7

    def test_empty_content(self):
        docs = {"changelog": "", "internal_release_notes": "", "customer_release_notes": "", "documentation_updates": []}
        score = _compute_content_quality(docs)
        assert score < 0.3

    def test_customer_notes_with_jargon_penalized(self):
        docs = {
            "changelog": "# v1\n- change",
            "internal_release_notes": "Technical details here\nMultiple lines",
            "customer_release_notes": "We updated the API endpoint middleware stack trace deployment pipeline.",
            "documentation_updates": [],
        }
        score = _compute_content_quality(docs)
        # Jargon in customer notes should lower score
        assert score < 0.8


class TestFuzzyPathMatch:
    def test_exact_match(self):
        assert _fuzzy_path_match("auth-guide.md", {"auth-guide.md"})

    def test_no_match(self):
        assert not _fuzzy_path_match("totally-different.md", {"auth-guide.md"})

    def test_underscore_dash_equivalence(self):
        assert _fuzzy_path_match("auth_guide", {"auth-guide.md"})

    def test_empty_path(self):
        assert not _fuzzy_path_match("", {"auth-guide.md"})

    def test_substring_match(self):
        assert _fuzzy_path_match("auth", {"auth-guide.md"})


class TestFullEvaluation:
    def test_perfect_release(self):
        generated = {
            "changelog": "# Changelog\n## Added\n- AUTH-1234: SSO\n- AUTH-1235: fix\n- AUTH-1236: provisioning",
            "internal_release_notes": "AUTH-1234 AUTH-1235 AUTH-1236\nDetailed technical notes.\nRisk: medium.",
            "customer_release_notes": "You can now use Single Sign-On with Okta for easier login.",
            "documentation_updates": [
                {"doc_path": "auth-guide.md", "action": "update", "suggested_content": "Add SSO section with detailed configuration steps."},
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
        assert result.overall_score > 0.8

    def test_result_to_dict(self):
        result = EvaluationResult(
            hallucination_rate=0.1,
            ticket_coverage=0.8,
            doc_recommendation_accuracy=0.9,
            overall_score=0.85,
        )
        d = result.to_dict()
        assert d["hallucination_rate"] == 0.1
        assert "details" in d

    def test_empty_generated_docs(self):
        result = evaluate({}, {}, [], [])
        assert result.ticket_coverage == 1.0  # No tickets to miss
        assert result.content_quality_score < 0.5
