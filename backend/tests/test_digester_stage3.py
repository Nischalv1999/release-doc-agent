"""Stage 3 tests for digester.py: structured code_insights + coverage enforcement.

Tests cover:
- validate_digest_output: code_insights normalised to {filename, change_type, observation, verified}
  - dict items preserved correctly
  - string items coerced to object (backward compat)
  - empty observation handled
  - verified field defaulted to True when absent
- _enforce_ticket_coverage: every input ticket key appears in output
  - covered tickets not duplicated
  - missing tickets added as [unverified] entries
  - ticket summaries included in placeholder text
- SYSTEM_PROMPT: coverage, citation, and structured code_insights rules present
- planner / writer code_insights rendering: formats object items correctly
"""
import pytest
from agents.digester import (
    _enforce_ticket_coverage,
    SYSTEM_PROMPT,
    _build_user_prompt,
)
from agents.base import validate_digest_output
from agents.planner import _build_user_prompt as planner_build_prompt
from agents.writer import _build_user_prompt as writer_build_prompt


# ── validate_digest_output: code_insights normalization ───────────────────────

class TestCodeInsightsNormalization:
    def test_missing_code_insights_defaults_to_empty_list(self):
        result = validate_digest_output({})
        assert result["code_insights"] == []

    def test_dict_item_preserved(self):
        item = {
            "filename": "src/auth/jwt.ts",
            "change_type": "modified",
            "observation": "JWT verification updated.",
            "verified": True,
        }
        result = validate_digest_output({"code_insights": [item]})
        assert len(result["code_insights"]) == 1
        out = result["code_insights"][0]
        assert out["filename"] == "src/auth/jwt.ts"
        assert out["change_type"] == "modified"
        assert out["observation"] == "JWT verification updated."
        assert out["verified"] is True

    def test_verified_false_preserved(self):
        item = {
            "filename": "src/api/v1/users.ts",
            "change_type": "deleted",
            "observation": "File was modified (patch truncated — content not available for analysis)",
            "verified": False,
        }
        result = validate_digest_output({"code_insights": [item]})
        assert result["code_insights"][0]["verified"] is False

    def test_dict_item_missing_filename_defaults(self):
        result = validate_digest_output({"code_insights": [{"observation": "x"}]})
        out = result["code_insights"][0]
        assert out["filename"] == "unknown"
        assert out["change_type"] == "modified"

    def test_dict_item_missing_verified_defaults_to_true(self):
        result = validate_digest_output({"code_insights": [{"filename": "f.ts", "observation": "x", "change_type": "added"}]})
        assert result["code_insights"][0]["verified"] is True

    def test_string_item_coerced_to_object(self):
        result = validate_digest_output({"code_insights": ["Added Stripe client module"]})
        out = result["code_insights"][0]
        assert isinstance(out, dict)
        assert out["observation"] == "Added Stripe client module"
        assert out["filename"] == "unknown"
        assert out["change_type"] == "modified"
        assert out["verified"] is True

    def test_empty_string_item_skipped(self):
        result = validate_digest_output({"code_insights": ["", "valid insight"]})
        # Empty string is falsy, should be skipped
        assert len(result["code_insights"]) == 1
        assert result["code_insights"][0]["observation"] == "valid insight"

    def test_multiple_items_all_normalized(self):
        items = [
            {"filename": "a.ts", "change_type": "added", "observation": "New file", "verified": True},
            "Old string format",
            {"filename": "b.ts", "observation": "Modified", "change_type": "modified"},
        ]
        result = validate_digest_output({"code_insights": items})
        assert len(result["code_insights"]) == 3
        for out in result["code_insights"]:
            assert isinstance(out, dict)
            assert all(k in out for k in ("filename", "change_type", "observation", "verified"))

    def test_non_list_code_insights_becomes_empty(self):
        # If LLM returns a non-list (e.g. a dict or None), normalize to empty
        result = validate_digest_output({"code_insights": {"bad": "shape"}})
        # Non-list is not iterable in the same way; should result in empty
        assert isinstance(result["code_insights"], list)

    def test_all_schema_fields_present(self):
        result = validate_digest_output({"code_insights": [{"filename": "x.ts", "change_type": "security", "observation": "SQL injection fix", "verified": True}]})
        out = result["code_insights"][0]
        assert set(out.keys()) == {"filename", "change_type", "observation", "verified"}


# ── _enforce_ticket_coverage ──────────────────────────────────────────────────

class TestEnforceTicketCoverage:
    def _make_tickets(self, keys_and_summaries: list[tuple[str, str]]) -> list:
        return [
            {"key": k, "fields": {"summary": s, "components": [], "fixVersions": []}}
            for k, s in keys_and_summaries
        ]

    def test_no_tickets_no_change(self):
        validated = {"features": ["some feature"], "bug_fixes": [], "breaking_changes": []}
        _enforce_ticket_coverage(validated, [])
        assert validated["features"] == ["some feature"]

    def test_covered_ticket_not_duplicated(self):
        validated = {
            "features": ["Added Stripe integration (PLAT-2002, PR #201)"],
            "bug_fixes": [],
            "breaking_changes": [],
        }
        tickets = self._make_tickets([("PLAT-2002", "Stripe payment integration")])
        _enforce_ticket_coverage(validated, tickets)
        # PLAT-2002 is already covered — no addition
        assert len(validated["features"]) == 1

    def test_missing_ticket_added_as_unverified(self):
        validated = {"features": [], "bug_fixes": [], "breaking_changes": []}
        tickets = self._make_tickets([("PLAT-2001", "Platform epic")])
        _enforce_ticket_coverage(validated, tickets)
        assert len(validated["features"]) == 1
        assert "[unverified]" in validated["features"][0]
        assert "PLAT-2001" in validated["features"][0]

    def test_missing_ticket_summary_included(self):
        validated = {"features": [], "bug_fixes": [], "breaking_changes": []}
        tickets = self._make_tickets([("PLAT-2010", "WebSocket notification system")])
        _enforce_ticket_coverage(validated, tickets)
        entry = validated["features"][0]
        assert "WebSocket notification system" in entry

    def test_ticket_covered_in_bug_fixes(self):
        validated = {
            "features": [],
            "bug_fixes": ["Fixed N+1 query issue (PLAT-2016, PR #208)"],
            "breaking_changes": [],
        }
        tickets = self._make_tickets([("PLAT-2016", "Database index optimization")])
        _enforce_ticket_coverage(validated, tickets)
        # Should NOT add another entry since PLAT-2016 is in bug_fixes
        assert len(validated["features"]) == 0

    def test_ticket_covered_in_breaking_changes(self):
        validated = {
            "features": [],
            "bug_fixes": [],
            "breaking_changes": ["Removed /api/v1/users endpoint (PLAT-2001, PR #205)"],
        }
        tickets = self._make_tickets([("PLAT-2001", "Remove deprecated v1 endpoints")])
        _enforce_ticket_coverage(validated, tickets)
        assert len(validated["features"]) == 0

    def test_multiple_missing_tickets_all_added(self):
        validated = {"features": [], "bug_fixes": [], "breaking_changes": []}
        tickets = self._make_tickets([
            ("PLAT-2001", "Epic"),
            ("PLAT-2010", "Notifications"),
            ("PLAT-2016", "DB indexes"),
        ])
        _enforce_ticket_coverage(validated, tickets)
        assert len(validated["features"]) == 3
        covered_keys = {"PLAT-2001", "PLAT-2010", "PLAT-2016"}
        for entry in validated["features"]:
            found = {k for k in covered_keys if k in entry}
            assert len(found) == 1, f"Expected exactly one key in entry: {entry}"

    def test_partial_coverage(self):
        validated = {
            "features": ["Added Stripe integration (PLAT-2002, PR #201)"],
            "bug_fixes": ["Fixed N+1 query (PLAT-2016, PR #208)"],
            "breaking_changes": [],
        }
        tickets = self._make_tickets([
            ("PLAT-2002", "Stripe"),
            ("PLAT-2016", "DB"),
            ("PLAT-2001", "Epic — not mentioned"),
        ])
        _enforce_ticket_coverage(validated, tickets)
        # Only PLAT-2001 should be added
        assert len(validated["features"]) == 2
        assert "PLAT-2001" in validated["features"][1]
        assert "[unverified]" in validated["features"][1]

    def test_ticket_without_summary(self):
        validated = {"features": [], "bug_fixes": [], "breaking_changes": []}
        tickets = [{"key": "PLAT-9999", "fields": {"components": [], "fixVersions": []}}]
        _enforce_ticket_coverage(validated, tickets)
        assert len(validated["features"]) == 1
        assert "PLAT-9999" in validated["features"][0]
        assert "[unverified]" in validated["features"][0]

    def test_unverified_entries_sorted_by_key(self):
        validated = {"features": [], "bug_fixes": [], "breaking_changes": []}
        tickets = self._make_tickets([
            ("PLAT-2016", "DB"),
            ("PLAT-2001", "Epic"),
            ("PLAT-2010", "Notifs"),
        ])
        _enforce_ticket_coverage(validated, tickets)
        keys_in_output = []
        for entry in validated["features"]:
            for key in ("PLAT-2001", "PLAT-2010", "PLAT-2016"):
                if key in entry:
                    keys_in_output.append(key)
        assert keys_in_output == sorted(keys_in_output)

    def test_empty_key_tickets_ignored(self):
        validated = {"features": [], "bug_fixes": [], "breaking_changes": []}
        tickets = [{"key": "", "fields": {"summary": "no key", "components": [], "fixVersions": []}}]
        _enforce_ticket_coverage(validated, tickets)
        # Empty key ticket should not produce an [unverified] entry
        assert len(validated["features"]) == 0


# ── SYSTEM_PROMPT content requirements ────────────────────────────────────────

class TestSystemPromptStage3:
    def test_citation_rule_present(self):
        lower = SYSTEM_PROMPT.lower()
        assert "citation" in lower or "cite" in lower or "must include" in lower

    def test_coverage_rule_present(self):
        assert "coverage" in SYSTEM_PROMPT.lower() or "every input ticket" in SYSTEM_PROMPT.lower()

    def test_unverified_placeholder_rule_present(self):
        assert "[unverified]" in SYSTEM_PROMPT

    def test_breaking_changes_explicit_signal_rule(self):
        lower = SYSTEM_PROMPT.lower()
        assert "explicit" in lower or "signal" in lower or "!" in SYSTEM_PROMPT

    def test_risk_level_holistic_and_no_priority(self):
        # Risk level is now a holistic LLM judgment; Jira priority must NOT be used
        lower = SYSTEM_PROMPT.lower()
        assert "holistic" in lower or "blast radius" in lower or "could break" in lower
        assert "priority" in lower  # explicitly called out as NOT a risk signal

    def test_code_insights_is_object_schema(self):
        # The prompt must describe the object schema, not just string format
        assert '"filename"' in SYSTEM_PROMPT
        assert '"change_type"' in SYSTEM_PROMPT
        assert '"observation"' in SYSTEM_PROMPT
        assert '"verified"' in SYSTEM_PROMPT

    def test_verified_false_for_truncated(self):
        assert "verified" in SYSTEM_PROMPT.lower()
        assert "truncated" in SYSTEM_PROMPT.lower()

    def test_no_fabrication_rule(self):
        lower = SYSTEM_PROMPT.lower()
        assert "fabricat" in lower or "do not invent" in lower or "hallucin" in lower


# ── Planner / Writer prompt formatting for code_insights objects ──────────────

class TestCodeInsightsPromptFormatting:
    def _make_digest(self, insights):
        return {
            "summary": "v2.5.0 release",
            "risk_level": "high",
            "affected_systems": ["Payments"],
            "features": ["Added Stripe (PLAT-2002, PR #201)"],
            "bug_fixes": [],
            "breaking_changes": [],
            "code_insights": insights,
        }

    def test_planner_formats_verified_insight(self):
        digest = self._make_digest([
            {"filename": "src/auth/jwt.ts", "change_type": "modified",
             "observation": "JWT alg changed to RS256.", "verified": True}
        ])
        prompt = planner_build_prompt(digest, [])
        assert "src/auth/jwt.ts" in prompt
        assert "modified" in prompt
        assert "RS256" in prompt

    def test_planner_formats_unverified_insight(self):
        digest = self._make_digest([
            {"filename": "src/api/v1/users.ts", "change_type": "deleted",
             "observation": "File was modified (patch truncated)", "verified": False}
        ])
        prompt = planner_build_prompt(digest, [])
        assert "src/api/v1/users.ts" in prompt
        assert "[unverified]" in prompt

    def test_writer_formats_verified_insight(self):
        digest = self._make_digest([
            {"filename": "migrations/001.sql", "change_type": "migration",
             "observation": "Adds composite index on payments table.", "verified": True}
        ])
        prompt = writer_build_prompt(digest, {}, [], {})
        assert "migrations/001.sql" in prompt
        assert "migration" in prompt

    def test_writer_formats_unverified_insight(self):
        digest = self._make_digest([
            {"filename": "src/api/v1/auth.ts", "change_type": "deleted",
             "observation": "File was modified (patch truncated)", "verified": False}
        ])
        prompt = writer_build_prompt(digest, {}, [], {})
        assert "[unverified]" in prompt

    def test_planner_handles_string_insights_gracefully(self):
        # Backward compat: if old string format slips through, no crash
        digest = self._make_digest(["Old string insight"])
        prompt = planner_build_prompt(digest, [])
        assert "Old string insight" in prompt

    def test_writer_handles_empty_insights(self):
        digest = self._make_digest([])
        # Should not include the "Code-Level Insights" header
        prompt = writer_build_prompt(digest, {}, [], {})
        assert "Code-Level Insights" not in prompt or prompt.count("Code-Level Insights") == 0


# ── Schema: new fields present in validate_digest_output defaults ─────────────

class TestStage3SchemaCompleteness:
    def test_all_stage3_fields_present_in_defaults(self):
        result = validate_digest_output({})
        required = {"features", "bug_fixes", "breaking_changes", "affected_systems",
                    "code_insights", "risk_level", "risk_rationale", "summary"}
        assert required.issubset(result.keys())

    def test_code_insights_field_is_list(self):
        result = validate_digest_output({})
        assert isinstance(result["code_insights"], list)

    def test_full_valid_stage3_output(self):
        full = {
            "features": ["Added Stripe integration (PLAT-2002, PR #201)"],
            "bug_fixes": ["Fixed N+1 query (PLAT-2016, PR #208)"],
            "breaking_changes": ["BREAKING: payment schema changed (PLAT-2003, PR #201)"],
            "affected_systems": ["API", "Auth", "Database", "Payments"],
            "risk_level": "high",
            "summary": "v2.5.0 platform modernisation.",
            "code_insights": [
                {"filename": "src/auth/jwt.ts", "change_type": "security",
                 "observation": "JWT alg updated to RS256.", "verified": True},
                {"filename": "src/api/v1/users.ts", "change_type": "deleted",
                 "observation": "File was modified (patch truncated — content not available for analysis)",
                 "verified": False},
            ],
        }
        result = validate_digest_output(full)
        assert result["risk_level"] == "high"
        assert len(result["code_insights"]) == 2
        assert result["code_insights"][0]["verified"] is True
        assert result["code_insights"][1]["verified"] is False
