"""
evals/error_classification.py
Phase 2D — deterministic error-category classification for recommendation
eval case results.

Every case produced by run_recommendation_evals.py is assigned exactly one
error_category and a short, deterministic error_reason, using only the
case's expected/actual fields, known_gap flag, and the `differences` list
already computed by the runner's _compare(). No LLM, no embeddings, no
re-execution of recommendation logic, no heuristic that requires a human to
eyeball anything — every rule below is a pure function of data already on
hand.

── Taxonomy ──────────────────────────────────────────────────────────────

none
    Purpose: mark a clean pass — there is nothing to investigate.
    Detection: differences == [] and known_gap is False (status == PASS).
    Example: DISC-001 — recommend/high/[dpt-physical-therapy], exactly as
    expected.

known_gap
    Purpose: a previously-documented architectural/taxonomy limitation,
    behaving exactly as documented. Not a regression; nothing new to fix.
    Detection: differences == [] and known_gap is True (status == KNOWN_GAP).
    Example: DISC-002 — clarifies forever because health_undifferentiated's
    override only ever considers drph-public-health/dnp-nursing, never
    dpt-physical-therapy. Matches the dataset's own expected_* fields, which
    already encode this limitation.

known_gap_regression
    Purpose: a known_gap case whose behavior has now drifted even from the
    documented limitation. This is its own bucket (not folded into
    scoring/ranking/etc.) because the right next step is different: a human
    needs to check whether the system got *better* (the gap may have been
    fixed by an unrelated change and the dataset should be updated) or
    *worse* (a real new regression layered on top of an old one).
    Detection: known_gap is True and differences != [] (status == FAIL).
    Example: (hypothetical) DISC-027 starts returning drph-public-health
    instead of the documented phd-engineering-computational-math artifact.

unknown_failure
    Purpose: catch-all for failures the deterministic rules below cannot
    explain — most commonly a raw exception during execution, where no
    other layer can even be assessed. Also used as a safety net so every
    case is guaranteed exactly one category even if the diff schema grows.
    Detection: an execution error was captured, OR differences != [] but no
    other rule matched.
    Example: handle_discovery() raises an exception for some turn sequence.

out_of_scope_issue
    Purpose: the out-of-scope/redirect short-circuit in extract_signals()
    fired when it should not have, or failed to fire when it should have.
    Detection: a "behavior" difference where expected_behavior == "redirect"
    or actual behavior == "redirect".
    Example: a query mentioning "undergraduate" redirects when a doctoral
    recommendation was expected (or vice versa).

clarification_issue
    Purpose: Phase C/D's clarify-vs-answer decision fired incorrectly —
    either the system clarified when it had enough signal to answer, or it
    answered when it should have asked first.
    Detection: a "behavior" difference where expected_behavior == "clarify"
    or actual behavior == "clarify" (and out_of_scope_issue did not already
    match — redirect takes precedence since it is the more specific rule).
    Example: "Expected recommend but system clarified."

taxonomy_gap
    Purpose: a "recommended_programs" mismatch traceable to a program with a
    documented taxonomy null-field limitation (currently only
    phd-engineering-computational-math, whose career_goal_tags is null).
    Detection: a "recommended_programs" difference where a program in
    (actual - expected) is in the null-field set.
    Example: DISC-027/045-style cases where Engineering PhD surfaces via an
    orientation-match or degree-mention artifact unrelated to the query's
    real domain.

scoring_issue
    Purpose: Phase D chose the wrong behavior *tier* among the
    non-clarify/non-redirect outcomes (recommend vs multi_recommend vs
    partial_match_with_caveat) — the system correctly decided to answer, but
    picked the wrong shape of answer.
    Detection: a "behavior" difference where neither side is "clarify" or
    "redirect".
    Example: expected "recommend" but actual "multi_recommend".

ranking_issue
    Purpose: Phase D correctly decided to answer with the right behavior
    type, but selected the wrong program(s) from within the right
    neighborhood — overlapping but not identical sets.
    Detection: a "recommended_programs" difference with no "behavior"
    difference, where expected and actual program sets intersect.
    Example: "Expected DPT but recommended DNP" would be ranking_issue only
    if DPT and DNP both scored as live candidates; in practice on this
    dataset, completely different programs almost always means zero
    overlap (see signal_extraction_issue) rather than a near-miss.

signal_extraction_issue
    Purpose: the recommended program(s) share no overlap at all with the
    expected program(s), despite the right behavior type — suggesting the
    wrong taxonomy tags were extracted from the query upstream, not just a
    ranking tie-break problem within the right candidate set.
    Detection: a "recommended_programs" difference with no "behavior"
    difference, where expected and actual program sets are disjoint.
    Example: expected dpt-physical-therapy, actual edd-educational-leadership-cc.

confidence_issue
    Purpose: the right behavior and the right program(s) were chosen, but
    the confidence tier assigned to them was miscalibrated.
    Detection: only a "confidence" difference is present (behavior and
    recommended_programs both match expected).
    Example: "Confidence expected medium but got low."

routing_issue
    Purpose: reserved for the router.py layer (discovery-intent detection,
    Branch 1.5, masters/eligibility/deadline guards) — the layer that
    decides whether a query reaches handle_discovery() at all.
    Detection: structurally unreachable by this runner. The evaluation
    dataset and runner call agents.journey_agent.handle_discovery() directly
    (see evals/run_recommendation_evals.py:_run_case_turns), bypassing
    routing/router.py entirely. Kept in the taxonomy as a placeholder for a
    future full-pipeline eval that drives queries through orchestrator.run()
    instead, where a routing mismatch (e.g. a discovery-shaped query routed
    to "advisor") could actually occur and be detected.
    Example: none possible with the current runner; would require comparing
    response.get("route") against an expected route, which this dataset
    does not (and the recommendation gold set should not) need to encode.
"""
from __future__ import annotations

from typing import Optional

from evals.metrics_recommendation import PROGRAM_LABELS

# Programs with a documented taxonomy null-field limitation (see
# data/program_taxonomy.json + recommendation_engine.py's career-gap penalty
# and HIGH-confidence cap). Extend this set if a future taxonomy edit adds
# another null career_goal_tags / academic_background_tags program.
_TAXONOMY_NULL_FIELD_PROGRAMS: frozenset[str] = frozenset({
    "phd-engineering-computational-math",  # career_goal_tags: null
})

_VERB: dict[Optional[str], str] = {
    "clarify":                   "clarified",
    "redirect":                  "redirected",
    "recommend":                 "recommended",
    "multi_recommend":           "recommended multiple programs",
    "partial_match_with_caveat": "returned a partial match with caveat",
    None:                        "produced no response",
}

# Canonical precedence / display order. Used both to decide which rule wins
# when several could describe a case, and as the stable ordering for the
# Error Summary report section.
CATEGORY_ORDER: tuple[str, ...] = (
    "unknown_failure",
    "known_gap_regression",
    "out_of_scope_issue",
    "clarification_issue",
    "taxonomy_gap",
    "scoring_issue",
    "ranking_issue",
    "signal_extraction_issue",
    "confidence_issue",
    "known_gap",
    "routing_issue",
    "none",
)

CATEGORY_LABELS: dict[str, str] = {
    "unknown_failure":         "Unknown Failure",
    "known_gap_regression":    "Known Gap Regression",
    "out_of_scope_issue":      "Out Of Scope",
    "clarification_issue":     "Clarification",
    "taxonomy_gap":            "Taxonomy Gap",
    "scoring_issue":           "Scoring",
    "ranking_issue":           "Ranking",
    "signal_extraction_issue": "Signal Extraction",
    "confidence_issue":        "Confidence",
    "known_gap":               "Known Gap",
    "routing_issue":           "Routing",
    "none":                    "None",
}


def _label(program_id: str) -> str:
    return PROGRAM_LABELS.get(program_id, program_id)


def _labels(program_ids: list[str]) -> str:
    return ", ".join(_label(p) for p in program_ids) if program_ids else "none"


def _diff_field(differences: list[dict], field: str) -> Optional[dict]:
    return next((d for d in differences if d["field"] == field), None)


def classify(
    known_gap: bool,
    expected: dict,
    actual: Optional[dict],
    differences: list[dict],
    error: Optional[str],
) -> tuple[str, str]:
    """Return (error_category, error_reason) for one case result.

    Deterministic precedence (first match wins), and why:
      1. unknown_failure        — execution exception; nothing else assessable.
      2. known_gap_regression   — known_gap case that drifted from its
                                   documented limitation; needs its own
                                   urgent triage bucket regardless of *which*
                                   field changed.
      3. out_of_scope_issue     — behavior diff touching "redirect"; the
                                   most specific behavior-layer rule.
      4. clarification_issue    — behavior diff touching "clarify".
      5. taxonomy_gap           — programs diff explained by a known
                                   null-field program; named root cause
                                   beats the generic ranking/signal rules.
      6. scoring_issue          — any other behavior diff (recommend vs
                                   multi_recommend vs partial_match_with_caveat).
      7. ranking_issue          — programs diff, behavior matches, sets overlap.
      8. signal_extraction_issue— programs diff, behavior matches, sets disjoint.
      9. confidence_issue       — only confidence differs.
      10. known_gap             — no diffs, known_gap flag set.
      11. none                 — no diffs, known_gap flag unset.
      12. unknown_failure       — fallback safety net (should be unreachable).

    Behavior-level rules (1-6) precede program-level rules (7-8), which
    precede the confidence-level rule (9): this mirrors the system's own
    layering — "whether to act" (Phase C/D behavior selection) is upstream
    of "which program(s)" (Phase D scoring), which is upstream of "how sure"
    (Phase D confidence assignment). A case with multiple simultaneous diffs
    is attributed to its most upstream broken layer.
    """
    if error:
        return "unknown_failure", f"Execution raised an exception: {error[:160]}"

    behavior_diff   = _diff_field(differences, "behavior")
    confidence_diff = _diff_field(differences, "confidence")
    programs_diff   = _diff_field(differences, "recommended_programs")

    if known_gap and differences:
        return (
            "known_gap_regression",
            "Known-gap case but current behavior no longer matches the "
            "documented limitation — verify whether this is a regression "
            "or an unintentional fix.",
        )

    if behavior_diff:
        exp_b, act_b = behavior_diff["expected"], behavior_diff["actual"]

        if exp_b == "redirect" or act_b == "redirect":
            return (
                "out_of_scope_issue",
                f"Expected {exp_b} but system {_VERB.get(act_b, act_b)}.",
            )

        if exp_b == "clarify" or act_b == "clarify":
            return (
                "clarification_issue",
                f"Expected {exp_b} but system {_VERB.get(act_b, act_b)}.",
            )

        return (
            "scoring_issue",
            f"Expected {exp_b} but system {_VERB.get(act_b, act_b)}.",
        )

    if programs_diff:
        exp_p = set(programs_diff["expected"])
        act_p = set(programs_diff["actual"])

        unexpected_null_field = (act_p - exp_p) & _TAXONOMY_NULL_FIELD_PROGRAMS
        if unexpected_null_field:
            return (
                "taxonomy_gap",
                f"Unexpected program {_labels(sorted(unexpected_null_field))} surfaced "
                f"— linked to a documented taxonomy null-field limitation.",
            )

        if exp_p & act_p:
            return (
                "ranking_issue",
                f"Expected {_labels(programs_diff['expected'])} but recommended "
                f"{_labels(programs_diff['actual'])}.",
            )

        return (
            "signal_extraction_issue",
            f"Expected {_labels(programs_diff['expected'])} but got completely "
            f"different program(s) {_labels(programs_diff['actual'])} — "
            f"signals may have been mis-extracted.",
        )

    if confidence_diff:
        return (
            "confidence_issue",
            f"Confidence expected {confidence_diff['expected']} but got "
            f"{confidence_diff['actual']}.",
        )

    if known_gap:
        return (
            "known_gap",
            "Known architectural limitation — current behavior matches the "
            "documented gap (see dataset gap_description).",
        )

    if not differences:
        return "none", "No issues detected — actual output matches expected."

    # Safety net: differences existed but matched no rule above. Should be
    # unreachable given _compare() only ever emits behavior/confidence/
    # recommended_programs/execution diffs, all handled above.
    return "unknown_failure", "Differences detected but unclassified — investigate manually."


def build_error_summary(cases: list[dict]) -> dict:
    """Count occurrences of each error_category across all cases.

    Only categories with count > 0 are included; "none" (clean passes) is
    excluded since it is not an error category.
    """
    counts: dict[str, int] = {}
    for c in cases:
        cat = c.get("error_category", "none")
        if cat == "none":
            continue
        counts[cat] = counts.get(cat, 0) + 1

    ordered = {cat: counts[cat] for cat in CATEGORY_ORDER if counts.get(cat)}
    for cat in sorted(counts):
        if cat not in ordered:
            ordered[cat] = counts[cat]
    return ordered


def format_error_summary_console(error_summary: dict) -> str:
    lines = ["Error Categories", ""]
    if not error_summary:
        lines.append("  (none)")
        return "\n".join(lines)
    for cat, count in error_summary.items():
        label = CATEGORY_LABELS.get(cat, cat)
        dots = "." * max(1, 20 - len(label))
        lines.append(f"  {label} {dots} {count}")
    return "\n".join(lines)
