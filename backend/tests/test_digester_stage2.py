"""Stage 2 tests for digester.py: affected_systems from LLM-visible factual metadata.
Also covers Stage 4: LLM risk assessment with deterministic safety floor.

Tests cover:
- _format_prs: base.repo.full_name is emitted as "Repository: ..." in the PR block
- _format_tickets: Jira components are already emitted as "Components: ..." in the ticket block
- SYSTEM_PROMPT: instructs the LLM to use only components + repo names, never file paths
- _build_user_prompt: repo and component data reach the LLM; no pre-computed systems section
- validate_digest_output: affected_systems still has [] default; unmapped_paths is gone
- _compute_risk_factors: factual metric computation
- _risk_floor: deterministic safety net
- _apply_risk_floor: floor applied to validated output, rationale merged
- Full floor integration: security fix forces high even if LLM says low; LLM can escalate above floor
"""
import json
import pytest
from agents.digester import (
    _build_user_prompt,
    _format_prs,
    _format_tickets,
    _compute_risk_factors,
    _risk_floor,
    _apply_risk_floor,
    SYSTEM_PROMPT,
)
from agents.base import validate_digest_output


# ── _format_prs includes repo name ────────────────────────────────────────────

class TestFormatPrsIncludesRepo:
    def _pr(self, number, repo, title="Test PR"):
        return {
            "number": number,
            "title": title,
            "body": "",
            "state": "closed",
            "merged_at": "2024-03-20T16:00:00Z",
            "merged_by": {"login": "user"},
            "additions": 10,
            "deletions": 2,
            "changed_files": 1,
            "labels": [],
            "requested_reviewers": [],
            "base": {"repo": {"full_name": repo}},
        }

    def test_repo_name_appears_in_output(self):
        out = _format_prs([self._pr(201, "company/payment-service")])
        assert "company/payment-service" in out

    def test_repo_label_is_repository(self):
        out = _format_prs([self._pr(201, "company/payment-service")])
        assert "Repository:" in out

    def test_different_repos_per_pr(self):
        prs = [
            self._pr(201, "company/payment-service", "Stripe"),
            self._pr(205, "company/notification-service", "WS"),
        ]
        out = _format_prs(prs)
        assert "company/payment-service" in out
        assert "company/notification-service" in out

    def test_missing_base_repo_does_not_crash(self):
        pr = {"number": 99, "title": "no repo", "body": "", "state": "closed",
              "merged_at": "", "merged_by": None, "additions": 0, "deletions": 0,
              "changed_files": 0, "labels": [], "requested_reviewers": []}
        out = _format_prs([pr])
        assert "99" in out  # still renders the PR

    def test_platform_repo_included(self):
        out = _format_prs([self._pr(208, "company/platform")])
        assert "company/platform" in out


# ── _format_tickets includes components ───────────────────────────────────────

class TestFormatTicketsIncludesComponents:
    def _ticket(self, key, components):
        return {
            "key": key,
            "fields": {
                "summary": f"Summary for {key}",
                "components": [{"name": c} for c in components],
                "fixVersions": [],
            },
        }

    def test_single_component_in_output(self):
        out = _format_tickets([self._ticket("PLAT-2002", ["Payments"])])
        assert "Payments" in out
        assert "Components:" in out

    def test_multiple_components_in_output(self):
        out = _format_tickets([self._ticket("PLAT-2003", ["Payments", "Database"])])
        assert "Payments" in out
        assert "Database" in out

    def test_no_components_no_crash(self):
        out = _format_tickets([self._ticket("PLAT-9999", [])])
        assert "PLAT-9999" in out

    def test_components_label_present(self):
        out = _format_tickets([self._ticket("PLAT-2020", ["API", "Security"])])
        assert "Components:" in out


# ── SYSTEM_PROMPT contains correct affected_systems instructions ───────────────

class TestSystemPromptAffectedSystems:
    def test_instructs_no_file_path_inference(self):
        lower = SYSTEM_PROMPT.lower()
        assert "file path" in lower or "file paths" in lower
        assert "do not" in lower or "not infer" in lower or "never" in lower

    def test_mentions_jira_components(self):
        lower = SYSTEM_PROMPT.lower()
        assert "component" in lower

    def test_mentions_repo_or_repository(self):
        lower = SYSTEM_PROMPT.lower()
        assert "repository" in lower or "repo" in lower

    def test_no_python_computed_instruction(self):
        # The old "copy from PRE-EXTRACTED" instruction must be gone
        assert "COPY EXACTLY" not in SYSTEM_PROMPT
        assert "pre-computed by Python" not in SYSTEM_PROMPT

    def test_deduplication_instruction_present(self):
        lower = SYSTEM_PROMPT.lower()
        assert "dedup" in lower or "deduplic" in lower

    def test_unmapped_paths_not_mentioned(self):
        assert "unmapped_paths" not in SYSTEM_PROMPT


# ── _build_user_prompt: factual data reaches LLM; no pre-computed block ───────

class TestBuildUserPromptStage2:
    def _pr(self, number, repo):
        return {
            "number": number, "title": f"PR {number}", "body": "", "state": "closed",
            "merged_at": "2024-03-20T16:00:00Z", "merged_by": {"login": "u"},
            "additions": 5, "deletions": 1, "changed_files": 1, "labels": [],
            "requested_reviewers": [], "jira_tickets": [],
            "base": {"repo": {"full_name": repo}},
        }

    def _ticket(self, key, components):
        return {
            "key": key,
            "fields": {
                "summary": f"Ticket {key}",
                "components": [{"name": c} for c in components],
                "fixVersions": [],
            },
        }

    def test_repo_name_reaches_llm(self):
        pr = self._pr(201, "company/payment-service")
        prompt = _build_user_prompt([], [pr], [])
        assert "company/payment-service" in prompt

    def test_component_reaches_llm(self):
        ticket = self._ticket("PLAT-2002", ["Payments"])
        prompt = _build_user_prompt([], [], [ticket])
        assert "Payments" in prompt

    def test_no_precomputed_systems_section(self):
        # Old Stage 2 block must be gone
        prompt = _build_user_prompt([], [], [])
        assert "Python-computed" not in prompt
        assert "Affected systems (Python-computed" not in prompt
        assert "Unmapped paths" not in prompt

    def test_do_not_invent_instruction_present(self):
        prompt = _build_user_prompt([], [], [])
        lower = prompt.lower()
        assert "invent" in lower or "do not" in lower or "only" in lower

    def test_multiple_repos_all_visible(self):
        prs = [self._pr(201, "company/payment-service"),
               self._pr(205, "company/notification-service")]
        prompt = _build_user_prompt([], prs, [])
        assert "company/payment-service" in prompt
        assert "company/notification-service" in prompt

    def test_accepts_three_positional_args(self):
        # First three positional params must be commits, pull_requests, tickets
        import inspect
        from agents.digester import _build_user_prompt as bup
        sig = inspect.signature(bup)
        param_names = list(sig.parameters.keys())
        assert param_names[:3] == ["commits", "pull_requests", "tickets"]


# ── validate_digest_output: unmapped_paths gone; affected_systems still present ─

class TestValidateDigestOutputStage2:
    def test_affected_systems_default_is_empty_list(self):
        result = validate_digest_output({})
        assert "affected_systems" in result
        assert result["affected_systems"] == []

    def test_unmapped_paths_not_in_defaults(self):
        result = validate_digest_output({})
        assert "unmapped_paths" not in result

    def test_affected_systems_preserved_when_present(self):
        result = validate_digest_output({"affected_systems": ["API", "Payments"]})
        assert result["affected_systems"] == ["API", "Payments"]

    def test_all_required_fields_present(self):
        result = validate_digest_output({})
        required = {
            "features", "bug_fixes", "breaking_changes",
            "affected_systems", "code_insights", "risk_level", "risk_rationale", "summary",
        }
        assert required.issubset(result.keys())

    def test_all_existing_fields_still_work(self):
        full = {
            "features": ["feat 1"],
            "bug_fixes": ["fix 1"],
            "breaking_changes": ["break 1"],
            "affected_systems": ["Payments", "API"],
            "risk_level": "high",
            "risk_rationale": ["CVE-2024-1234 detected"],
            "summary": "v2.5.0 release",
        }
        result = validate_digest_output(full)
        assert result["affected_systems"] == ["Payments", "API"]
        assert result["risk_level"] == "high"
        assert result["risk_rationale"] == ["CVE-2024-1234 detected"]

    def test_risk_rationale_default_is_empty_list(self):
        result = validate_digest_output({})
        assert "risk_rationale" in result
        assert result["risk_rationale"] == []

    def test_risk_rationale_non_list_coerced(self):
        result = validate_digest_output({"risk_rationale": "some string"})
        assert isinstance(result["risk_rationale"], list)
        assert result["risk_rationale"] == ["some string"]

    def test_risk_rationale_none_becomes_empty_list(self):
        result = validate_digest_output({"risk_rationale": None})
        assert result["risk_rationale"] == []


# ── _compute_risk_factors ──────────────────────────────────────────────────────

class TestComputeRiskFactors:
    def _commit_with_files(self, filenames, sha="abc12345"):
        return {
            "sha": sha,
            "commit": {"message": "chore: update"},
            "stats": {"additions": 10, "deletions": 2},
            "files": [{"filename": fn, "additions": 5, "deletions": 1, "status": "modified"} for fn in filenames],
        }

    def _pr(self, additions, deletions, changed_files, labels=None, repo="company/platform"):
        return {
            "number": 1, "title": "PR", "body": "", "state": "closed",
            "merged_at": "2024-01-01T00:00:00Z", "merged_by": {"login": "u"},
            "additions": additions, "deletions": deletions, "changed_files": changed_files,
            "labels": labels or [], "requested_reviewers": [], "jira_tickets": [],
            "base": {"repo": {"full_name": repo}},
        }

    def test_cve_present_sets_security_flag(self):
        factors = _compute_risk_factors([], [], [], [], {"CVE-2024-1234": ["commit abc"]})
        assert factors["security_fix_present"] is True
        assert factors["cve_count"] == 1

    def test_no_cve_clears_security_flag(self):
        factors = _compute_risk_factors([], [], [], [], {})
        assert factors["security_fix_present"] is False
        assert factors["cve_count"] == 0

    def test_sql_file_sets_migration_flag(self):
        commit = self._commit_with_files(["migrations/0042_add_col.sql"])
        factors = _compute_risk_factors([commit], [], [], [], {})
        assert factors["has_schema_migration"] is True

    def test_non_sql_clears_migration_flag(self):
        commit = self._commit_with_files(["src/auth/jwt.ts"])
        factors = _compute_risk_factors([commit], [], [], [], {})
        assert factors["has_schema_migration"] is False

    def test_breaking_change_from_llm_output(self):
        factors = _compute_risk_factors([], [], [], ["BREAKING: API schema changed (PLAT-2003, PR #201)"], {})
        assert factors["breaking_change_present"] is True

    def test_breaking_change_from_commit_bang(self):
        commit = {"sha": "abc", "commit": {"message": "feat(auth)!: drop basic auth"}, "stats": {}, "files": []}
        factors = _compute_risk_factors([commit], [], [], [], {})
        assert factors["breaking_change_present"] is True

    def test_breaking_change_from_commit_keyword(self):
        commit = {"sha": "abc", "commit": {"message": "BREAKING: removed old endpoint"}, "stats": {}, "files": []}
        factors = _compute_risk_factors([commit], [], [], [], {})
        assert factors["breaking_change_present"] is True

    def test_breaking_change_from_pr_label(self):
        pr = self._pr(10, 2, 1, labels=[{"name": "breaking-change"}])
        factors = _compute_risk_factors([], [pr], [], [], {})
        assert factors["breaking_change_present"] is True

    def test_no_breaking_signals(self):
        factors = _compute_risk_factors([], [], [], [], {})
        assert factors["breaking_change_present"] is False

    def test_total_lines_summed_from_prs(self):
        prs = [self._pr(100, 20, 3), self._pr(50, 10, 2)]
        factors = _compute_risk_factors([], prs, [], [], {})
        assert factors["total_changed_lines"] == 180
        assert factors["total_files_changed"] == 5

    def test_deletion_heavy(self):
        pr = self._pr(10, 100, 5)
        factors = _compute_risk_factors([], [pr], [], [], {})
        assert factors["deletion_heavy"] is True

    def test_not_deletion_heavy(self):
        pr = self._pr(100, 10, 5)
        factors = _compute_risk_factors([], [pr], [], [], {})
        assert factors["deletion_heavy"] is False

    def test_tests_touched_detected(self):
        commit = self._commit_with_files(["src/auth/jwt.test.ts"])
        factors = _compute_risk_factors([commit], [], [], [], {})
        assert factors["tests_touched"] is True

    def test_tests_not_touched(self):
        commit = self._commit_with_files(["src/auth/jwt.ts"])
        factors = _compute_risk_factors([commit], [], [], [], {})
        assert factors["tests_touched"] is False

    def test_num_systems_counts_unique_repos_and_components(self):
        prs = [
            self._pr(10, 2, 1, repo="company/payment-service"),
            self._pr(10, 2, 1, repo="company/notification-service"),
        ]
        tickets = [{"key": "PLAT-1", "fields": {"components": [{"name": "Database"}], "fixVersions": []}}]
        factors = _compute_risk_factors([], prs, tickets, [], {})
        # 2 repos + 1 component = 3, but component may overlap
        assert factors["num_systems_touched"] >= 2


# ── _risk_floor ────────────────────────────────────────────────────────────────

class TestRiskFloor:
    def test_cve_always_high(self):
        assert _risk_floor({"security_fix_present": True, "breaking_change_present": False, "has_schema_migration": False}) == "high"

    def test_breaking_change_is_medium(self):
        assert _risk_floor({"security_fix_present": False, "breaking_change_present": True, "has_schema_migration": False}) == "medium"

    def test_sql_migration_is_medium(self):
        assert _risk_floor({"security_fix_present": False, "breaking_change_present": False, "has_schema_migration": True}) == "medium"

    def test_both_breaking_and_sql_still_medium_not_high(self):
        assert _risk_floor({"security_fix_present": False, "breaking_change_present": True, "has_schema_migration": True}) == "medium"

    def test_no_signals_is_low(self):
        assert _risk_floor({"security_fix_present": False, "breaking_change_present": False, "has_schema_migration": False}) == "low"

    def test_cve_wins_over_breaking_change(self):
        assert _risk_floor({"security_fix_present": True, "breaking_change_present": True, "has_schema_migration": True}) == "high"


# ── _apply_risk_floor: floor enforcement and rationale injection ───────────────

class TestApplyRiskFloor:
    def _factors(self, **overrides):
        base = {
            "security_fix_present": False,
            "breaking_change_present": False,
            "has_schema_migration": False,
            "cve_count": 0,
        }
        base.update(overrides)
        return base

    def test_floor_high_overrides_llm_low(self):
        validated = {"risk_level": "low", "risk_rationale": ["small change"]}
        factors = self._factors(security_fix_present=True, cve_count=1)
        _apply_risk_floor(validated, "high", factors, {"CVE-2024-1234": ["commit abc"]})
        assert validated["risk_level"] == "high"
        assert any("CVE" in r for r in validated["risk_rationale"])

    def test_floor_high_overrides_llm_medium(self):
        validated = {"risk_level": "medium", "risk_rationale": []}
        factors = self._factors(security_fix_present=True, cve_count=2)
        _apply_risk_floor(validated, "high", factors, {"CVE-2024-1": ["c1"], "CVE-2024-2": ["c2"]})
        assert validated["risk_level"] == "high"

    def test_floor_medium_overrides_llm_low(self):
        validated = {"risk_level": "low", "risk_rationale": []}
        factors = self._factors(breaking_change_present=True)
        _apply_risk_floor(validated, "medium", factors, {})
        assert validated["risk_level"] == "medium"
        assert any("breaking" in r.lower() for r in validated["risk_rationale"])

    def test_floor_medium_overrides_llm_low_via_sql(self):
        validated = {"risk_level": "low", "risk_rationale": []}
        factors = self._factors(has_schema_migration=True)
        _apply_risk_floor(validated, "medium", factors, {})
        assert validated["risk_level"] == "medium"
        assert any("migration" in r.lower() or "sql" in r.lower() for r in validated["risk_rationale"])

    def test_llm_high_preserved_when_floor_is_low(self):
        # LLM escalated above floor for auth/crypto concern — must not be reduced
        validated = {"risk_level": "high", "risk_rationale": ["auth token validation removed"]}
        factors = self._factors()
        _apply_risk_floor(validated, "low", factors, {})
        assert validated["risk_level"] == "high"
        assert validated["risk_rationale"] == ["auth token validation removed"]

    def test_llm_medium_preserved_when_floor_is_low(self):
        validated = {"risk_level": "medium", "risk_rationale": ["wide blast radius"]}
        factors = self._factors()
        _apply_risk_floor(validated, "low", factors, {})
        assert validated["risk_level"] == "medium"

    def test_llm_high_preserved_when_floor_is_medium(self):
        validated = {"risk_level": "high", "risk_rationale": ["payment-critical path modified"]}
        factors = self._factors(breaking_change_present=True)
        _apply_risk_floor(validated, "medium", factors, {})
        assert validated["risk_level"] == "high"

    def test_floor_reason_prepended_not_appended(self):
        validated = {"risk_level": "low", "risk_rationale": ["existing reason"]}
        factors = self._factors(breaking_change_present=True)
        _apply_risk_floor(validated, "medium", factors, {})
        assert validated["risk_rationale"][0].startswith("Safety floor")
        assert "existing reason" in validated["risk_rationale"]

    def test_equal_floor_and_llm_no_change(self):
        validated = {"risk_level": "medium", "risk_rationale": ["some evidence"]}
        factors = self._factors(breaking_change_present=True)
        _apply_risk_floor(validated, "medium", factors, {})
        # No floor reason injected (floor == LLM, not strictly greater)
        assert validated["risk_level"] == "medium"
        assert all("Safety floor" not in r for r in validated["risk_rationale"])


# ── SYSTEM_PROMPT risk instructions ───────────────────────────────────────────

class TestSystemPromptRiskInstructions:
    def test_no_jira_priority_as_risk_signal(self):
        lower = SYSTEM_PROMPT.lower()
        assert "priority" in lower
        assert "not" in lower or "do not" in lower

    def test_holistic_risk_instruction_present(self):
        lower = SYSTEM_PROMPT.lower()
        assert "holistic" in lower or "blast radius" in lower or "could break" in lower

    def test_risk_rationale_in_schema(self):
        assert "risk_rationale" in SYSTEM_PROMPT

    def test_risk_factors_block_referenced(self):
        assert "RISK FACTORS" in SYSTEM_PROMPT

    def test_auth_or_crypto_mentioned_as_risk_signal(self):
        lower = SYSTEM_PROMPT.lower()
        assert "auth" in lower or "crypto" in lower or "token" in lower


# ── RISK FACTORS section in prompt ────────────────────────────────────────────

class TestRiskFactorsSectionInPrompt:
    def _pr(self, additions, deletions, changed_files):
        return {
            "number": 1, "title": "PR", "body": "", "state": "closed",
            "merged_at": "2024-01-01T00:00:00Z", "merged_by": {"login": "u"},
            "additions": additions, "deletions": deletions, "changed_files": changed_files,
            "labels": [], "requested_reviewers": [], "jira_tickets": [],
            "base": {"repo": {"full_name": "company/platform"}},
        }

    def test_risk_factors_header_present(self):
        prompt = _build_user_prompt([], [self._pr(10, 2, 1)], [])
        assert "RISK FACTORS" in prompt

    def test_cve_count_shown(self):
        prompt = _build_user_prompt([], [self._pr(10, 2, 1)], [])
        assert "CVE count:" in prompt

    def test_sql_migration_fact_shown(self):
        prompt = _build_user_prompt([], [self._pr(10, 2, 1)], [])
        assert "SQL schema migration" in prompt or "schema migration" in prompt.lower()

    def test_line_counts_shown(self):
        prompt = _build_user_prompt([], [self._pr(896, 115, 12)], [])
        assert "896" in prompt

    def test_files_changed_shown(self):
        prompt = _build_user_prompt([], [self._pr(896, 115, 12)], [])
        assert "12" in prompt
