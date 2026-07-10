"""pytest fixtures: mock LLM client, in-memory project state."""

import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4


VALID_JUDGE_RESPONSE = """{
  "faithfulness": {"score": 4, "rationale": "All claims traced to sources."},
  "problem_statement_integrity": {"score": 5, "rationale": "Scope faithfully preserved."},
  "citation_accuracy": {"score": 4, "rationale": "Citations match chunk content."},
  "uncertainty_transparency": {"score": 3, "rationale": "Some edge cases flagged."},
  "overall": 4,
  "verdict": "pass",
  "death_spiral_reason": null
}"""

DEATH_SPIRAL_JUDGE_RESPONSE = """{
  "faithfulness": {"score": 2, "rationale": "Unsupported claims found."},
  "problem_statement_integrity": {"score": 2, "rationale": "Scope was narrowed."},
  "citation_accuracy": {"score": 1, "rationale": "Citations do not match claims."},
  "uncertainty_transparency": {"score": 1, "rationale": "Contradictions hidden."},
  "overall": 1,
  "verdict": "death_spiral",
  "death_spiral_reason": "Criteria A and B directly contradict each other with no source resolution."
}"""

MALFORMED_JUDGE_RESPONSE = "This is not JSON at all."


@pytest.fixture
def valid_criteria():
    return [
        {
            "type": "inclusion",
            "statement": "Companies with MSCI ESG Rating AA or AAA",
            "rationale": "Rating threshold ensures minimum ESG quality.",
            "source_ids": ["fixture_esg_criteria"],
        },
        {
            "type": "exclusion",
            "statement": "Companies with revenue >= 5% from thermal coal",
            "rationale": "Thermal coal is inconsistent with ESG mandate.",
            "source_ids": ["fixture_esg_criteria"],
        },
    ]


@pytest.fixture
def empty_criteria():
    return []


@pytest.fixture
def mock_llm_generate():
    with patch("portfolio_architect.llm.client.generate") as m:
        m.return_value = AsyncMock(return_value='{"criteria": []}')
        yield m


@pytest.fixture
def mock_llm_judge_pass():
    with patch("portfolio_architect.llm.client.judge") as m:
        m.return_value = VALID_JUDGE_RESPONSE
        yield m


@pytest.fixture
def mock_llm_judge_death_spiral():
    with patch("portfolio_architect.llm.client.judge") as m:
        m.return_value = DEATH_SPIRAL_JUDGE_RESPONSE
        yield m


@pytest.fixture
def mock_llm_judge_malformed():
    with patch("portfolio_architect.llm.client.judge") as m:
        m.return_value = MALFORMED_JUDGE_RESPONSE
        yield m
