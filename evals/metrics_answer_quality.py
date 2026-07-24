"""
evals/metrics_answer_quality.py
Phase 10 — deterministic answer-quality metrics.

Scores the TEXT of a grounded answer against the evidence it was built from.
Complements evals/metrics_llm.py (which scores run OUTCOMES —
accepted/rejected/fallback) by measuring answer-content properties the Phase 10
prompt work targets: grounding, citation correctness, hallucination, verbosity,
repetition, abstention, and clarification.

No LLM, no embeddings, no semantic similarity, no LLM-as-judge. Every metric is
a deterministic function of the answer string and the evidence string — the same
token-overlap discipline used by retrieval/utils.tokenize and answer_agent. The
functions are pure and reusable: they score hand-authored before/after fixtures
today and could score real model output when a live LLM is available.
"""
from __future__ import annotations

import re
from typing import Any

from retrieval.utils import tokenize

# Tokens too generic to count as "content" when measuring grounding — matching
# the answer_agent's philosophy that common words inflate overlap scores.
_GENERIC = frozenset({
    "the", "a", "an", "to", "in", "of", "for", "at", "is", "are", "and", "or",
    "you", "your", "this", "that", "it", "with", "on", "as", "be", "by", "from",
    "see", "please", "may", "can", "will", "should", "there", "here", "these",
    "those", "was", "were", "has", "have", "if", "not", "no", "yes", "we", "our",
})

# A URL as it appears in answer or evidence text.
_URL = re.compile(r'https?://[^\s\)\]"\'<>]+')

# Phrases that signal an explicit abstention / "not available" answer.
_ABSTENTION = (
    "not available", "isn't available", "is not available", "don't have",
    "do not have", "not something i can confirm", "not covered", "no information",
    "not in the", "couldn't find", "could not find", "not listed",
    "don't include", "doesn't include", "does not include", "not include",
    "can't confirm", "cannot confirm", "can't provide", "cannot provide",
)

# Concrete specifics a fabricated answer would invent — used to check that an
# abstention answer does NOT also assert made-up facts.
_SPECIFIC = re.compile(r'(\$\s?\d|\bGPA\b|\b\d\.\d\b|\b\d{1,2}:\d{2}\b|'
                       r'\bhttps?://|\b\d{3}[-.]\d{3}[-.]\d{4}\b)', re.IGNORECASE)


def _urls(text: str) -> set[str]:
    return {m.rstrip(".,;:!?") for m in _URL.findall(text or "")}


def _sentences(text: str) -> list[str]:
    """Split into non-empty sentence/line/bullet units (deterministic)."""
    parts = re.split(r'(?<=[.!?])\s+|\n+', (text or "").strip())
    return [re.sub(r'^[\-\*\d\.\)\s]+', "", p).strip() for p in parts if p.strip()]


def grounding_rate(answer: str, evidence: str) -> float:
    """Fraction of the answer's content sentences supported by the evidence.

    A sentence is "supported" when at least half of its content tokens (minus
    generic words and URLs) also appear in the evidence. URLs are validated
    separately (citation_correctness), so they are excluded here. An answer with
    no content sentences scores 1.0 (nothing ungrounded).
    """
    ev_tokens = tokenize(_URL.sub(" ", evidence or "")) - _GENERIC
    sentences = _sentences(answer)
    scored = 0
    supported = 0
    for s in sentences:
        toks = tokenize(_URL.sub(" ", s)) - _GENERIC
        if not toks:
            continue
        scored += 1
        if len(toks & ev_tokens) >= max(1, (len(toks) + 1) // 2):
            supported += 1
    return round(supported / scored, 4) if scored else 1.0


def citation_correctness(answer: str, evidence: str) -> dict[str, Any]:
    """URL-level citation quality: fidelity, attribution, hallucination count."""
    ans_urls = _urls(answer)
    ev_urls = _urls(evidence)
    fabricated = sorted(ans_urls - ev_urls)
    return {
        # every URL the answer cites exists in the evidence
        "fidelity_ok": not fabricated,
        # when the evidence offers a URL, the answer cites at least one real one
        "attribution_ok": (not ev_urls) or bool(ans_urls & ev_urls),
        "hallucinated_urls": fabricated,
        "hallucinated_url_count": len(fabricated),
    }


def verbosity(answer: str) -> dict[str, int]:
    return {
        "chars": len(answer or ""),
        "sentences": len(_sentences(answer)),
    }


def repetition_rate(answer: str) -> float:
    """Fraction of duplicated content sentences (0.0 = no repetition).

    Sentences are normalized (lowercased, whitespace-collapsed) before the
    duplicate count, so restating the same fact in two places is caught.
    """
    norm = [re.sub(r'\s+', " ", s.lower()) for s in _sentences(answer)]
    norm = [s for s in norm if s]
    if len(norm) <= 1:
        return 0.0
    return round((len(norm) - len(set(norm))) / len(norm), 4)


def abstains(answer: str) -> bool:
    """True when the answer explicitly says the information is not available."""
    low = (answer or "").lower()
    return any(p in low for p in _ABSTENTION)


def abstains_cleanly(answer: str) -> bool:
    """Abstains AND does not also assert fabricated specifics (amounts, GPAs,
    phone numbers, URLs) — a graceful 'I don't know', not a hedged guess."""
    return abstains(answer) and not _SPECIFIC.search(answer or "")


def asks_clarification(answer: str) -> bool:
    """True when the answer poses a clarifying question rather than committing."""
    return "?" in (answer or "")


def score_answer(answer: str, evidence: str) -> dict[str, Any]:
    """All per-answer metrics in one dict (pure)."""
    cit = citation_correctness(answer, evidence)
    v = verbosity(answer)
    return {
        "grounding_rate": grounding_rate(answer, evidence),
        "citation_fidelity_ok": cit["fidelity_ok"],
        "citation_attribution_ok": cit["attribution_ok"],
        "hallucinated_url_count": cit["hallucinated_url_count"],
        "chars": v["chars"],
        "sentences": v["sentences"],
        "repetition_rate": repetition_rate(answer),
        "abstains": abstains(answer),
        "abstains_cleanly": abstains_cleanly(answer),
        "asks_clarification": asks_clarification(answer),
    }


def _evidence_text(evidence: Any) -> str:
    """Flatten a case's retrieved_evidence (str or dict) to searchable text."""
    if isinstance(evidence, str):
        return evidence
    import json
    return json.dumps(evidence, ensure_ascii=False)


def evaluate_case(case: dict, variant: str) -> dict[str, Any]:
    """Score one golden case's `variant` answer ("baseline" or "candidate")
    against its evidence, then judge pass/fail against the case's expectations.

    Expectations (all optional) live under case["expect"]:
      min_grounding            float   — grounding_rate must be >= this
      citation_fidelity        bool    — no fabricated URLs
      require_abstention       bool    — must abstain cleanly
      require_clarification    bool    — must ask a clarifying question
      must_contain             [str]   — every substring must appear verbatim
                                         (used for conflict cases: assert both
                                         values + both sources are present,
                                         where literal grounding under-scores
                                         the necessary meta-commentary)
      max_chars                int     — verbosity ceiling
      max_repetition           float   — repetition ceiling
    """
    answer = case[f"{variant}_answer"]
    evidence = _evidence_text(case.get("retrieved_evidence", ""))
    scores = score_answer(answer, evidence)
    exp = case.get("expect", {})

    failures: list[str] = []
    if "min_grounding" in exp and scores["grounding_rate"] < exp["min_grounding"]:
        failures.append(f"grounding {scores['grounding_rate']} < {exp['min_grounding']}")
    if exp.get("citation_fidelity") and not scores["citation_fidelity_ok"]:
        failures.append(f"fabricated URLs: {scores['hallucinated_url_count']}")
    if exp.get("require_abstention") and not scores["abstains_cleanly"]:
        failures.append("expected a clean abstention")
    if exp.get("require_clarification") and not scores["asks_clarification"]:
        failures.append("expected a clarifying question")
    for needle in exp.get("must_contain", []):
        if needle not in answer:
            failures.append(f"missing required text: {needle!r}")
    if "max_chars" in exp and scores["chars"] > exp["max_chars"]:
        failures.append(f"chars {scores['chars']} > {exp['max_chars']}")
    if "max_repetition" in exp and scores["repetition_rate"] > exp["max_repetition"]:
        failures.append(f"repetition {scores['repetition_rate']} > {exp['max_repetition']}")

    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "variant": variant,
        "scores": scores,
        "passed": not failures,
        "failures": failures,
    }


def aggregate(results: list[dict]) -> dict[str, Any]:
    """Summary metrics over a list of evaluate_case results (one variant)."""
    n = len(results) or 1
    def rate(pred):
        return round(sum(1 for r in results if pred(r)) / n, 4)
    return {
        "cases": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "mean_grounding": round(sum(r["scores"]["grounding_rate"] for r in results) / n, 4),
        "citation_fidelity_rate": rate(lambda r: r["scores"]["citation_fidelity_ok"]),
        "hallucinated_url_total": sum(r["scores"]["hallucinated_url_count"] for r in results),
        "mean_chars": round(sum(r["scores"]["chars"] for r in results) / n, 1),
        "mean_repetition": round(sum(r["scores"]["repetition_rate"] for r in results) / n, 4),
    }
