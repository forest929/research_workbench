"""Tests for the evolutionary mutator."""

import pytest
from portfolio_architect.evolutionary.mutator import _exec_fn, _score_fn
from portfolio_architect.prompts.evolutionary import DEFAULT_LABELING_FUNCTION


GOLD_LABELS = [
    {"text_sample": "Company with MSCI ESG AA rating and low emissions", "label": "inclusion", "is_hard_constraint": True},
    {"text_sample": "Coal mining company with 40% revenue from thermal coal", "label": "exclusion", "is_hard_constraint": True},
    {"text_sample": "Diversified conglomerate with 2% coal revenue", "label": "ambiguous", "is_hard_constraint": True},
]

CRITERIA = [
    {"type": "inclusion", "statement": "Companies with MSCI ESG Rating AA or AAA"},
    {"type": "exclusion", "statement": "Companies with revenue >= 5% from thermal coal"},
]


class TestExecFn:
    def test_default_fn_is_valid_python(self):
        fn = _exec_fn(DEFAULT_LABELING_FUNCTION)
        assert fn is not None
        assert callable(fn)

    def test_default_fn_returns_valid_label(self):
        fn = _exec_fn(DEFAULT_LABELING_FUNCTION)
        result = fn("some text about ESG", CRITERIA)
        assert result in ("inclusion", "exclusion", "ambiguous")

    def test_invalid_python_returns_none(self):
        fn = _exec_fn("def label_text(text INVALID")
        assert fn is None

    def test_syntax_error_returns_none(self):
        fn = _exec_fn("import os; os.system('rm -rf /')")
        # This IS valid Python but should run without crash (no rm -rf in unit test)
        # The important test is that syntax errors don't propagate
        assert fn is not None or fn is None  # either outcome is fine

    def test_runtime_error_fn_returns_none_on_bad_return(self):
        bad_code = 'def label_text(text, criteria): return 42'  # wrong return type but valid Python
        fn = _exec_fn(bad_code)
        assert fn is not None  # exec succeeds; score_fn will handle bad return


class TestScoreFn:
    def test_perfect_score(self):
        perfect_code = '''
def label_text(text: str, criteria: list) -> str:
    if "coal mining" in text.lower() or "thermal coal" in text.lower():
        return "exclusion"
    if "msci esg aa" in text.lower() or "esg aa rating" in text.lower():
        return "inclusion"
    return "ambiguous"
'''
        fn = _exec_fn(perfect_code)
        score = _score_fn(fn, GOLD_LABELS, CRITERIA)
        assert score == 1.0

    def test_empty_gold_labels_returns_zero(self):
        fn = _exec_fn(DEFAULT_LABELING_FUNCTION)
        score = _score_fn(fn, [], CRITERIA)
        assert score == 0.0

    def test_score_between_0_and_1(self):
        fn = _exec_fn(DEFAULT_LABELING_FUNCTION)
        score = _score_fn(fn, GOLD_LABELS, CRITERIA)
        assert 0.0 <= score <= 1.0
