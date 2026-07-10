"""Tests for criterion extraction and gold value enforcement."""

import pytest
from portfolio_architect.judge.structural_check import _validate_criteria_structure


class TestGoldValueEnforcement:
    """Gold values must survive extraction unchanged (they're injected as hard constraints)."""

    def test_gold_value_format_preserved(self):
        """Gold value criteria must have source_ids=['GOLD_VALUE'] after extraction."""
        gold_criterion = {
            "type": "inclusion",
            "statement": "Companies must have MSCI ESG Rating AA or AAA",
            "rationale": "Hard constraint set by analyst.",
            "source_ids": ["GOLD_VALUE"],
        }
        passed, errors = _validate_criteria_structure([gold_criterion])
        assert passed is True

    def test_mixed_criteria_validation(self, valid_criteria):
        """Mix of gold and normal criteria should all validate."""
        gold_criterion = {
            "type": "exclusion",
            "statement": "No tobacco companies",
            "rationale": "Portfolio mandate excludes sin stocks.",
            "source_ids": ["GOLD_VALUE"],
        }
        criteria = valid_criteria + [gold_criterion]
        passed, errors = _validate_criteria_structure(criteria)
        assert passed is True

    def test_conflict_flag_in_rationale(self):
        """Conflicting criteria must have CONFLICT: prefix in rationale per extraction prompt rules."""
        conflicting_a = {
            "type": "inclusion",
            "statement": "Companies with any ESG rating",
            "rationale": "CONFLICT: Contradicts exclusion of low-rated companies.",
            "source_ids": ["source_1"],
        }
        conflicting_b = {
            "type": "exclusion",
            "statement": "Companies with ESG rating below A",
            "rationale": "CONFLICT: Contradicts broad ESG inclusion above.",
            "source_ids": ["source_2"],
        }
        passed, errors = _validate_criteria_structure([conflicting_a, conflicting_b])
        # Both are structurally valid — CONFLICT detection is the judge's job
        assert passed is True


class TestCriterionTypes:
    def test_only_inclusion_and_exclusion_valid(self):
        invalid = [{"type": "maybe", "statement": "x", "rationale": "y", "source_ids": ["a"]}]
        passed, errors = _validate_criteria_structure(invalid)
        assert passed is False

    def test_inclusion_is_valid(self):
        criteria = [{"type": "inclusion", "statement": "x", "rationale": "y", "source_ids": ["a"]}]
        passed, _ = _validate_criteria_structure(criteria)
        assert passed is True

    def test_exclusion_is_valid(self):
        criteria = [{"type": "exclusion", "statement": "x", "rationale": "y", "source_ids": ["a"]}]
        passed, _ = _validate_criteria_structure(criteria)
        assert passed is True
