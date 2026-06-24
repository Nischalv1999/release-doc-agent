"""Tests for agent base utilities - retry, validation, error handling."""
import pytest
from unittest.mock import MagicMock, patch
from agents.base import (
    AgentError,
    AgentTimeoutError,
    truncate_text,
    validate_digest_output,
    validate_writer_output,
    validate_review_output,
)


class TestTruncateText:
    def test_short_text_unchanged(self):
        assert truncate_text("hello", 100) == "hello"

    def test_long_text_truncated(self):
        result = truncate_text("a" * 200, 50)
        assert len(result) < 200
        assert "truncated" in result

    def test_exact_limit(self):
        text = "x" * 100
        assert truncate_text(text, 100) == text

    def test_empty_string(self):
        assert truncate_text("", 100) == ""


class TestValidateDigestOutput:
    def test_complete_output_unchanged(self):
        output = {
            "features": ["feat 1"],
            "bug_fixes": ["fix 1"],
            "breaking_changes": [],
            "affected_systems": ["auth"],
            "risk_level": "medium",
            "summary": "A release.",
        }
        result = validate_digest_output(output)
        assert result == output

    def test_missing_fields_get_defaults(self):
        result = validate_digest_output({})
        assert result["features"] == []
        assert result["bug_fixes"] == []
        assert result["breaking_changes"] == []
        assert result["affected_systems"] == []
        assert result["risk_level"] == "medium"  # Invalid → default
        assert result["summary"] == "No summary generated."

    def test_invalid_risk_normalized(self):
        result = validate_digest_output({"risk_level": "extreme"})
        assert result["risk_level"] == "medium"

    def test_string_instead_of_list(self):
        result = validate_digest_output({"features": "single feature"})
        assert result["features"] == ["single feature"]

    def test_valid_risk_levels(self):
        for level in ["low", "medium", "high"]:
            result = validate_digest_output({"risk_level": level})
            assert result["risk_level"] == level


class TestValidateWriterOutput:
    def test_complete_output(self):
        output = {
            "changelog": "# Changes",
            "internal_release_notes": "Notes",
            "customer_release_notes": "Customer notes",
            "documentation_updates": [
                {"doc_path": "x.md", "section": "s", "suggested_content": "c", "action": "update"}
            ],
        }
        result = validate_writer_output(output)
        assert result == output

    def test_missing_fields_get_defaults(self):
        result = validate_writer_output({})
        assert result["changelog"] == ""
        assert result["documentation_updates"] == []

    def test_invalid_doc_updates_filtered(self):
        output = {
            "documentation_updates": [
                {"doc_path": "valid.md", "action": "update"},  # Valid
                {"no_path": True},  # Invalid - no doc_path
                "not a dict",  # Invalid - not a dict
            ]
        }
        result = validate_writer_output(output)
        assert len(result["documentation_updates"]) == 1
        assert result["documentation_updates"][0]["doc_path"] == "valid.md"


class TestValidateReviewOutput:
    def test_complete_output(self):
        output = {
            "overall_score": 8,
            "hallucination_issues": [],
            "missing_coverage": [],
            "tone_issues": [],
            "suggestions": ["good work"],
            "approved": True,
        }
        result = validate_review_output(output)
        assert result["overall_score"] == 8
        assert result["approved"] is True

    def test_score_clamped(self):
        result = validate_review_output({"overall_score": 15})
        assert result["overall_score"] == 10

        result = validate_review_output({"overall_score": -5})
        assert result["overall_score"] == 1

    def test_non_numeric_score(self):
        result = validate_review_output({"overall_score": "high"})
        assert result["overall_score"] == 5

    def test_approved_coerced_to_bool(self):
        result = validate_review_output({"approved": 1})
        assert result["approved"] is True

        result = validate_review_output({"approved": 0})
        assert result["approved"] is False

    def test_missing_fields(self):
        result = validate_review_output({})
        assert result["overall_score"] == 5
        assert result["approved"] is False
        assert result["hallucination_issues"] == []


class TestAgentError:
    def test_error_message(self):
        err = AgentError("Digester", "timeout", attempts=3)
        assert "Digester" in str(err)
        assert "3 attempts" in str(err)

    def test_timeout_is_agent_error(self):
        err = AgentTimeoutError("Writer", "timed out", attempts=2)
        assert isinstance(err, AgentError)
