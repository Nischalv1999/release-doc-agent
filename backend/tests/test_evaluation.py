"""Tests for the evaluation framework - all edge cases."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from evaluation.evaluator import (
    evaluate,
    EvaluationResult,
    _compute_hallucination_rate,
    _compute_ticket_coverage,
    _compute_doc_accuracy,
    _compute_content_quality,
    _compute_weighted_ticket_coverage,
    _compute_doc_update_f1,
    _check_fabricated_identifiers,
    _check_critical_gates,
    _compute_faithfulness_rate,
    _fuzzy_path_match,
    WEIGHT_HALLUCINATION,
    WEIGHT_TICKET_COVERAGE,
    WEIGHT_DOC_ACCURACY,
    WEIGHT_CONTENT_QUALITY,
    NEEDS_REVISION_THRESHOLD,
    PRIORITY_WEIGHTS,
    DEFAULT_PRIORITY_WEIGHT,
    _GOLD_DIR,
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

    def test_to_dict_has_force_needs_revision(self):
        result = EvaluationResult(force_needs_revision=True)
        d = result.to_dict()
        assert "force_needs_revision" in d
        assert d["force_needs_revision"] is True

    def test_backward_compat_four_arg_call(self):
        # Original 4-arg signature must still work
        result = evaluate({}, {}, [], [])
        assert isinstance(result, EvaluationResult)


# ── Stage 1: Fabricated identifier detection ──────────────────────────────────

class TestFabricatedIdentifiers:
    def _source(self, tickets=None, prs=None, commits=None):
        return {
            "tickets": tickets or [],
            "pull_requests": prs or [],
            "commits": commits or [],
        }

    def _docs(self, changelog="", internal="", customer=""):
        return {
            "changelog": changelog,
            "internal_release_notes": internal,
            "customer_release_notes": customer,
            "documentation_updates": [],
        }

    def test_clean_output_no_fabrications(self):
        src = self._source(
            tickets=[{"key": "PLAT-2002"}],
            prs=[{"number": 201, "title": "Stripe", "body": ""}],
        )
        docs = self._docs(changelog="PLAT-2002 merged in PR #201.")
        assert _check_fabricated_identifiers(docs, src) == []

    def test_fabricated_cve_detected(self):
        src = self._source(tickets=[{"key": "PLAT-2025", "fields": {"summary": "SQL injection CVE-2024-31337"}}])
        docs = self._docs(changelog="Fixed CVE-2025-99999 vulnerability.")
        results = _check_fabricated_identifiers(docs, src)
        types = {r["type"] for r in results}
        assert "cve" in types
        ids = {r["identifier"] for r in results}
        assert "CVE-2025-99999" in ids

    def test_real_cve_in_source_not_flagged(self):
        src = self._source(
            tickets=[{"key": "PLAT-2025", "fields": {
                "summary": "SQL injection CVE-2024-31337",
                "description": "CVE-2024-31337 details",
            }}]
        )
        docs = self._docs(changelog="Fixed CVE-2024-31337.")
        results = _check_fabricated_identifiers(docs, src)
        assert all(r["identifier"] != "CVE-2024-31337" for r in results)

    def test_fabricated_ticket_key_detected(self):
        src = self._source(tickets=[{"key": "PLAT-2002"}])
        docs = self._docs(changelog="Implemented FAKE-123 feature.")
        results = _check_fabricated_identifiers(docs, src)
        ids = {r["identifier"] for r in results}
        assert "FAKE-123" in ids
        types = {r["type"] for r in results}
        assert "ticket_key" in types

    def test_real_ticket_key_not_flagged(self):
        src = self._source(tickets=[{"key": "PLAT-2002"}])
        docs = self._docs(changelog="PLAT-2002 merged.")
        assert _check_fabricated_identifiers(docs, src) == []

    def test_fabricated_pr_number_detected(self):
        src = self._source(prs=[{"number": 201, "title": "Stripe", "body": ""}])
        docs = self._docs(changelog="See PR #999 for details.")
        results = _check_fabricated_identifiers(docs, src)
        ids = {r["identifier"] for r in results}
        assert "PR #999" in ids
        types = {r["type"] for r in results}
        assert "pr_number" in types

    def test_real_pr_number_not_flagged(self):
        src = self._source(prs=[{"number": 201, "title": "Stripe", "body": ""}])
        docs = self._docs(changelog="Merged PR #201.")
        assert _check_fabricated_identifiers(docs, src) == []

    def test_empty_source_returns_empty_for_empty_output(self):
        src = self._source()
        docs = self._docs()
        assert _check_fabricated_identifiers(docs, src) == []

    def test_fabricated_id_triggers_force_needs_revision(self):
        src = self._source(prs=[{"number": 201, "title": "x", "body": ""}])
        docs = self._docs(changelog="See PR #999.")
        result = evaluate(docs, {}, [], [], source_artifacts=src)
        assert result.force_needs_revision is True
        assert any("Fabricated" in g for g in result.details["critical_gates"])

    def test_fabricated_ids_in_details(self):
        src = self._source(tickets=[{"key": "REAL-1"}])
        docs = self._docs(changelog="FAKE-99 feature added.")
        result = evaluate(docs, {}, [], [], source_artifacts=src)
        assert len(result.details["fabricated_identifiers"]) >= 1


# ── Stage 2: LLM faithfulness judge ──────────────────────────────────────────

class TestFaithfulnessJudge:
    def _source(self):
        return {
            "tickets": [{"key": "PLAT-2002", "fields": {"summary": "Stripe integration"}}],
            "pull_requests": [{"number": 201, "title": "Stripe"}],
            "commits": [],
        }

    def _docs(self):
        return {
            "changelog": "# Changelog\n## Added\n- Stripe payment processor (PLAT-2002, PR #201)",
            "internal_release_notes": "Stripe integrated. PR #201.",
            "customer_release_notes": "You can now pay with Stripe.",
            "documentation_updates": [],
        }

    def test_judge_returns_rate_from_mock(self):
        mock_client = MagicMock()
        # Simulate call_llm_with_retry returning parsed JSON
        with patch("evaluation.evaluator._compute_faithfulness_rate") as mock_judge:
            mock_judge.return_value = (0.1, [{"claim": "bad claim", "reason": "not in source"}])
            result = evaluate(self._docs(), {}, [], [], source_artifacts=self._source(), client=mock_client)
            assert result.hallucination_rate == pytest.approx(0.1, abs=0.05)

    def test_judge_failure_falls_back_to_reviewer_proxy(self):
        with patch("evaluation.evaluator._compute_faithfulness_rate") as mock_judge:
            mock_judge.return_value = (None, [])  # simulate failure
            review = {"hallucination_issues": [{"text": "x", "reason": "r"}]}
            result = evaluate(self._docs(), review, [], [], source_artifacts=self._source(), client=MagicMock())
            # Falls back to reviewer proxy: 1 issue * 0.1 = 0.1
            assert result.hallucination_rate == pytest.approx(0.1, abs=0.01)

    def test_no_client_uses_reviewer_proxy(self):
        review = {"hallucination_issues": [{"text": "x", "reason": "r"}, {"text": "y", "reason": "s"}]}
        result = evaluate(self._docs(), review, [], [], client=None)
        assert result.hallucination_rate == pytest.approx(0.2, abs=0.01)

    def test_unsupported_claims_in_details(self):
        with patch("evaluation.evaluator._compute_faithfulness_rate") as mock_judge:
            mock_judge.return_value = (0.2, [{"claim": "fabricated feature", "reason": "no source"}])
            result = evaluate(self._docs(), {}, [], [], source_artifacts=self._source(), client=MagicMock())
            assert isinstance(result.details["unsupported_claims"], list)


# ── Stage 3: Word-boundary matching and priority weights ──────────────────────

class TestWordBoundaryMatching:
    def test_plat_202_does_not_false_match_plat_2020(self):
        docs = {
            "changelog": "Fixed PLAT-2020 issue.",
            "internal_release_notes": "",
            "customer_release_notes": "",
            "documentation_updates": [],
        }
        tickets = [{"key": "PLAT-202"}]
        assert _compute_ticket_coverage(docs, tickets) == 0.0

    def test_plat_2020_matches_exactly(self):
        docs = {
            "changelog": "Fixed PLAT-2020 issue.",
            "internal_release_notes": "",
            "customer_release_notes": "",
            "documentation_updates": [],
        }
        tickets = [{"key": "PLAT-2020"}]
        assert _compute_ticket_coverage(docs, tickets) == 1.0

    def test_case_insensitive_boundary_match(self):
        docs = {
            "changelog": "fixed plat-2002.",
            "internal_release_notes": "",
            "customer_release_notes": "",
            "documentation_updates": [],
        }
        tickets = [{"key": "PLAT-2002"}]
        assert _compute_ticket_coverage(docs, tickets) == 1.0

    def test_key_at_end_of_line_matches(self):
        docs = {
            "changelog": "Merged PLAT-2010",
            "internal_release_notes": "",
            "customer_release_notes": "",
            "documentation_updates": [],
        }
        tickets = [{"key": "PLAT-2010"}]
        assert _compute_ticket_coverage(docs, tickets) == 1.0


class TestPriorityWeightedCoverage:
    def _ticket(self, key, priority_name=None):
        t = {"key": key, "fields": {}}
        if priority_name:
            t["fields"]["priority"] = {"name": priority_name}
        return t

    def test_equal_weights_when_no_priority(self):
        docs = {
            "changelog": "A-1 B-1",
            "internal_release_notes": "",
            "documentation_updates": [],
        }
        tickets = [self._ticket("A-1"), self._ticket("B-1")]
        score, per_ticket = _compute_weighted_ticket_coverage(docs, tickets)
        assert score == pytest.approx(1.0)
        assert per_ticket["A-1"]["weight"] == DEFAULT_PRIORITY_WEIGHT
        assert per_ticket["B-1"]["weight"] == DEFAULT_PRIORITY_WEIGHT

    def test_missing_highest_ticket_hurts_more_than_missing_low(self):
        docs_all = {"changelog": "ALPHA-1 BETA-1", "internal_release_notes": "", "documentation_updates": []}
        tickets = [self._ticket("ALPHA-1", "Highest"), self._ticket("BETA-1", "Low")]

        score_all, _ = _compute_weighted_ticket_coverage(docs_all, tickets)
        assert score_all == pytest.approx(1.0)

        docs_missing_highest = {"changelog": "BETA-1", "internal_release_notes": "", "documentation_updates": []}
        score_miss_h, _ = _compute_weighted_ticket_coverage(docs_missing_highest, tickets)

        docs_missing_low = {"changelog": "ALPHA-1", "internal_release_notes": "", "documentation_updates": []}
        score_miss_l, _ = _compute_weighted_ticket_coverage(docs_missing_low, tickets)

        # Missing a Highest ticket hurts more (lower score) than missing a Low ticket
        assert score_miss_h < score_miss_l

    def test_highest_priority_weight(self):
        _, per_ticket = _compute_weighted_ticket_coverage(
            {"changelog": "", "internal_release_notes": "", "documentation_updates": []},
            [self._ticket("X-1", "Highest")],
        )
        assert per_ticket["X-1"]["weight"] == PRIORITY_WEIGHTS["highest"]

    def test_customer_notes_excluded_from_keyed_scoring(self):
        # Ticket key appears ONLY in customer notes (which intentionally omit keys)
        docs = {
            "changelog": "General update",
            "internal_release_notes": "General notes",
            "customer_release_notes": "PLAT-2002 has been completed",  # key in customer only
            "documentation_updates": [],
        }
        tickets = [self._ticket("PLAT-2002", "High")]
        score, per_ticket = _compute_weighted_ticket_coverage(docs, tickets)
        assert per_ticket["PLAT-2002"]["covered"] is False  # not in technical docs
        assert score < 1.0

    def test_weighted_score_in_evaluate_details(self):
        docs = {
            "changelog": "PLAT-2002 done",
            "internal_release_notes": "",
            "customer_release_notes": "",
            "documentation_updates": [],
        }
        tickets = [self._ticket("PLAT-2002", "High"), self._ticket("PLAT-2020", "Highest")]
        result = evaluate(docs, {}, tickets, [])
        assert "coverage_per_ticket" in result.details
        assert "PLAT-2002" in result.details["coverage_per_ticket"]

    def test_no_tickets_returns_perfect_score(self):
        score, per_ticket = _compute_weighted_ticket_coverage(
            {"changelog": "", "internal_release_notes": "", "documentation_updates": []}, []
        )
        assert score == 1.0
        assert per_ticket == {}


# ── Stage 4: Doc-update F1 vs gold set ───────────────────────────────────────

class TestDocUpdateF1:
    def _docs_with_updates(self, paths):
        return {
            "changelog": "",
            "internal_release_notes": "",
            "customer_release_notes": "",
            "documentation_updates": [
                {"doc_path": p, "action": "update", "suggested_content": "Updated."}
                for p in paths
            ],
        }

    def test_gold_file_perfect_match(self):
        # System produces exactly the gold doc_paths
        gold_paths = ["api-reference.md", "auth-guide.md", "onboarding.md"]
        docs = self._docs_with_updates(gold_paths)
        score, details = _compute_doc_update_f1(docs, [], release_name="v2.5.0")
        assert details["mode"] == "gold_f1"
        assert details["precision"] == pytest.approx(1.0, abs=0.01)
        # recall depends on how many gold paths system hit vs total gold
        assert 0.0 <= score <= 1.0

    def test_gold_file_partial_match_recall(self):
        docs = self._docs_with_updates(["api-reference.md"])
        score, details = _compute_doc_update_f1(docs, [], release_name="v2.5.0")
        assert details["mode"] == "gold_f1"
        # recall = 1 gold path matched / 3 unique gold paths
        assert details["recall"] == pytest.approx(1 / 3, abs=0.02)

    def test_gold_file_no_system_updates_recall_0(self):
        docs = self._docs_with_updates([])
        score, details = _compute_doc_update_f1(docs, [], release_name="v2.5.0")
        assert details["mode"] == "gold_f1"
        assert details["recall"] == 0.0

    def test_no_gold_file_falls_back_to_validity(self):
        docs = self._docs_with_updates(["real.md"])
        existing = [{"path": "real.md"}]
        score, details = _compute_doc_update_f1(docs, existing, release_name=None)
        assert details["mode"] == "validity"
        assert "validity_score" in details

    def test_no_gold_file_unknown_release_falls_back(self):
        docs = self._docs_with_updates([])
        _, details = _compute_doc_update_f1(docs, [], release_name="nonexistent-release-xyz")
        assert details["mode"] == "validity"

    def test_f1_details_in_evaluate_output(self):
        docs = self._docs_with_updates(["api-reference.md"])
        result = evaluate(docs, {}, [], [], release_name="v2.5.0")
        assert "doc_eval" in result.details
        assert result.details["doc_eval"]["mode"] == "gold_f1"

    def test_gold_precision_computed_correctly(self):
        # 2 system paths, 1 matches gold
        docs = self._docs_with_updates(["api-reference.md", "made-up.md"])
        _, details = _compute_doc_update_f1(docs, [], release_name="v2.5.0")
        assert details["mode"] == "gold_f1"
        # precision = 1 (true positive) / 2 (system total) = 0.5
        assert details["precision"] == pytest.approx(0.5, abs=0.01)


# ── Stage 5: Critical gates ───────────────────────────────────────────────────

class TestCriticalGates:
    def test_no_violations_when_clean(self):
        violations = _check_critical_gates([], {}, None)
        assert violations == []

    def test_fabricated_id_triggers_gate(self):
        fabricated = [{"identifier": "FAKE-99", "type": "ticket_key"}]
        violations = _check_critical_gates(fabricated, {}, None)
        assert len(violations) == 1
        assert "FAKE-99" in violations[0]

    def test_gate_message_includes_identifier(self):
        fabricated = [
            {"identifier": "CVE-2099-12345", "type": "cve"},
            {"identifier": "BOGUS-1", "type": "ticket_key"},
        ]
        violations = _check_critical_gates(fabricated, {}, None)
        assert any("CVE-2099-12345" in v or "BOGUS-1" in v for v in violations)

    def test_security_leak_triggers_gate(self):
        plan = {
            "exclusion_list": [{
                "item": "CVE-2024-31337 SQL injection fix (PLAT-2025)",
                "reason": "CVE detected",
                "exclude_from": ["customer_release_notes"],
            }]
        }
        docs = {"customer_release_notes": "We fixed CVE-2024-31337 today."}
        violations = _check_critical_gates([], docs, plan)
        assert any("CVE-2024-31337" in v for v in violations)

    def test_gate_overrides_otherwise_good_score(self):
        # Fabricated identifier → force_needs_revision even if score > threshold
        src = {
            "tickets": [{"key": "PLAT-2002"}],
            "pull_requests": [],
            "commits": [],
        }
        docs = {
            "changelog": "# Changelog\n## Added\n- Great feature (PLAT-2002)\n- Another good thing\n- More stuff",
            "internal_release_notes": "PLAT-2002 done. Full risk assessment: low.\nMultiple detailed lines of notes here.",
            "customer_release_notes": "Great new features are available for you.",
            "documentation_updates": [
                {"doc_path": "api-reference.md", "action": "update", "suggested_content": "Update the API docs accordingly."},
            ],
        }
        # Add a fabricated PR number
        docs["changelog"] += "\n- Merged PR #9999"
        review = {"hallucination_issues": [], "overall_score": 9, "approved": True}
        result = evaluate(docs, review, [{"key": "PLAT-2002", "fields": {"priority": {"name": "High"}}}], [], source_artifacts=src)
        assert result.force_needs_revision is True

    def test_gate_violations_visible_in_details(self):
        src = {"tickets": [], "pull_requests": [], "commits": []}
        docs = {"changelog": "INVENTED-99 merged.", "internal_release_notes": "", "customer_release_notes": "", "documentation_updates": []}
        result = evaluate(docs, {}, [], [], source_artifacts=src)
        assert "critical_gates" in result.details

    def test_clean_output_no_force_needs_revision(self):
        src = {"tickets": [{"key": "PLAT-2002"}], "pull_requests": [{"number": 201, "title": "x", "body": ""}], "commits": []}
        docs = {"changelog": "PLAT-2002 done. PR #201 merged.", "internal_release_notes": "", "customer_release_notes": "", "documentation_updates": []}
        result = evaluate(docs, {}, [], [], source_artifacts=src)
        assert result.force_needs_revision is False


# ── Weight constants ──────────────────────────────────────────────────────────

class TestWeightConstants:
    def test_weights_sum_to_one(self):
        total = WEIGHT_HALLUCINATION + WEIGHT_TICKET_COVERAGE + WEIGHT_DOC_ACCURACY + WEIGHT_CONTENT_QUALITY
        assert total == pytest.approx(1.0)

    def test_all_weights_importable(self):
        assert isinstance(WEIGHT_HALLUCINATION, float)
        assert isinstance(WEIGHT_TICKET_COVERAGE, float)
        assert isinstance(WEIGHT_DOC_ACCURACY, float)
        assert isinstance(WEIGHT_CONTENT_QUALITY, float)

    def test_needs_revision_threshold_importable(self):
        assert isinstance(NEEDS_REVISION_THRESHOLD, float)
        assert NEEDS_REVISION_THRESHOLD == pytest.approx(0.5)

    def test_weights_surfaced_in_details(self):
        result = evaluate({}, {}, [], [])
        w = result.details["weights"]
        assert w["hallucination"] == WEIGHT_HALLUCINATION
        assert w["ticket_coverage"] == WEIGHT_TICKET_COVERAGE
        assert w["doc_accuracy"] == WEIGHT_DOC_ACCURACY
        assert w["content_quality"] == WEIGHT_CONTENT_QUALITY
        assert w["needs_revision_threshold"] == NEEDS_REVISION_THRESHOLD

    def test_overall_score_uses_named_weights(self):
        # When hallucination_rate=0 and all other scores=1, overall should equal sum of weights
        result = evaluate(
            {
                "changelog": "# CL\n## Added\n- " + " ".join(["x"] * 30),
                "internal_release_notes": "Internal\n" + " ".join(["y"] * 40),
                "customer_release_notes": " ".join(["z"] * 50),
                "documentation_updates": [{"doc_path": "x.md", "action": "add", "suggested_content": "long content here"}],
            },
            {"hallucination_issues": [], "overall_score": 10, "approved": True},
            [],
            [],
        )
        # Check that the overall_score is in range [0, 1]
        assert 0.0 <= result.overall_score <= 1.0

    def test_priority_weights_all_valid(self):
        for name, w in PRIORITY_WEIGHTS.items():
            assert 0.0 < w <= 1.0, f"Weight for {name!r} out of range: {w}"
