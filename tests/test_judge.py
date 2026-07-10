"""Tests for both stages of the LLM-as-judge verification layer."""

import pytest
from uuid import uuid4

from portfolio_architect.judge.structural_check import run as structural_check, _validate_criteria_structure
from portfolio_architect.judge.logical_check import _parse_judge_response


# ─── Structural check ─────────────────────────────────────────────────────────

class TestStructuralValidation:
    def test_valid_criteria_pass(self, valid_criteria):
        passed, errors = _validate_criteria_structure(valid_criteria)
        assert passed is True
        assert errors == []

    def test_empty_criteria_fail(self):
        passed, errors = _validate_criteria_structure([])
        assert passed is False
        assert any("empty" in e for e in errors)

    def test_not_a_list_fail(self):
        passed, errors = _validate_criteria_structure({"criteria": []})
        assert passed is False

    def test_invalid_type_fail(self):
        criteria = [{"type": "maybe", "statement": "x", "rationale": "y", "source_ids": ["a"]}]
        passed, errors = _validate_criteria_structure(criteria)
        assert passed is False
        assert any("type" in e for e in errors)

    def test_empty_statement_fail(self):
        criteria = [{"type": "inclusion", "statement": "", "rationale": "y", "source_ids": ["a"]}]
        passed, errors = _validate_criteria_structure(criteria)
        assert passed is False

    def test_empty_source_ids_fail(self):
        criteria = [{"type": "inclusion", "statement": "x", "rationale": "y", "source_ids": []}]
        passed, errors = _validate_criteria_structure(criteria)
        assert passed is False


@pytest.mark.asyncio
async def test_structural_run_returns_dict(valid_criteria):
    result = await structural_check(
        conn=None,  # structural check doesn't need DB
        project_id=uuid4(),
        run_id=uuid4(),
        criteria=valid_criteria,
    )
    assert "verdict" in result
    assert result["verdict"] in ("pass", "fail")
    assert result["criteria_count"] == len(valid_criteria)


# ─── Logical check parsing ─────────────────────────────────────────────────────

class TestLogicalJudgeParsing:
    def test_valid_json_parsed_correctly(self):
        raw = """{
          "faithfulness": {"score": 4, "rationale": "All claims cited."},
          "problem_statement_integrity": {"score": 5, "rationale": "Preserved."},
          "citation_accuracy": {"score": 4, "rationale": "Accurate."},
          "uncertainty_transparency": {"score": 3, "rationale": "Some gaps."},
          "overall": 4,
          "verdict": "pass",
          "death_spiral_reason": null
        }"""
        result = _parse_judge_response(raw)
        assert result["verdict"] == "pass"
        assert result["faithfulness"]["score"] == 4
        assert result["overall"] == 4

    def test_malformed_json_returns_fail_not_crash(self):
        result = _parse_judge_response("This is not JSON at all.")
        assert result["verdict"] == "fail"
        assert result["overall"] == 1

    def test_markdown_fence_stripped(self):
        raw = '```json\n{"faithfulness": {"score": 3, "rationale": "ok"}, "problem_statement_integrity": {"score": 3, "rationale": "ok"}, "citation_accuracy": {"score": 3, "rationale": "ok"}, "uncertainty_transparency": {"score": 3, "rationale": "ok"}, "overall": 3, "verdict": "pass", "death_spiral_reason": null}\n```'
        result = _parse_judge_response(raw)
        assert result["verdict"] == "pass"

    def test_death_spiral_detected(self):
        raw = """{
          "faithfulness": {"score": 1, "rationale": "Unsupported."},
          "problem_statement_integrity": {"score": 2, "rationale": "Drift."},
          "citation_accuracy": {"score": 1, "rationale": "Wrong cites."},
          "uncertainty_transparency": {"score": 1, "rationale": "Hidden."},
          "overall": 1,
          "verdict": "death_spiral",
          "death_spiral_reason": "Criteria A and B directly contradict."
        }"""
        result = _parse_judge_response(raw)
        assert result["verdict"] == "death_spiral"
        assert result["death_spiral_reason"] is not None

    def test_missing_verdict_inferred_from_scores(self):
        raw = """{
          "faithfulness": {"score": 2, "rationale": "Low."},
          "problem_statement_integrity": {"score": 2, "rationale": "Low."},
          "citation_accuracy": {"score": 2, "rationale": "Low."},
          "uncertainty_transparency": {"score": 2, "rationale": "Low."}
        }"""
        result = _parse_judge_response(raw)
        # All scores < 3 → should infer "fail"
        assert result["verdict"] == "fail"
