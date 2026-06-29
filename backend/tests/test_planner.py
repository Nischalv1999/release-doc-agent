"""Tests for the redesigned Planner agent (Stage 1-4 features).

Covers:
- Empty-plan guard: breaking-only release no longer collapses to _minimal_plan
- core_narrative: null for fix-only, string for themed releases
- exclusion_list: CVE-bearing items auto-added deterministically
- _verify_exclusions: fails if excluded term appears in customer_release_notes
- audience_outlines: 8-bullet cap enforced
- rag_search_queries: used by retrieval; empty list falls back to _build_rag_query
- _validate_plan: type-coercion and bounds on all new fields
- _enforce_security_exclusions: ticket-type and label signals
"""
import json
import pytest

from agents.planner import (
    _minimal_plan,
    _validate_plan,
    _enforce_security_exclusions,
    _build_user_prompt,
    extract_security_tokens,
    SYSTEM_PROMPT,
    plan,
)
from agents.reviewer import _verify_exclusions


# ── Mock LLM client ────────────────────────────────────────────────────────────

class _MockClient:
    """Minimal mock that returns a fixed JSON plan via the .chat() interface."""
    def __init__(self, response: dict | None = None):
        self._response = response or {
            "changelog_plan": {"sections": ["changes"], "tone": "technical"},
            "internal_notes_plan": {"audience": "engineering", "sections": ["summary"], "include_risk": True},
            "customer_notes_plan": {"audience": "end-users", "sections": ["summary"], "tone": "friendly"},
            "doc_update_plan": [],
            "core_narrative": "Payment stack modernised with Stripe",
            "exclusion_list": [],
            "audience_outlines": {
                "customer": ["Frame Stripe as a seamless checkout upgrade"],
                "internal": ["Detail JWT migration breaking steps"],
            },
            "rag_search_queries": ["Stripe checkout migration", "JWT auth guide"],
        }
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return json.dumps(self._response)


# ── Empty-plan guard fix ───────────────────────────────────────────────────────

class TestEmptyPlanGuard:
    def test_breaking_only_calls_llm_not_minimal(self):
        """A breaking-only digest (no features, no bug_fixes) must reach the LLM."""
        digest = {
            "features": [],
            "bug_fixes": [],
            "breaking_changes": ["BREAKING: payment schema changed (PLAT-2003, PR #201)"],
            "affected_systems": ["Payments"],
            "risk_level": "high",
            "summary": "Breaking change release.",
            "risk_rationale": [],
        }
        client = _MockClient()
        result = plan(digest, [], client)
        # The LLM was called
        assert len(client.calls) == 1
        # core_narrative is from LLM response, not _minimal_plan default
        assert result["core_narrative"] == "Payment stack modernised with Stripe"

    def test_truly_empty_digest_returns_minimal(self):
        """No features, no bug_fixes, no breaking_changes → _minimal_plan, no LLM call."""
        digest = {"features": [], "bug_fixes": [], "breaking_changes": [], "summary": ""}
        client = _MockClient()
        result = plan(digest, [], client)
        # LLM was NOT called
        assert len(client.calls) == 0
        # Returns minimal plan defaults
        assert result["core_narrative"] is None
        assert result["rag_search_queries"] == []

    def test_features_only_still_calls_llm(self):
        digest = {"features": ["Added X (PLAT-1, PR #1)"], "bug_fixes": [], "breaking_changes": []}
        client = _MockClient()
        plan(digest, [], client)
        assert len(client.calls) == 1

    def test_bug_fixes_only_still_calls_llm(self):
        digest = {"features": [], "bug_fixes": ["Fixed Y (PLAT-2, PR #2)"], "breaking_changes": []}
        client = _MockClient()
        plan(digest, [], client)
        assert len(client.calls) == 1


# ── core_narrative ─────────────────────────────────────────────────────────────

class TestCoreNarrative:
    def test_null_preserved_from_llm(self):
        """LLM returning null for core_narrative should be preserved."""
        result = _validate_plan({"core_narrative": None})
        assert result["core_narrative"] is None

    def test_string_preserved(self):
        result = _validate_plan({"core_narrative": "Payment stack modernised with Stripe"})
        assert result["core_narrative"] == "Payment stack modernised with Stripe"

    def test_non_string_non_none_coerced_to_string(self):
        result = _validate_plan({"core_narrative": 42})
        assert result["core_narrative"] == "42"

    def test_missing_defaults_to_none(self):
        result = _validate_plan({})
        assert result["core_narrative"] is None

    def test_empty_string_preserved(self):
        # Empty string is falsy but technically a string — coerce to None
        result = _validate_plan({"core_narrative": ""})
        assert result["core_narrative"] is None

    def test_fix_only_release_gets_null_from_llm(self):
        """For a fix-only release, LLM should return null (tested via mock)."""
        client = _MockClient(response={
            "changelog_plan": {"sections": ["fixes"], "tone": "technical"},
            "internal_notes_plan": {"audience": "engineering", "sections": ["summary"], "include_risk": False},
            "customer_notes_plan": {"audience": "end-users", "sections": ["summary"], "tone": "friendly"},
            "doc_update_plan": [],
            "core_narrative": None,
            "exclusion_list": [],
            "audience_outlines": {"customer": [], "internal": []},
            "rag_search_queries": [],
        })
        digest = {"features": [], "bug_fixes": ["Fixed login timeout bug (PLAT-50, PR #5)"], "breaking_changes": []}
        result = plan(digest, [], client)
        assert result["core_narrative"] is None

    def test_themed_release_has_string_core_narrative(self):
        """For a release with clear features, LLM returns a string (tested via mock)."""
        client = _MockClient()
        digest = {"features": ["Stripe integration (PLAT-2002, PR #201)"], "bug_fixes": [], "breaking_changes": []}
        result = plan(digest, [], client)
        assert isinstance(result["core_narrative"], str)
        assert len(result["core_narrative"]) > 0


# ── exclusion_list + _enforce_security_exclusions ─────────────────────────────

class TestSecurityExclusions:
    def _plan_with_empty_exclusion(self):
        return {
            "exclusion_list": [],
            "changelog_plan": {}, "internal_notes_plan": {}, "customer_notes_plan": {},
            "doc_update_plan": [], "core_narrative": None,
            "audience_outlines": {"customer": [], "internal": []}, "rag_search_queries": [],
        }

    def test_cve_item_added_to_exclusion_list(self):
        plan_dict = self._plan_with_empty_exclusion()
        digest = {
            "features": ["Fixed CVE-2024-1234: SQL injection in payment handler (PLAT-99, PR #10)"],
            "bug_fixes": [], "breaking_changes": [],
        }
        _enforce_security_exclusions(plan_dict, digest, [])
        assert len(plan_dict["exclusion_list"]) == 1
        entry = plan_dict["exclusion_list"][0]
        assert "customer_release_notes" in entry["exclude_from"]
        assert "CVE-2024-1234" in entry["reason"]

    def test_multiple_cve_item(self):
        plan_dict = self._plan_with_empty_exclusion()
        digest = {
            "features": ["Patched CVE-2024-0001 and CVE-2024-0002 (PLAT-50, PR #1)"],
            "bug_fixes": [], "breaking_changes": [],
        }
        _enforce_security_exclusions(plan_dict, digest, [])
        assert any("CVE-2024-0001" in e["reason"] for e in plan_dict["exclusion_list"])

    def test_security_ticket_label_triggers_exclusion(self):
        plan_dict = self._plan_with_empty_exclusion()
        tickets = [
            {"key": "SEC-42", "fields": {"labels": ["security-vulnerability"], "issuetype": {}, "components": [], "fixVersions": []}},
        ]
        digest = {
            "features": ["Fixed auth bypass (SEC-42, PR #77)"],
            "bug_fixes": [], "breaking_changes": [],
        }
        _enforce_security_exclusions(plan_dict, digest, tickets)
        assert len(plan_dict["exclusion_list"]) == 1
        assert "customer_release_notes" in plan_dict["exclusion_list"][0]["exclude_from"]

    def test_vulnerability_issue_type_triggers_exclusion(self):
        plan_dict = self._plan_with_empty_exclusion()
        tickets = [
            {"key": "VULN-7", "fields": {"labels": [], "issuetype": {"name": "Vulnerability"}, "components": [], "fixVersions": []}},
        ]
        digest = {
            "features": [],
            "bug_fixes": ["Resolved VULN-7: XSS in dashboard (PR #88)"],
            "breaking_changes": [],
        }
        _enforce_security_exclusions(plan_dict, digest, tickets)
        assert len(plan_dict["exclusion_list"]) == 1

    def test_normal_item_not_excluded(self):
        plan_dict = self._plan_with_empty_exclusion()
        digest = {
            "features": ["Added dark mode (PLAT-200, PR #55)"],
            "bug_fixes": [], "breaking_changes": [],
        }
        _enforce_security_exclusions(plan_dict, digest, [])
        assert len(plan_dict["exclusion_list"]) == 0

    def test_no_duplicate_exclusions(self):
        """If an item is already in exclusion_list, don't add it again."""
        item = "Fixed CVE-2024-1234 (PLAT-99, PR #10)"
        plan_dict = self._plan_with_empty_exclusion()
        plan_dict["exclusion_list"].append({
            "item": item,
            "reason": "already there",
            "exclude_from": ["customer_release_notes"],
        })
        digest = {"features": [item], "bug_fixes": [], "breaking_changes": []}
        _enforce_security_exclusions(plan_dict, digest, [])
        # Still only one entry
        assert len(plan_dict["exclusion_list"]) == 1

    def test_cve_in_breaking_change_also_excluded(self):
        plan_dict = self._plan_with_empty_exclusion()
        digest = {
            "features": [],
            "bug_fixes": [],
            "breaking_changes": ["BREAKING: Patched CVE-2024-9999 auth bypass (PLAT-1, PR #1)"],
        }
        _enforce_security_exclusions(plan_dict, digest, [])
        assert len(plan_dict["exclusion_list"]) == 1
        assert "customer_release_notes" in plan_dict["exclusion_list"][0]["exclude_from"]

    def test_full_plan_pipeline_auto_excludes_cve(self):
        """End-to-end: plan() with a CVE in the digest auto-adds the exclusion."""
        client = _MockClient()
        digest = {
            "features": ["Patched CVE-2024-5678: RCE in webhook handler (PLAT-300, PR #300)"],
            "bug_fixes": [],
            "breaking_changes": [],
            "summary": "Security patch.",
            "risk_level": "high",
            "risk_rationale": [],
            "affected_systems": [],
        }
        result = plan(digest, [], client)
        cve_exclusions = [
            e for e in result["exclusion_list"]
            if "CVE-2024-5678" in e.get("reason", "") or "CVE-2024-5678" in e.get("item", "")
        ]
        assert len(cve_exclusions) >= 1
        assert "customer_release_notes" in cve_exclusions[0]["exclude_from"]


# ── _verify_exclusions (reviewer) ─────────────────────────────────────────────

class TestVerifyExclusions:
    def test_cve_leak_in_customer_notes_detected(self):
        plan_dict = {
            "exclusion_list": [{
                "item": "Patched CVE-2024-1234 SQL injection (PLAT-99, PR #10)",
                "reason": "CVE reference",
                "exclude_from": ["customer_release_notes"],
            }]
        }
        generated_docs = {
            "changelog": "# Changelog\n\n## Fixed CVE-2024-1234",
            "internal_release_notes": "## Security fix: CVE-2024-1234",
            "customer_release_notes": "We patched a vulnerability. CVE-2024-1234 is now resolved.",
            "documentation_updates": [],
        }
        leaks = _verify_exclusions(generated_docs, plan_dict)
        assert len(leaks) >= 1
        assert any("CVE-2024-1234" in leak["text"] for leak in leaks)

    def test_ticket_key_leak_in_customer_notes_detected(self):
        plan_dict = {
            "exclusion_list": [{
                "item": "Fixed auth bypass (SEC-42, PR #77)",
                "reason": "Security ticket",
                "exclude_from": ["customer_release_notes"],
            }]
        }
        generated_docs = {
            "changelog": "",
            "internal_release_notes": "",
            "customer_release_notes": "We fixed an issue (SEC-42) that affected login.",
            "documentation_updates": [],
        }
        leaks = _verify_exclusions(generated_docs, plan_dict)
        assert any("SEC-42" in leak["text"] for leak in leaks)

    def test_clean_customer_notes_returns_empty_list(self):
        plan_dict = {
            "exclusion_list": [{
                "item": "Patched CVE-2024-1234 SQL injection (PLAT-99, PR #10)",
                "reason": "CVE reference",
                "exclude_from": ["customer_release_notes"],
            }]
        }
        generated_docs = {
            "changelog": "# Changelog\n\n## Fixed a security issue",
            "internal_release_notes": "## Security fix: CVE-2024-1234",
            "customer_release_notes": "We improved security and reliability. No action needed.",
            "documentation_updates": [],
        }
        leaks = _verify_exclusions(generated_docs, plan_dict)
        assert leaks == []

    def test_cve_in_changelog_not_internal_does_not_trigger(self):
        """Exclusion is only for customer_release_notes — CVE in other docs is fine."""
        plan_dict = {
            "exclusion_list": [{
                "item": "Fixed CVE-2024-9999 (PLAT-1, PR #1)",
                "reason": "CVE",
                "exclude_from": ["customer_release_notes"],
            }]
        }
        generated_docs = {
            "changelog": "## Security\n- Fixed CVE-2024-9999 (PLAT-1, PR #1)",
            "internal_release_notes": "Security: CVE-2024-9999 patched",
            "customer_release_notes": "We made security improvements.",
            "documentation_updates": [],
        }
        leaks = _verify_exclusions(generated_docs, plan_dict)
        assert leaks == []

    def test_empty_exclusion_list_returns_empty(self):
        leaks = _verify_exclusions(
            {"customer_release_notes": "Great release!"},
            {"exclusion_list": []}
        )
        assert leaks == []

    def test_missing_customer_notes_returns_empty(self):
        plan_dict = {
            "exclusion_list": [{
                "item": "CVE-2024-1234 fix (PLAT-1, PR #1)",
                "reason": "CVE",
                "exclude_from": ["customer_release_notes"],
            }]
        }
        leaks = _verify_exclusions({"customer_release_notes": ""}, plan_dict)
        assert leaks == []

    def test_sql_injection_phrase_not_auto_detected(self):
        """Phrase-based detection is NOT implemented — only CVE IDs and ticket keys."""
        plan_dict = {
            "exclusion_list": [{
                "item": "Fixed SQL injection vulnerability in dashboard",
                "reason": "security item",
                "exclude_from": ["customer_release_notes"],
            }]
        }
        generated_docs = {
            "customer_release_notes": "We fixed a SQL injection issue in the dashboard.",
            "changelog": "", "internal_release_notes": "", "documentation_updates": [],
        }
        # No CVE IDs or ticket keys in the item — no tokens to check
        leaks = _verify_exclusions(generated_docs, plan_dict)
        assert leaks == []  # phrase matching not implemented; tokens only


# ── audience_outlines cap ─────────────────────────────────────────────────────

class TestAudienceOutlines:
    def test_customer_bullets_capped_at_8(self):
        result = _validate_plan({
            "audience_outlines": {
                "customer": [f"bullet {i}" for i in range(15)],
                "internal": [],
            }
        })
        assert len(result["audience_outlines"]["customer"]) == 8

    def test_internal_bullets_capped_at_8(self):
        result = _validate_plan({
            "audience_outlines": {
                "customer": [],
                "internal": [f"bullet {i}" for i in range(20)],
            }
        })
        assert len(result["audience_outlines"]["internal"]) == 8

    def test_fewer_than_8_preserved(self):
        result = _validate_plan({
            "audience_outlines": {
                "customer": ["a", "b", "c"],
                "internal": ["x", "y"],
            }
        })
        assert result["audience_outlines"]["customer"] == ["a", "b", "c"]
        assert result["audience_outlines"]["internal"] == ["x", "y"]

    def test_missing_audience_outlines_defaults_to_empty(self):
        result = _validate_plan({})
        assert result["audience_outlines"] == {"customer": [], "internal": []}

    def test_non_dict_audience_outlines_defaults_to_empty(self):
        result = _validate_plan({"audience_outlines": "not a dict"})
        assert result["audience_outlines"] == {"customer": [], "internal": []}

    def test_bullets_coerced_to_strings(self):
        result = _validate_plan({
            "audience_outlines": {"customer": [1, 2, None], "internal": []}
        })
        assert all(isinstance(b, str) for b in result["audience_outlines"]["customer"])


# ── rag_search_queries cap and fallback ───────────────────────────────────────

class TestRagSearchQueries:
    def test_queries_capped_at_5(self):
        result = _validate_plan({
            "rag_search_queries": [f"query {i}" for i in range(10)]
        })
        assert len(result["rag_search_queries"]) == 5

    def test_fewer_than_5_preserved(self):
        result = _validate_plan({
            "rag_search_queries": ["Stripe checkout", "JWT auth migration"]
        })
        assert result["rag_search_queries"] == ["Stripe checkout", "JWT auth migration"]

    def test_missing_defaults_to_empty_list(self):
        result = _validate_plan({})
        assert result["rag_search_queries"] == []

    def test_non_list_defaults_to_empty(self):
        result = _validate_plan({"rag_search_queries": "not a list"})
        assert result["rag_search_queries"] == []

    def test_empty_strings_filtered_out(self):
        result = _validate_plan({"rag_search_queries": ["Stripe", "", "JWT", ""]})
        assert "" not in result["rag_search_queries"]
        assert "Stripe" in result["rag_search_queries"]

    def test_queries_derived_from_plan_flow(self):
        """Via the mock client, rag_search_queries flows through plan() correctly."""
        client = _MockClient(response={
            "changelog_plan": {"sections": ["changes"], "tone": "technical"},
            "internal_notes_plan": {"audience": "engineering", "sections": ["summary"], "include_risk": True},
            "customer_notes_plan": {"audience": "end-users", "sections": ["summary"], "tone": "friendly"},
            "doc_update_plan": [],
            "core_narrative": None,
            "exclusion_list": [],
            "audience_outlines": {"customer": [], "internal": []},
            "rag_search_queries": ["Stripe checkout migration", "JWT auth guide", "payment schema"],
        })
        digest = {"features": ["Stripe (PLAT-2002, PR #201)"], "bug_fixes": [], "breaking_changes": []}
        result = plan(digest, [], client)
        assert result["rag_search_queries"] == ["Stripe checkout migration", "JWT auth guide", "payment schema"]

    def test_empty_rag_queries_in_minimal_plan(self):
        """Minimal plan (empty digest) returns empty rag_search_queries."""
        result = _minimal_plan()
        assert result["rag_search_queries"] == []


# ── _validate_plan: comprehensive field normalisation ─────────────────────────

class TestValidatePlan:
    def test_all_new_fields_present_with_defaults(self):
        result = _validate_plan({})
        assert "core_narrative" in result
        assert "exclusion_list" in result
        assert "audience_outlines" in result
        assert "rag_search_queries" in result

    def test_exclusion_list_invalid_entries_filtered(self):
        result = _validate_plan({
            "exclusion_list": [
                {"item": "good item", "reason": "reason", "exclude_from": ["customer_release_notes"]},
                "not a dict",
                {"reason": "missing item", "exclude_from": ["customer_release_notes"]},  # no item
                {"item": "has item", "reason": "", "exclude_from": []},  # empty exclude_from
            ]
        })
        assert len(result["exclusion_list"]) == 1
        assert result["exclusion_list"][0]["item"] == "good item"

    def test_exclusion_list_invalid_doc_type_filtered(self):
        result = _validate_plan({
            "exclusion_list": [{
                "item": "something",
                "reason": "test",
                "exclude_from": ["customer_release_notes", "invalid_doc_type"],
            }]
        })
        assert "invalid_doc_type" not in result["exclusion_list"][0]["exclude_from"]
        assert "customer_release_notes" in result["exclusion_list"][0]["exclude_from"]


# ── extract_security_tokens ───────────────────────────────────────────────────

class TestExtractSecurityTokens:
    def test_extracts_cve_ids(self):
        tokens = extract_security_tokens("Patched CVE-2024-1234 and CVE-2023-9999")
        assert "CVE-2024-1234" in tokens
        assert "CVE-2023-9999" in tokens

    def test_extracts_ticket_keys(self):
        tokens = extract_security_tokens("Fixed PLAT-2002 and SEC-42 (PR #10)")
        assert "PLAT-2002" in tokens
        assert "SEC-42" in tokens

    def test_returns_empty_for_plain_text(self):
        tokens = extract_security_tokens("We fixed a security issue in the dashboard.")
        assert tokens == []

    def test_extracts_both_cve_and_ticket(self):
        tokens = extract_security_tokens("Fixed CVE-2024-5678 via PLAT-99 (PR #77)")
        assert "CVE-2024-5678" in tokens
        assert "PLAT-99" in tokens


# ── SYSTEM_PROMPT structure ───────────────────────────────────────────────────

class TestPlannerSystemPrompt:
    def test_core_narrative_mentioned(self):
        assert "core_narrative" in SYSTEM_PROMPT

    def test_exclusion_list_mentioned(self):
        assert "exclusion_list" in SYSTEM_PROMPT

    def test_audience_outlines_mentioned(self):
        assert "audience_outlines" in SYSTEM_PROMPT

    def test_rag_search_queries_mentioned(self):
        assert "rag_search_queries" in SYSTEM_PROMPT

    def test_cap_8_mentioned_for_audience_outlines(self):
        assert "8" in SYSTEM_PROMPT

    def test_cap_5_mentioned_for_rag_queries(self):
        assert "5" in SYSTEM_PROMPT

    def test_null_option_for_core_narrative_explained(self):
        lower = SYSTEM_PROMPT.lower()
        assert "null" in lower

    def test_security_python_enforcement_noted(self):
        assert "Python" in SYSTEM_PROMPT or "python" in SYSTEM_PROMPT.lower()
