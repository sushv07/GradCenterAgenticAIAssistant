"""
recommendation_engine.py
Phase D — Deterministic scoring engine for doctoral program recommendations.

Scoring model (additive weighted):
  degree_type match:           +1.00
  unique career tag:           +0.85 per tag
  shared career tag:           +0.40 per tag
  interest (1 tag):            +0.20
  interest (2 tags):           +0.35
  interest (3+ tags):          +0.50
  background (1 tag):          +0.10
  background (2+ tags):        +0.20
  orientation match:           +0.15
  orientation mismatch:        −0.10
  career gap penalty:          ×0.50  (PhD-Eng: career_goal_tags=null)

Rule-based confidence tiers (NOT purely numeric):
  HIGH:   degree_type match OR unique career tag match
  MEDIUM: shared career match OR 2+ interest matches OR
          (1 interest + orientation match) OR (1 interest + background match)
  LOW:    single interest match OR background match only
  NONE:   insufficient signal (score < 0.10 and no qualifying signal)

Coverage gate: programs without coverage_status in {"complete","partial"} score 0.0.

Phase D override cases (documented exceptions to Phase C clarify decisions):
  education_undifferentiated → multi_recommend when exactly 2 EdD programs
      both score ≥ low AND education_leadership is domain-exclusive to EdD pair.
  health_undifferentiated → multi_recommend when DrPH + DNP both score ≥ medium.
  orientation_only → multi_recommend ONLY when state.orientation == "clinical"
      AND exactly 2 clinical programs exist (DNP + DPT) AND both reach medium.

Non-overridable gaps: term_ambiguity_*, admission_gated, no_field_signal.

Constraints: no LLM, no embeddings, no LangGraph, no masters recommendations,
             no router changes, no taxonomy changes, deterministic scoring only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from contracts.journey_state import JourneyState
from contracts.response_types import ProgramMatch


# ---------------------------------------------------------------------------
# Taxonomy cache
# ---------------------------------------------------------------------------

_TAXONOMY_CACHE: Optional[list[dict]] = None


def _load_taxonomy() -> list[dict]:
    global _TAXONOMY_CACHE
    if _TAXONOMY_CACHE is None:
        path = Path(__file__).parent.parent / "data" / "program_taxonomy.json"
        with path.open() as f:
            data = json.load(f)
        _TAXONOMY_CACHE = data["programs"]
    return _TAXONOMY_CACHE


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_UNIQUE_CAREER_TAGS: frozenset[str] = frozenset({
    "physical_therapist", "nurse_practitioner",
    "public_health_leader", "policy_maker", "applied_researcher",
    "college_administrator", "school_administrator",
})

_COVERED_STATUSES: frozenset[str] = frozenset({"complete", "partial"})

# Degree abbreviation → program_id(s)
_DEGREE_TO_PROGRAM: dict[str, str | tuple[str, ...]] = {
    "DNP":  "dnp-nursing",
    "DPT":  "dpt-physical-therapy",
    "DrPH": "drph-public-health",
    "EdD":  ("edd-educational-leadership-cc", "edd-educational-leadership-p12"),
    "PhD":  "phd-engineering-computational-math",
}

# Non-overridable gap codes — Phase D must return clarify for these
_NON_OVERRIDABLE_GAPS: frozenset[str] = frozenset({
    "term_ambiguity_doctor",
    "term_ambiguity_leadership",
    "term_ambiguity_education",
    "admission_gated",
    "no_field_signal",
})

# Overridable gap codes
_OVERRIDABLE_GAPS: frozenset[str] = frozenset({
    "education_undifferentiated",
    "health_undifferentiated",
    "orientation_only",
})

# Clinical program IDs (for orientation_only override)
_CLINICAL_PROGRAM_IDS: frozenset[str] = frozenset({"dnp-nursing", "dpt-physical-therapy"})


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ProgramScore:
    program_id:            str
    raw_score:             float
    degree_type_match:     bool           = False
    matched_career_unique: list[str]      = field(default_factory=list)
    matched_career_shared: list[str]      = field(default_factory=list)
    matched_interest:      list[str]      = field(default_factory=list)
    matched_background:    list[str]      = field(default_factory=list)
    orientation_match:     Optional[bool] = None   # None = no orientation signal
    career_gap_applied:    bool           = False
    confidence:            str            = "none"
    score_basis:           list[str]      = field(default_factory=list)
    advisor_email:         str            = ""
    deadline_fall:         str            = ""


@dataclass
class _RecommendationResult:
    behavior:             str
    confidence:           str
    program_matches:      list[ProgramMatch]
    recommended_programs: list[str]
    question:             Optional[str] = None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def compute_program_score(state: JourneyState, program: dict) -> ProgramScore:
    """Compute additive weighted score for one program against accumulated state."""
    prog_id = program["program_id"]
    advisor_email = (program.get("advisor") or {}).get("email", "")
    deadline_fall = (program.get("deadlines") or {}).get("fall", "")

    # Coverage gate
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

    score  = 0.0
    basis: list[str] = []
    obj    = ProgramScore(
        program_id=prog_id, raw_score=0.0,
        advisor_email=advisor_email, deadline_fall=deadline_fall,
    )

    # ── Degree type match (+1.00) ──────────────────────────────────────────
    if state_degree:
        target = _DEGREE_TO_PROGRAM.get(state_degree)
        if target:
            matches_degree = (
                prog_id == target if isinstance(target, str)
                else prog_id in target
            )
            if matches_degree:
                score += 1.00
                obj.degree_type_match = True
                basis.append("degree_type")

    # ── Career goal matches ────────────────────────────────────────────────
    career_gap_applicable = False
    if state_careers:
        if prog_careers:
            for tag in state_careers:
                if tag in prog_careers:
                    if tag in _UNIQUE_CAREER_TAGS:
                        score += 0.85
                        obj.matched_career_unique.append(tag)
                        basis.append(f"unique_career:{tag}")
                    else:
                        score += 0.40
                        obj.matched_career_shared.append(tag)
                        basis.append(f"shared_career:{tag}")
        else:
            # Career signals present but program has null career_goal_tags → gap penalty
            career_gap_applicable = True
            obj.career_gap_applied = True

    # ── Interest tag matches ───────────────────────────────────────────────
    matched_interests = sorted(state_interests & prog_interests)
    n_int = len(matched_interests)
    if n_int >= 3:
        score += 0.50
        obj.matched_interest = matched_interests
        basis.append(f"interests_3plus:{','.join(matched_interests[:3])}")
    elif n_int == 2:
        score += 0.35
        obj.matched_interest = matched_interests
        basis.append(f"interests_2:{','.join(matched_interests)}")
    elif n_int == 1:
        score += 0.20
        obj.matched_interest = matched_interests
        basis.append(f"interest_1:{matched_interests[0]}")

    # ── Academic background matches ────────────────────────────────────────
    matched_bg = sorted(state_bg & prog_bg)
    n_bg = len(matched_bg)
    if n_bg >= 2:
        score += 0.20
        obj.matched_background = matched_bg
        basis.append(f"background_2plus:{','.join(matched_bg[:2])}")
    elif n_bg == 1:
        score += 0.10
        obj.matched_background = matched_bg
        basis.append(f"background_1:{matched_bg[0]}")

    # ── Orientation ────────────────────────────────────────────────────────
    if state_orient and prog_orient:
        if state_orient == prog_orient:
            score += 0.15
            obj.orientation_match = True
            basis.append(f"orientation_match:{state_orient}")
        else:
            score -= 0.10
            obj.orientation_match = False
            basis.append(f"orientation_mismatch:{state_orient}!={prog_orient}")

    # ── Career gap penalty (×0.50) ─────────────────────────────────────────
    if career_gap_applicable and score > 0:
        score *= 0.50

    obj.raw_score   = max(0.0, score)
    obj.score_basis = basis
    return obj


def score_all_programs(state: JourneyState, taxonomy: list[dict]) -> list[ProgramScore]:
    """Score all programs and return sorted by raw_score descending."""
    scores = [compute_program_score(state, p) for p in taxonomy]
    return sorted(scores, key=lambda s: s.raw_score, reverse=True)


# ---------------------------------------------------------------------------
# Confidence assignment
# ---------------------------------------------------------------------------

def _assign_confidence(score: ProgramScore) -> str:
    """
    Rule-based confidence tier. Not purely numeric — signal type determines tier.
    Engineering PhD is capped at MEDIUM always (null career_goal_tags).
    """
    if score.raw_score <= 0.0:
        return "none"

    # HIGH: explicit degree match or unique career tag
    if score.degree_type_match or score.matched_career_unique:
        # Engineering PhD never gets HIGH — career alignment unverifiable
        if score.program_id == "phd-engineering-computational-math":
            return "medium"
        return "high"

    # MEDIUM: shared career OR 2+ interests OR (1 interest + orientation) OR (1 interest + bg)
    if score.matched_career_shared:
        return "medium"
    n_int = len(score.matched_interest)
    if n_int >= 2:
        return "medium"
    if n_int == 1 and score.orientation_match is True:
        return "medium"
    if n_int == 1 and score.matched_background:
        return "medium"

    # LOW: single interest match OR background match only
    if n_int == 1 or score.matched_background:
        return "low"

    # NONE: orientation-only signal (not enough to recommend)
    return "none"


def _multi_confidence(
    prog1: ProgramScore,
    prog2: ProgramScore,
    state: JourneyState,
    all_programs: list[ProgramScore],
) -> str:
    """
    Confidence for a multi_recommend pair.
    medium if any matched interest OR career tag is exclusive to this pair
    (i.e. appears in the pair's matches but NOT in any other scored program's matches).
    low otherwise.
    """
    pair_ids = {prog1.program_id, prog2.program_id}
    combined_interests = set(prog1.matched_interest) | set(prog2.matched_interest)
    combined_careers   = (
        set(prog1.matched_career_unique) | set(prog1.matched_career_shared) |
        set(prog2.matched_career_unique) | set(prog2.matched_career_shared)
    )

    other_programs = [p for p in all_programs if p.program_id not in pair_ids]
    all_other_interests: set[str] = set()
    all_other_careers:   set[str] = set()
    for other in other_programs:
        all_other_interests |= set(other.matched_interest)
        all_other_careers   |= (
            set(other.matched_career_unique) | set(other.matched_career_shared)
        )

    if (combined_interests - all_other_interests) or (combined_careers - all_other_careers):
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Behavior selection
# ---------------------------------------------------------------------------

def _to_program_match(score: ProgramScore) -> ProgramMatch:
    m: ProgramMatch = {
        "program_id":    score.program_id,
        "confidence":    score.confidence,
        "advisor_email": score.advisor_email,
        "deadline_fall": score.deadline_fall,
        "score_basis":   score.score_basis,
    }
    return m


def _clarify_result(question: Optional[str] = None) -> _RecommendationResult:
    return _RecommendationResult(
        behavior="clarify",
        confidence="none",
        program_matches=[],
        recommended_programs=[],
        question=question,
    )


def select_recommendation(
    state: JourneyState,
    gaps: list[str],
    taxonomy: list[dict],
) -> _RecommendationResult:
    """
    Core Phase D decision function.

    1. Non-overridable gaps → clarify immediately.
    2. Score all programs.
    3. Apply Phase C override logic for overridable gaps.
    4. Apply behavior spread rules.
    """
    gap_set = set(gaps)

    # ── Guard: non-overridable gaps ────────────────────────────────────────
    if gap_set & _NON_OVERRIDABLE_GAPS:
        return _clarify_result()

    # ── Score all programs ─────────────────────────────────────────────────
    all_scores = score_all_programs(state, taxonomy)

    # Assign confidence to every scored program
    for s in all_scores:
        s.confidence = _assign_confidence(s)

    # ── Phase C override: orientation_only + clinical ──────────────────────
    # Must run BEFORE the general overridable-gap handling because it has
    # stricter conditions than a generic gap override.
    if "orientation_only" in gap_set:
        # Only override when orientation is clinical AND exactly 2 clinical programs
        # (DNP + DPT) reach medium confidence with a special clinical rule.
        if state.get("orientation") == "clinical":
            clinical_scored = [
                s for s in all_scores
                if s.program_id in _CLINICAL_PROGRAM_IDS
            ]
            # For the clinical override, orientation match alone elevates to medium
            # (clinical orientation is domain-exclusive to DNP+DPT)
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
                    behavior="multi_recommend",
                    confidence="medium",
                    program_matches=matches,
                    recommended_programs=[m["program_id"] for m in matches],
                )
        # orientation_only with non-clinical orientation is non-overridable
        return _clarify_result()

    # ── Phase C override: education_undifferentiated ───────────────────────
    if "education_undifferentiated" in gap_set:
        edd_scored = [
            s for s in all_scores
            if s.program_id.startswith("edd-")
        ]
        edd_eligible = [s for s in edd_scored if s.raw_score >= 0.10]
        if len(edd_eligible) == 2:
            # Check if any matched interest is domain-exclusive to the EdD pair
            pair_ids = {s.program_id for s in edd_eligible}
            pair_interests = set()
            for s in edd_eligible:
                pair_interests |= set(s.matched_interest)

            other_scores = [s for s in all_scores if s.program_id not in pair_ids]
            other_interests: set[str] = set()
            for s in other_scores:
                other_interests |= set(s.matched_interest)

            if pair_interests - other_interests:
                # Domain-exclusive interest → override to multi_recommend at medium
                pair = sorted(edd_eligible, key=lambda s: s.raw_score, reverse=True)
                for s in pair:
                    s.confidence = "medium"
                matches = [_to_program_match(s) for s in pair]
                return _RecommendationResult(
                    behavior="multi_recommend",
                    confidence="medium",
                    program_matches=matches,
                    recommended_programs=[m["program_id"] for m in matches],
                )
        # Override conditions not met — fall through to clarify
        return _clarify_result()

    # ── Phase C override: health_undifferentiated ──────────────────────────
    if "health_undifferentiated" in gap_set:
        # DrPH and DNP are the health pair (DPT has null academic_background_tags)
        health_pair_ids = {"drph-public-health", "dnp-nursing"}
        health_scored = [s for s in all_scores if s.program_id in health_pair_ids]
        health_medium  = [s for s in health_scored if s.confidence == "medium"]
        if len(health_medium) == 2:
            pair = sorted(health_medium, key=lambda s: s.raw_score, reverse=True)
            conf = _multi_confidence(pair[0], pair[1], state, all_scores)
            matches = [_to_program_match(s) for s in pair]
            return _RecommendationResult(
                behavior="multi_recommend",
                confidence=conf,
                program_matches=matches,
                recommended_programs=[m["program_id"] for m in matches],
            )
        # Override conditions not met — keep clarify
        return _clarify_result()

    # ── No gaps (or all gaps are overridable and handled above) ───────────
    # Filter eligible programs (score ≥ 0.20 or low-confidence partial match)
    eligible_high_med = [s for s in all_scores if s.raw_score >= 0.20]
    eligible_low      = [s for s in all_scores if 0.10 <= s.raw_score < 0.20]

    # Engineering PhD with null career_goal_tags always produces partial_match_with_caveat
    top_overall = all_scores[0] if all_scores else None
    if top_overall and top_overall.raw_score > 0:
        prog_id = top_overall.program_id

        # ── Single clear program with HIGH confidence ──────────────────────
        if top_overall.confidence == "high" and prog_id != "phd-engineering-computational-math":
            match = _to_program_match(top_overall)
            return _RecommendationResult(
                behavior="recommend",
                confidence="high",
                program_matches=[match],
                recommended_programs=[prog_id],
            )

        # ── Engineering PhD special case ───────────────────────────────────
        if prog_id == "phd-engineering-computational-math" and top_overall.raw_score > 0:
            match = _to_program_match(top_overall)
            return _RecommendationResult(
                behavior="partial_match_with_caveat",
                confidence=top_overall.confidence,
                program_matches=[match],
                recommended_programs=[prog_id],
            )

        # ── Check for multi-recommend: 2 programs at medium within 0.20 ───
        medium_programs = [s for s in all_scores if s.confidence == "medium" and s.raw_score > 0]
        if len(medium_programs) >= 2:
            top2 = medium_programs[:2]
            spread = top2[0].raw_score - top2[1].raw_score
            if spread <= 0.20:
                conf = _multi_confidence(top2[0], top2[1], state, all_scores)
                matches = [_to_program_match(s) for s in top2]
                return _RecommendationResult(
                    behavior="multi_recommend",
                    confidence=conf,
                    program_matches=matches,
                    recommended_programs=[m["program_id"] for m in matches],
                )

        # ── Single MEDIUM program ──────────────────────────────────────────
        if top_overall.confidence == "medium":
            match = _to_program_match(top_overall)
            return _RecommendationResult(
                behavior="recommend",
                confidence="medium",
                program_matches=[match],
                recommended_programs=[prog_id],
            )

        # ── Low confidence: partial_match_with_caveat ──────────────────────
        if top_overall.confidence == "low":
            match = _to_program_match(top_overall)
            return _RecommendationResult(
                behavior="partial_match_with_caveat",
                confidence="low",
                program_matches=[match],
                recommended_programs=[prog_id],
            )

    # No eligible programs at all → clarify
    return _clarify_result()
