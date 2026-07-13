"""LLM-as-judge for workbench conversation answers.

Independent of generation: a distinct judge model/client (`llm.judge`), a
separate prompt, and temperature 0. It scores a synthesized, cited answer
against the sources it was built from, so it can catch unsupported claims and
bad citations — the failure the whole system exists to prevent.

Parsing is defensive: unparseable judge output is a failed grade, not a crash.
Output is a flat dict the UI renders directly.
"""

import json
import re

from portfolio_architect.llm import client as llm

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

_DIMS = ("faithfulness", "citation_accuracy", "relevance", "completeness")

_SYSTEM = """You are an independent evaluator of AI-synthesized clinical-evidence \
answers. You are given a QUESTION, the SOURCES it was built from (atomic claims \
extracted from real papers — each with a source_id, a verdict, and a verbatim \
quote), and the ANSWER. Judge ONLY against the provided sources.

Score each dimension 1-5 (integers) with a one-line rationale:
- faithfulness: is every statement in the answer supported by the sources? \
Unsupported or hallucinated claims must score low.
- citation_accuracy: do the [source_id] citations in the answer actually back \
the statements they are attached to?
- relevance: does the answer address the drug / population / outcome the \
question asks about?
- completeness: does it use the strongest available evidence and acknowledge \
disagreement, rather than cherry-picking or missing obvious relevant sources?

The answer is expected to OPEN with one aggregate statistics sentence (e.g. "Across 92 claims from \
53 studies, 83 support ... 2 contradict ...") drawn from <evidence_totals>, which are the \
authoritative full-cluster counts. Treat that sentence as given context: do NOT penalize it for \
lacking a per-source [source_id] citation, and check it only against <evidence_totals>. Judge \
faithfulness and citation_accuracy on the SPECIFIC findings that follow it. The <sources> below are \
the focused subset the answer quotes in detail (weighted toward contradicting/qualifying evidence by \
design), so do not treat the presence of only a subset as cherry-picking.

Return STRICT JSON only — no prose, no markdown fences:
{"faithfulness":{"score":N,"rationale":"..."},"citation_accuracy":{"score":N,"rationale":"..."},\
"relevance":{"score":N,"rationale":"..."},"completeness":{"score":N,"rationale":"..."},\
"overall":N,"verdict":"pass|weak|fail","summary":"one sentence"}

Set verdict "fail" if any dimension < 3, "weak" if the lowest dimension is 3, \
else "pass"."""

_USER = """<question>
{question}
</question>
<evidence_totals>
{evidence_totals}
</evidence_totals>
<sources>
{sources}
</sources>
<answer>
{answer}
</answer>

Return the strict JSON verdict."""


def _sources_block(members: list[dict]) -> str:
    parts = []
    for m in members:
        quote = (m.get("evidence_quote") or "").strip().replace("\n", " ")[:300]
        parts.append(
            f'[{m.get("source_id")}] verdict={m.get("verdict")} :: '
            f'{(m.get("claim_text") or "").strip()}'
            + (f' (quote: "{quote}")' if quote else "")
        )
    return "\n".join(parts) if parts else "(no sources)"


def _flatten(parsed: dict) -> dict:
    """Normalize the model's JSON into the flat shape the scorecard reads:
    {dim: int, dim_rationale: str, overall: float, verdict: str, summary: str}."""
    out: dict = {}
    for d in _DIMS:
        node = parsed.get(d)
        if isinstance(node, dict):
            score, rationale = node.get("score"), node.get("rationale") or node.get("reason")
        else:
            score = parsed.get(d, parsed.get(f"{d}_score"))
            rationale = parsed.get(f"{d}_rationale")
        try:
            score = max(1, min(5, int(round(float(score)))))
        except (TypeError, ValueError):
            score = 1
        out[d] = score
        out[f"{d}_rationale"] = (rationale or "").strip()

    scores = [out[d] for d in _DIMS]
    try:
        out["overall"] = round(float(parsed.get("overall")), 1)
    except (TypeError, ValueError):
        out["overall"] = round(sum(scores) / len(scores), 1)

    verdict = str(parsed.get("verdict", "")).lower()
    if verdict not in ("pass", "weak", "fail"):
        verdict = "fail" if any(s < 3 for s in scores) else ("weak" if any(s == 3 for s in scores) else "pass")
    out["verdict"] = verdict
    out["summary"] = (parsed.get("summary") or "").strip()
    return out


def _failed_grade(reason: str) -> dict:
    out = {}
    for d in _DIMS:
        out[d] = 1
        out[f"{d}_rationale"] = reason
    out.update({"overall": 1, "verdict": "fail", "summary": reason})
    return out


def _salvage(cleaned: str) -> dict | None:
    """Best-effort recovery when the JSON won't parse — typically a long reasoning
    trace truncated the verdict mid-object, so the early dimensions are present
    but the tail (and closing braces) are cut. Pull whatever per-dimension scores
    survived via regex; return None if nothing usable is found (e.g. truncated
    inside the reasoning, before any JSON), so the caller falls back to a fail."""
    found = {d: m.group(1) for d in _DIMS
             if (m := re.search(rf'"{d}"\s*:\s*{{\s*"score"\s*:\s*(\d)', cleaned))}
    if not found:
        return None
    parsed: dict = {}
    for d in _DIMS:
        if d in found:
            rm = re.search(rf'"{d}"\s*:\s*{{[^}}]*"rationale"\s*:\s*"([^"]*)"', cleaned)
            parsed[d] = {"score": found[d], "rationale": rm.group(1) if rm else ""}
        # missing dimensions are left out -> _flatten scores them 1
    if (vm := re.search(r'"verdict"\s*:\s*"(pass|weak|fail)"', cleaned)):
        parsed["verdict"] = vm.group(1)
    if (sm := re.search(r'"summary"\s*:\s*"([^"]*)"', cleaned)):
        parsed["summary"] = sm.group(1)
    return _flatten(parsed)


def _parse(raw: str) -> dict:
    raw = _THINK_RE.sub("", raw or "").strip()  # drop reasoning-model <think> traces
    if raw.startswith("```"):  # strip markdown fence
        for seg in raw.split("```")[1:]:
            s = seg.lstrip("json").strip()
            if s.startswith("{"):
                raw = s
                break
    if not raw.startswith("{"):  # extract first {...} from any surrounding prose
        i, j = raw.find("{"), raw.rfind("}")
        if i != -1 and j > i:
            raw = raw[i:j + 1]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # Truncated/malformed JSON — recover partial scores before giving up.
        return _salvage(raw) or _failed_grade("Judge output was not valid JSON.")
    if not isinstance(parsed, dict):
        return _failed_grade("Judge output was not a JSON object.")
    return _flatten(parsed)


async def judge_conversation(question, members, answer, evidence_totals=None, conn=None, project_id=None) -> dict:
    """Judge one synthesized answer. Never raises — LLM/parse failures return a
    failed grade so the caller can store and show it rather than 500.

    `evidence_totals` is the full-cluster verdict-count line the answer's opening
    statistics sentence is built from; the judge treats it as authoritative so it
    doesn't flag that sentence as an uncited/unsupported claim."""
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _USER.format(
            question=question or "(no question)",
            evidence_totals=evidence_totals or "(not provided)",
            sources=_sources_block(members),
            answer=answer or "",
        )},
    ]
    try:
        raw = await llm.judge(messages, call_type="judge_conversation", conn=conn, project_id=project_id)
    except Exception as e:
        return _failed_grade(f"Judge call failed: {e}")
    return _parse(raw)
