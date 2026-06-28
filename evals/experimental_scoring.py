"""
evals/experimental_scoring.py
Phase 2E — weight-parameterized clone of recommendation_engine.py's scoring
and behavior-selection logic, for sensitivity analysis only.

agents/recommendation_engine.py is NEVER modified by this module or its
callers. This module duplicates ONLY the parts of Phase D that are
weight-sensitive:

  - compute_program_score()'s additive terms        -> experimental_score()
  - select_recommendation()'s raw_score thresholds   -> experimental_select_recommendation()
    (0.10 / 0.20 cutoffs, the 0.20 multi-recommend spread check) — these are
    absolute numeric comparisons against the score magnitude, so a weight
    change can shift which program crosses them even though the threshold
    values themselves don't change.

Everything that is weight-INDEPENDENT is imported directly from
agents.recommendation_engine, so this clone can never silently drift from
production for the parts that don't change with weights:

  - _assign_confidence()   — pure boolean/count-based tier rules, no weights
  - _multi_confidence()    — pure set-overlap rule, no weights
  - _load_taxonomy()       — same taxonomy file, read-only
  - _DEGREE_TO_PROGRAM, _UNIQUE_CAREER_TAGS, _COVERED_STATUSES,
    _NON_OVERRIDABLE_GAPS, _OVERRIDABLE_GAPS, _CLINICAL_PROGRAM_IDS
  - ProgramScore, _RecommendationResult (the same dataclasses production uses)

Caveat (documented, not hidden): experimental_select_recommendation()'s
*branching structure* (which gap codes get which override, in what order)
is a literal copy of recommendation_engine.select_recommendation() as of
Phase 2E. If a future change to recommendation_engine.py alters that
branching (not just its weight constants), this clone must be manually
re-synced — it will NOT pick up such changes automatically. This is an
accepted cost of keeping production code completely untouched by an
analysis-only tool.
"""
from __future__ import annotations

from typing import Optional

from contracts.journey_state import JourneyState
from contracts.response_types import ProgramMatch

from agents.recommendation_engine import (
    ProgramScore,
    _RecommendationResult,
    _assign_confidence,
    _multi_confidence,
    _load_taxonomy,
    _DEGREE_TO_PROGRAM,
    _UNIQUE_CAREER_TAGS,
    _COVERED_STATUSES,
    _NON_OVERRIDABLE_GAPS,
    _CLINICAL_PROGRAM_IDS,
)

__all__ = [
    "DEFAULT_WEIGHTS",
    "experimental_score",
    "experimental_score_all",
    "experimental_select_recommendation",
    "load_taxonomy",
]

# Mirrors the literal weight constants in recommendation_engine.py's
# compute_program_score() docstring/body exactly. This IS the production
# configuration, expressed as data instead of inline literals — the
# "baseline" every experiment is diffed against. Any experiment is just
# DEFAULT_WEIGHTS.copy() with one or two keys overridden.
DEFAULT_WEIGHTS: dict[str, float] = {
    "degree":               1.00,
    "career_unique":        0.85,
    "career_shared":        0.40,
    "interest_1":           0.20,
    "interest_2":           0.35,
    "interest_3plus":       0.50,
    "background_1":         0.10,
    "background_2plus":     0.20,
    "orientation_match":    0.15,
    "orientation_mismatch": -0.10,
    "career_gap_multiplier": 0.50,
}

# Re-export so callers don't need to import agents.recommendation_engine
# directly just to load the taxonomy.
load_taxonomy = _load_taxonomy


def experimental_score(state: JourneyState, program: dict, weights: dict[str, float]) -> ProgramScore:
    """Weight-parameterized clone of recommendation_engine.compute_program_score().

    Identical algorithm; every literal weight constant is replaced by a
    lookup into `weights`. With weights == DEFAULT_WEIGHTS this produces
    byte-identical ProgramScore objects to production (verified by the
    fidelity check in weight_validation.py).
    """
    prog_id = program["program_id"]
    advisor_email = (program.get("advisor") or {}).get("email", "")
    deadline_fall = (program.get("deadlines") or {}).get("fall", "")

    if program.get("coverage_status") not in _COVERED_STATUSES:
        return ProgramScore(
            program_id=prog_id, raw_score=0.0,
            advisor_email=advisor_email, deadline_fall=deadline_fall,
        )

    prog_interests = set(program.get("interest_tags") or [])
    prog_careers   = set(program.get("career_goal_tags") or [])
    prog_bg        = set(program.get("academic_background_tags") or [])
    prog_orient    = program.get("orientation")

    state_interests = set(state.get("interests", []))
    state_careers   = set(state.get("career_goal_signals", []))
    state_bg        = set(state.get("academic_background", []))
    state_orient    = state.get("orientation")
    state_degree    = state.get("degree_type")

    score = 0.0
    basis: list[str] = []
    obj = ProgramScore(
        program_id=prog_id, raw_score=0.0,
        advisor_email=advisor_email, deadline_fall=deadline_fall,
    )

    # ── Degree type match ───────────────────────────────────────────────────
    if state_degree:
        target = _DEGREE_TO_PROGRAM.get(state_degree)
        if target:
            matches_degree = (
                prog_id == target if isinstance(target, str)
                else prog_id in target
            )
            if matches_degree:
                score += weights["degree"]
                obj.degree_type_match = True
                basis.append("degree_type")

    # ── Career goal matches ──────────────────────────────────────────────────
    career_gap_applicable = False
    if state_careers:
        if prog_careers:
            for tag in state_careers:
                if tag in prog_careers:
                    if tag in _UNIQUE_CAREER_TAGS:
                        score += weights["career_unique"]
                        obj.matched_career_unique.append(tag)
                        basis.append(f"unique_career:{tag}")
                    else:
                        score += weights["career_shared"]
                        obj.matched_career_shared.append(tag)
                        basis.append(f"shared_career:{tag}")
        else:
            career_gap_applicable = True
            obj.career_gap_applied = True

    # ── Interest tag matches ─────────────────────────────────────────────────
    matched_interests = sorted(state_interests & prog_interests)
    n_int = len(matched_interests)
    if n_int >= 3:
        score += weights["interest_3plus"]
        obj.matched_interest = matched_interests
        basis.append(f"interests_3plus:{','.join(matched_interests[:3])}")
    elif n_int == 2:
        score += weights["interest_2"]
        obj.matched_interest = matched_interests
        basis.append(f"interests_2:{','.join(matched_interests)}")
    elif n_int == 1:
        score += weights["interest_1"]
        obj.matched_interest = matched_interests
        basis.append(f"interest_1:{matched_interests[0]}")

    # ── Academic background matches ──────────────────────────────────────────
    matched_bg = sorted(state_bg & prog_bg)
    n_bg = len(matched_bg)
    if n_bg >= 2:
        score += weights["background_2plus"]
        obj.matched_background = matched_bg
        basis.append(f"background_2plus:{','.join(matched_bg[:2])}")
    elif n_bg == 1:
        score += weights["background_1"]
        obj.matched_background = matched_bg
        basis.append(f"background_1:{matched_bg[0]}")

    # ── Orientation ───────────────────────────────────────────────────────────
    if state_orient and prog_orient:
        if state_orient == prog_orient:
            score += weights["orientation_match"]
            obj.orientation_match = True
            basis.append(f"orientation_match:{state_orient}")
        else:
            score += weights["orientation_mismatch"]
            obj.orientation_match = False
            basis.append(f"orientation_mismatch:{state_orient}!={prog_orient}")

    # ── Career gap penalty ───────────────────────────────────────────────────
    if career_gap_applicable and score > 0:
        score *= weights["career_gap_multiplier"]

    obj.raw_score = max(0.0, score)
    obj.score_basis = basis
    return obj


def experimental_score_all(
    state: JourneyState, taxonomy: list[dict], weights: dict[str, float],
) -> list[ProgramScore]:
    """Score all programs under `weights` and sort by raw_score descending."""
    scores = [experimental_score(state, p, weights) for p in taxonomy]
    return sorted(scores, key=lambda s: s.raw_score, reverse=True)


def _to_program_match(score: ProgramScore) -> ProgramMatch:
    return {
        "program_id":    score.program_id,
        "confidence":    score.confidence,
        "advisor_email": score.advisor_email,
        "deadline_fall": score.deadline_fall,
        "score_basis":   score.score_basis,
    }


def _clarify_result(question: Optional[str] = None) -> _RecommendationResult:
    return _RecommendationResult(
        behavior="clarify", confidence="none",
        program_matches=[], recommended_programs=[], question=question,
    )


def experimental_select_recommendation(
    state: JourneyState,
    gaps: list[str],
    taxonomy: list[dict],
    weights: dict[str, float],
) -> _RecommendationResult:
    """Weight-parameterized clone of recommendation_engine.select_recommendation().

    Branching structure is a literal copy of production as of Phase 2E (see
    module docstring caveat). Only the ProgramScore values feeding the
    raw_score/confidence comparisons come from experimental_score() instead
    of compute_program_score().
    """
    gap_set = set(gaps)

    if gap_set & _NON_OVERRIDABLE_GAPS:
        return _clarify_result()

    all_scores = experimental_score_all(state, taxonomy, weights)
    for s in all_scores:
        s.confidence = _assign_confidence(s)

    if "orientation_only" in gap_set:
        if state.get("orientation") == "clinical":
            clinical_scored = [s for s in all_scores if s.program_id in _CLINICAL_PROGRAM_IDS]
            for s in clinical_scored:
                if s.confidence == "none" and s.orientation_match is True:
                    s.confidence = "medium"
                    if "orientation_match:clinical" not in s.score_basis:
                        s.score_basis.append("orientation_match:clinical")
            clinical_medium = [s for s in clinical_scored if s.confidence == "medium"]
            if (
                len(clinical_medium) == 2
                and {s.program_id for s in clinical_medium} == _CLINICAL_PROGRAM_IDS
            ):
                pair = sorted(clinical_medium, key=lambda s: s.raw_score, reverse=True)
                matches = [_to_program_match(s) for s in pair]
                return _RecommendationResult(
                    behavior="multi_recommend", confidence="medium",
                    program_matches=matches,
                    recommended_programs=[m["program_id"] for m in matches],
                )
        return _clarify_result()

    if "education_undifferentiated" in gap_set:
        edd_scored = [s for s in all_scores if s.program_id.startswith("edd-")]
        edd_eligible = [s for s in edd_scored if s.raw_score >= 0.10]
        if len(edd_eligible) == 2:
            pair_ids = {s.program_id for s in edd_eligible}
            pair_interests: set[str] = set()
            for s in edd_eligible:
                pair_interests |= set(s.matched_interest)
            other_scores = [s for s in all_scores if s.program_id not in pair_ids]
            other_interests: set[str] = set()
            for s in other_scores:
                other_interests |= set(s.matched_interest)
            if pair_interests - other_interests:
                pair = sorted(edd_eligible, key=lambda s: s.raw_score, reverse=True)
                for s in pair:
                    s.confidence = "medium"
                matches = [_to_program_match(s) for s in pair]
                return _RecommendationResult(
                    behavior="multi_recommend", confidence="medium",
                    program_matches=matches,
                    recommended_programs=[m["program_id"] for m in matches],
                )
        return _clarify_result()

    if "health_undifferentiated" in gap_set:
        health_pair_ids = {"drph-public-health", "dnp-nursing"}
        health_scored = [s for s in all_scores if s.program_id in health_pair_ids]
        health_medium = [s for s in health_scored if s.confidence == "medium"]
        if len(health_medium) == 2:
            pair = sorted(health_medium, key=lambda s: s.raw_score, reverse=True)
            conf = _multi_confidence(pair[0], pair[1], state, all_scores)
            matches = [_to_program_match(s) for s in pair]
            return _RecommendationResult(
                behavior="multi_recommend", confidence=conf,
                program_matches=matches,
                recommended_programs=[m["program_id"] for m in matches],
            )
        return _clarify_result()

    top_overall = all_scores[0] if all_scores else None
    if top_overall and top_overall.raw_score > 0:
        prog_id = top_overall.program_id

        if top_overall.confidence == "high" and prog_id != "phd-engineering-computational-math":
            match = _to_program_match(top_overall)
            return _RecommendationResult(
                behavior="recommend", confidence="high",
                program_matches=[match], recommended_programs=[prog_id],
            )

        if prog_id == "phd-engineering-computational-math" and top_overall.raw_score > 0:
            match = _to_program_match(top_overall)
            return _RecommendationResult(
                behavior="partial_match_with_caveat", confidence=top_overall.confidence,
                program_matches=[match], recommended_programs=[prog_id],
            )

        medium_programs = [s for s in all_scores if s.confidence == "medium" and s.raw_score > 0]
        if len(medium_programs) >= 2:
            top2 = medium_programs[:2]
            spread = top2[0].raw_score - top2[1].raw_score
            if spread <= 0.20:
                conf = _multi_confidence(top2[0], top2[1], state, all_scores)
                matches = [_to_program_match(s) for s in top2]
                return _RecommendationResult(
                    behavior="multi_recommend", confidence=conf,
                    program_matches=matches,
                    recommended_programs=[m["program_id"] for m in matches],
                )

        if top_overall.confidence == "medium":
            match = _to_program_match(top_overall)
            return _RecommendationResult(
                behavior="recommend", confidence="medium",
                program_matches=[match], recommended_programs=[prog_id],
            )

        if top_overall.confidence == "low":
            match = _to_program_match(top_overall)
            return _RecommendationResult(
                behavior="partial_match_with_caveat", confidence="low",
                program_matches=[match], recommended_programs=[prog_id],
            )

    return _clarify_result()
