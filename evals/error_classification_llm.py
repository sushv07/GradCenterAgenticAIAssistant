"""
evals/error_classification_llm.py
Phase 7D — deterministic error-category classification for LLM eval case
results (recommendation explanation + grounded answer generation).

Mirrors evals/error_classification.py's role and style for the Phase 2D
recommendation-eval runner. Every case is assigned exactly one
error_category and a short, deterministic error_reason, using only the
case's expected/actual outcome and the explicit pass/fail facts the runner
already computed (evidence coverage, forbidden-phrase presence, URL
fabrication, deterministic-field consistency). No LLM, no semantic
similarity, no subjective judgment — every rule is a pure function of data
already on hand.

── Recommendation Explanation taxonomy ────────────────────────────────────

none
    A clean pass — actual_outcome matches expected_outcome and (when an
    explanation was attached) evidence/forbidden-phrase checks both passed.

missing_explanation
    expected_outcome == "explanation_attached" but no explanation was
    attached — the real attach_explanations() call either failed
    validation or wasn't reached for an unexpected reason.

unsupported_claim
    An explanation was attached but contains a forbidden phrase from the
    case's forbidden_phrases list (e.g. admissions-outcome language, a
    mention of another program).

evidence_omission
    An explanation was attached but does not mention one or more of the
    case's expected_evidence_phrases.

deterministic_drift
    The most serious category: a deterministic ProgramMatch field
    (program_id, confidence, score_basis, advisor_email, deadline_fall)
    changed after attach_explanations() ran. This must never happen by
    design (Phase 7B) — any occurrence is a regression in the integration
    point, not the LLM's output quality.

fallback_failure
    A simulated failure case (connection error, timeout, malformed JSON,
    empty answer) did not degrade exactly as expected — e.g. an exception
    propagated, or an explanation was attached anyway.

unexpected_outcome
    Catch-all: actual_outcome doesn't match expected_outcome and none of
    the more specific rules above explain why.

── Grounded Answer taxonomy ────────────────────────────────────────────────

none
    A clean pass.

fabricated_citation
    expected_outcome == "accepted" but the answer was rejected because it
    cited a URL not present in the retrieved content/source_url, OR
    expected_outcome == "rejected_fabricated_citation" but the synthesizer
    accepted the answer anyway (failed to catch a fabrication).

malformed_output
    expected_outcome == "rejected_malformed_output" but the synthesizer
    did not reject it (or vice versa) — invalid JSON, empty answer, or
    invalid confidence value handling did not match expectations.

fallback_failure
    A simulated network/timeout failure did not degrade exactly as
    expected — an exception propagated instead of synthesize_answer()
    returning None.

validation_failure
    Catch-all: actual_outcome doesn't match expected_outcome and none of
    the more specific rules above explain why.
"""
from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Recommendation Explanation classification
# ---------------------------------------------------------------------------

def classify_explanation(case: dict, result: dict) -> tuple[str, str]:
    """
    Return (error_category, error_reason) for one recommendation-explanation
    eval case result. Checked in priority order: deterministic drift is the
    most severe and is checked first regardless of outcome match; content
    issues (forbidden phrase, evidence omission) are checked next since
    they can occur even when actual_outcome == expected_outcome ==
    "explanation_attached"; everything else falls through to a plain
    outcome-mismatch comparison.
    """
    expected = case["expected_outcome"]
    actual   = result.get("actual_outcome")

    if result.get("deterministic_drift_detected"):
        return (
            "deterministic_drift",
            "a deterministic ProgramMatch field changed after attach_explanations() ran",
        )

    if actual == "explanation_attached" and result.get("forbidden_phrase_found"):
        found = result.get("forbidden_phrases_found", [])
        return "unsupported_claim", f"explanation contains forbidden phrase(s): {found}"

    if actual == "explanation_attached" and not result.get("evidence_fully_covered", True):
        missing = result.get("missing_evidence_phrases", [])
        return "evidence_omission", f"explanation missing expected evidence phrase(s): {missing}"

    if actual == expected:
        return "none", f"correctly produced outcome={actual}"

    if expected == "explanation_attached" and actual != "explanation_attached":
        return "missing_explanation", f"expected an explanation; got outcome={actual}"

    if expected in ("no_explanation_graceful_fallback", "no_explanation_validation_failure"):
        return "fallback_failure", f"expected graceful degradation ({expected}); got outcome={actual}"

    return "unexpected_outcome", f"expected={expected!r} actual={actual!r}"


# ---------------------------------------------------------------------------
# Grounded Answer classification
# ---------------------------------------------------------------------------

def classify_answer(case: dict, result: dict) -> tuple[str, str]:
    """
    Return (error_category, error_reason) for one grounded-answer eval case
    result.
    """
    expected = case["expected_outcome"] or ""
    actual   = result.get("actual_outcome") or ""

    if actual == expected:
        return "none", f"correctly produced outcome={actual}"

    # outcome values are e.g. "rejected_fabricated_citation" — substring
    # checks, not exact equality, so a mismatch involving either side is
    # caught regardless of which one carries the "rejected_" prefix.
    if "fabricated_citation" in expected or "fabricated_citation" in actual:
        return (
            "fabricated_citation",
            f"expected={expected!r} actual={actual!r} — citation-fidelity mismatch",
        )

    if "malformed_output" in expected or "malformed_output" in actual:
        return (
            "malformed_output",
            f"expected={expected!r} actual={actual!r} — format/validation mismatch",
        )

    if expected == "rejected_network_failure" and actual != expected:
        return "fallback_failure", f"expected graceful network-failure fallback; got outcome={actual}"

    return "validation_failure", f"expected={expected!r} actual={actual!r}"


# ---------------------------------------------------------------------------
# Summary helpers (mirror error_classification.py's console-facing style)
# ---------------------------------------------------------------------------

def build_error_summary(results: list[dict], category_key: str = "error_category") -> dict:
    """Count occurrences of each error_category across a list of case results."""
    summary: dict[str, int] = {}
    for r in results:
        cat = r.get(category_key, "unknown")
        summary[cat] = summary.get(cat, 0) + 1
    return summary


def format_error_summary_console(summary: dict, title: str) -> str:
    lines = [title]
    for cat, count in sorted(summary.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"  {cat}: {count}")
    return "\n".join(lines)
