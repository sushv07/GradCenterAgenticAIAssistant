"""
evals/metrics_llm.py
Phase 7D — deterministic metrics over an LLM evaluation run.

Pure post-processing over the per-case results already produced by
run_llm_evals.py — mirrors evals/metrics_recommendation.py's role for the
Phase 2B recommendation-eval runner. This module only counts and divides
numbers that run_llm_evals.py already computed; it never re-invokes the
LLM, never makes a judgment call, and never uses semantic similarity.

No LLM-as-a-judge. Every metric is a deterministic rate computed from
explicit pass/fail facts (was a forbidden phrase present? was a fabricated
URL detected? did the deterministic fields change?) already established by
the runner's own comparisons.
"""
from __future__ import annotations

_EXPLANATION_OUTCOMES = (
    "explanation_attached",
    "no_explanation_no_evidence",
    "no_explanation_graceful_fallback",
    "no_explanation_validation_failure",
)

_ANSWER_OUTCOMES = (
    "accepted",
    "rejected_fabricated_citation",
    "rejected_network_failure",
    "rejected_malformed_output",
)


def _pct(count: int, total: int) -> float:
    return round(count / total * 100, 1) if total else 0.0


def compute_explanation_metrics(cases: list[dict]) -> dict:
    """Compute Phase 7D metrics for recommendation-explanation eval cases."""
    total = len(cases)
    passed = sum(1 for c in cases if c["status"] == "PASS")
    failed = sum(1 for c in cases if c["status"] == "FAIL")

    # Cases where an explanation was actually expected to be (and was)
    # attached — the denominator for evidence/forbidden-claim rates.
    attached_cases = [c for c in cases if c.get("actual_outcome") == "explanation_attached"]
    n_attached = len(attached_cases)

    evidence_covered = sum(1 for c in attached_cases if c.get("evidence_fully_covered"))
    forbidden_present = sum(1 for c in attached_cases if c.get("forbidden_phrase_found"))

    deterministic_consistent = sum(1 for c in cases if not c.get("deterministic_drift_detected"))

    fallback_cases = [
        c for c in cases
        if c.get("expected_outcome") in (
            "no_explanation_graceful_fallback", "no_explanation_validation_failure",
        )
    ]
    fallback_success = sum(1 for c in fallback_cases if c["status"] == "PASS")

    generation_attempted = [
        c for c in cases if c.get("expected_outcome") != "no_explanation_no_evidence"
    ]
    generated = sum(
        1 for c in generation_attempted if c.get("actual_outcome") == "explanation_attached"
    )

    outcome_distribution = {
        outcome: sum(1 for c in cases if c.get("actual_outcome") == outcome)
        for outcome in _EXPLANATION_OUTCOMES
    }

    return {
        "overall_counts": {"total_cases": total, "pass": passed, "fail": failed},
        "explanation_generation_rate": _pct(generated, len(generation_attempted)),
        "evidence_coverage_rate":      _pct(evidence_covered, n_attached),
        "forbidden_claim_rate":        _pct(forbidden_present, n_attached),
        "deterministic_consistency_rate": _pct(deterministic_consistent, total),
        "fallback_success_rate":       _pct(fallback_success, len(fallback_cases)),
        "outcome_distribution":        outcome_distribution,
    }


def compute_answer_metrics(cases: list[dict]) -> dict:
    """Compute Phase 7D metrics for grounded-answer eval cases."""
    total = len(cases)
    passed = sum(1 for c in cases if c["status"] == "PASS")
    failed = sum(1 for c in cases if c["status"] == "FAIL")

    accepted_cases = [c for c in cases if c.get("expected_outcome") == "accepted"]
    citation_fidelity_ok = sum(1 for c in accepted_cases if c["status"] == "PASS")

    fabrication_cases = [c for c in cases if c.get("expected_outcome") == "rejected_fabricated_citation"]
    fabrication_rejected = sum(1 for c in fabrication_cases if c["status"] == "PASS")

    insufficient_cases = [
        c for c in accepted_cases
        if c.get("simulated_confidence") == "low"
    ]
    insufficient_correct = sum(1 for c in insufficient_cases if c["status"] == "PASS")

    fallback_cases = [
        c for c in cases
        if c.get("expected_outcome") in ("rejected_network_failure", "rejected_malformed_output")
    ]
    fallback_correct = sum(1 for c in fallback_cases if c["status"] == "PASS")

    outcome_distribution = {
        outcome: sum(1 for c in cases if c.get("actual_outcome") == outcome)
        for outcome in _ANSWER_OUTCOMES
    }

    return {
        "overall_counts": {"total_cases": total, "pass": passed, "fail": failed},
        "citation_fidelity_rate":              _pct(citation_fidelity_ok, len(accepted_cases)),
        "unsupported_url_rejection_rate":      _pct(fabrication_rejected, len(fabrication_cases)),
        "insufficient_evidence_correctness_rate": _pct(insufficient_correct, len(insufficient_cases)),
        "deterministic_fallback_correctness_rate": _pct(fallback_correct, len(fallback_cases)),
        "outcome_distribution":                outcome_distribution,
    }


def format_console_summary(explanation_metrics: dict, answer_metrics: dict, execution_time_ms: float) -> str:
    """Render the Phase 7D metrics as a readable console block."""
    width = 50
    lines: list[str] = []
    lines.append("=" * width)
    lines.append("LLM Evaluation Summary")
    lines.append("=" * width)
    lines.append("")

    lines.append("Recommendation Explanation")
    em = explanation_metrics
    oc = em["overall_counts"]
    lines.append(f"  Cases: {oc['total_cases']}  Pass: {oc['pass']}  Fail: {oc['fail']}")
    lines.append(f"  Explanation Generation Rate: {em['explanation_generation_rate']}%")
    lines.append(f"  Evidence Coverage Rate: {em['evidence_coverage_rate']}%")
    lines.append(f"  Forbidden Claim Rate: {em['forbidden_claim_rate']}%")
    lines.append(f"  Deterministic Consistency Rate: {em['deterministic_consistency_rate']}%")
    lines.append(f"  Fallback Success Rate: {em['fallback_success_rate']}%")
    lines.append("")

    lines.append("Grounded Answer Generation")
    am = answer_metrics
    oc2 = am["overall_counts"]
    lines.append(f"  Cases: {oc2['total_cases']}  Pass: {oc2['pass']}  Fail: {oc2['fail']}")
    lines.append(f"  Citation Fidelity Rate: {am['citation_fidelity_rate']}%")
    lines.append(f"  Unsupported URL Rejection Rate: {am['unsupported_url_rejection_rate']}%")
    lines.append(f"  Insufficient Evidence Correctness Rate: {am['insufficient_evidence_correctness_rate']}%")
    lines.append(f"  Deterministic Fallback Correctness Rate: {am['deterministic_fallback_correctness_rate']}%")
    lines.append("")

    lines.append(f"Execution Time: {execution_time_ms} ms")
    lines.append("")
    lines.append("=" * width)
    return "\n".join(lines)
