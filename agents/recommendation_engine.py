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

Phase 3A.4 generalized domain override (replaces the three former Phase D
special-case blocks — education_undifferentiated, health_undifferentiated,
orientation_only — plus the previously-unhandled healthcare_goal_unclear gap):
  For any overridable gap, the candidate program group is derived from
  taxonomy tag membership only (interest tags > background tags >
  orientation, by specificity) — no hardcoded program-id pairs. Within that
  group: 2+ eligible candidates → multi_recommend; exactly 1 → solo
  recommend/partial_match_with_caveat; a genuine zero-signal tie (every
  candidate undifferentiated except for the orientation match that defined
  the group) is promoted together rather than silently picked apart.
  See _resolve_domain_override().

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
from gradcenter_logging import emit


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

# Overridable gap codes — dispatched through the single generalized domain
# override mechanism (_resolve_domain_override), not per-gap special cases.
# healthcare_goal_unclear was previously unhandled here (silently fell
# through to general scoring); Phase 3A.4 gives it the same treatment as
# the other three domain-ambiguity gaps.
_OVERRIDABLE_GAPS: frozenset[str] = frozenset({
    "education_undifferentiated",
    "health_undifferentiated",
    "orientation_only",
    "healthcare_goal_unclear",
})

# Retained for evals/experimental_scoring.py (Phase 2E weight-validation
# clone), which imports this directly. No longer consulted by
# select_recommendation() itself — candidate groups are now derived from
# taxonomy tag membership rather than a hardcoded program-id pair.
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


# ---------------------------------------------------------------------------
# Observability (Phase 2F) — read-only: explains decisions, never influences
# them. Every helper below only inspects ProgramScore/state/taxonomy data
# that select_recommendation() already computed; none of them feed back
# into scoring, confidence, or behavior selection.
# ---------------------------------------------------------------------------

def _emit_score_events(all_scores: list[ProgramScore]) -> None:
    """recommendation.score — one event per program evaluated this call,
    explaining exactly how each program's raw_score was produced."""
    for s in all_scores:
        fields = dict(
            program_id=s.program_id,
            raw_score=round(s.raw_score, 4),
            confidence=s.confidence,
            degree_match=s.degree_type_match,
            matched_career_unique=s.matched_career_unique,
            matched_career_shared=s.matched_career_shared,
            matched_interest=s.matched_interest,
            matched_background=s.matched_background,
            score_basis=s.score_basis,
        )
        if s.orientation_match is not None:
            fields["orientation_match"] = s.orientation_match
        emit("recommendation.score", level="INFO", **fields)


def _classify_rejection(score: ProgramScore, program: dict, state: JourneyState) -> str:
    """Deterministic reason a non-selected program lost out, derived only
    from data select_recommendation() already has on hand. Checked in order
    of most-specific to least-specific cause."""
    if program.get("coverage_status") not in _COVERED_STATUSES:
        return "coverage_gate"
    if score.career_gap_applied:
        return "career_gap"
    state_careers = set(state.get("career_goal_signals", []))
    prog_careers  = set(program.get("career_goal_tags") or [])
    if state_careers and prog_careers and not (score.matched_career_unique or score.matched_career_shared):
        return "career_mismatch"
    if score.orientation_match is False:
        return "orientation_mismatch"
    if score.raw_score <= 0.0:
        return "no_signal_match"
    if score.raw_score < 0.20:
        return "below_threshold"
    return "lower_score"


def _emit_rejection_events(
    all_scores: list[ProgramScore],
    taxonomy: list[dict],
    state: JourneyState,
    selected_ids: set[str],
) -> None:
    """recommendation.rejected — one event per non-selected program this
    call, explaining why it lost (or, for a clarify outcome, why none of
    them were confident enough to recommend)."""
    by_id = {p["program_id"]: p for p in taxonomy}
    top_score = all_scores[0].raw_score if all_scores else 0.0
    for s in all_scores:
        if s.program_id in selected_ids:
            continue
        reason = _classify_rejection(s, by_id.get(s.program_id, {}), state)
        emit(
            "recommendation.rejected", level="INFO",
            program_id=s.program_id, reason=reason,
            raw_score=round(s.raw_score, 4), score_gap=round(top_score - s.raw_score, 4),
        )


def _emit_decision_event(
    behavior: str,
    confidence: str,
    recommended_programs: list[str],
    gaps: list[str],
    all_scores: Optional[list[ProgramScore]] = None,
    override: Optional[str] = None,
) -> None:
    """recommendation.decision — exactly one event per select_recommendation()
    call, summarizing the final outcome and the override path (if any) that
    produced it."""
    fields = dict(
        behavior=behavior,
        confidence=confidence,
        recommended_programs=recommended_programs,
        gaps_considered=list(gaps),
    )
    if override:
        fields["override_used"] = override
    if all_scores:
        fields["top_score"] = round(all_scores[0].raw_score, 4)
        if len(all_scores) > 1:
            fields["second_score"]  = round(all_scores[1].raw_score, 4)
            fields["score_margin"]  = round(all_scores[0].raw_score - all_scores[1].raw_score, 4)
    emit("recommendation.decision", level="INFO", **fields)


# ---------------------------------------------------------------------------
# Phase 3A.4 — Generalized domain override
# ---------------------------------------------------------------------------

def _domain_candidates(
    state: JourneyState,
    all_scores: list[ProgramScore],
    taxonomy: list[dict],
) -> list[ProgramScore]:
    """
    Determine which programs are plausible candidates for the ambiguity the
    current state represents, using taxonomy tag membership only — no
    hardcoded program-id pairs. Priority: interest tags > background tags >
    orientation, mirroring the specificity ordering already used elsewhere
    (extract_signals() step order, _assign_confidence() tiers). Whichever
    signal channel is present and most specific defines the group; this is
    the one algorithm that determines candidates for every domain, instead
    of a separate hardcoded set per gap code.
    """
    state_interests = set(state.get("interests", []))
    state_bg        = set(state.get("academic_background", []))
    state_orient    = state.get("orientation")

    if state_interests:
        matching_ids = {
            p["program_id"] for p in taxonomy
            if set(p.get("interest_tags") or []) & state_interests
        }
    elif state_bg:
        matching_ids = {
            p["program_id"] for p in taxonomy
            if set(p.get("academic_background_tags") or []) & state_bg
        }
    elif state_orient:
        matching_ids = {
            p["program_id"] for p in taxonomy
            if p.get("orientation") == state_orient
        }
    else:
        return []

    return [s for s in all_scores if s.program_id in matching_ids]


def _promote_domain_tie(candidates: list[ProgramScore], orientation: Optional[str]) -> None:
    """
    Mutates candidates in place. When EVERY candidate in the domain group is
    otherwise fully undifferentiated (confidence == "none") and their only
    positive signal is the orientation match that defined the group, this is
    a genuine zero-information tie — promote them together to medium so the
    group can be offered as a multi_recommend instead of silently picking
    one. Never promotes a singleton group: with nothing to break a tie
    against, that would manufacture a confident pick out of bare orientation
    alone. Generalizes the old orientation_only+clinical promotion rule to
    any domain group.
    """
    if len(candidates) < 2:
        return
    tied = [
        s for s in candidates
        if s.confidence == "none" and s.orientation_match is True
        and not s.matched_interest and not s.matched_background
        and not s.matched_career_unique and not s.matched_career_shared
        and not s.degree_type_match
    ]
    if len(tied) == len(candidates):
        tag = f"orientation_match:{orientation}"
        for s in tied:
            s.confidence = "medium"
            if tag not in s.score_basis:
                s.score_basis.append(tag)


def _resolve_domain_override(
    state: JourneyState,
    all_scores: list[ProgramScore],
    taxonomy: list[dict],
) -> Optional[tuple[str, str, list[ProgramScore]]]:
    """
    Single generalized override mechanism for every overridable gap code
    (replaces the three former Phase D special-case blocks). Returns
    (behavior, confidence, programs) when the domain group resolves to a
    confident answer, or None when the caller should clarify instead.
    """
    candidates = _domain_candidates(state, all_scores, taxonomy)
    if not candidates:
        return None

    _promote_domain_tie(candidates, state.get("orientation"))

    eligible = [s for s in candidates if s.confidence != "none"]
    if not eligible:
        return None

    ranked = sorted(eligible, key=lambda s: s.raw_score, reverse=True)
    if len(ranked) >= 2:
        pair = ranked[:2]
        conf = _multi_confidence(pair[0], pair[1], state, all_scores)
        return ("multi_recommend", conf, pair)

    solo = ranked[0]
    behavior = "recommend" if solo.confidence in ("medium", "high") else "partial_match_with_caveat"
    return (behavior, solo.confidence, [solo])


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
        _emit_decision_event("clarify", "none", [], gaps, override="non_overridable_gap")
        return _clarify_result()

    # ── Score all programs ─────────────────────────────────────────────────
    all_scores = score_all_programs(state, taxonomy)

    # Assign confidence to every scored program
    for s in all_scores:
        s.confidence = _assign_confidence(s)

    _emit_score_events(all_scores)

    # ── Generalized domain override (Phase 3A.4) ────────────────────────────
    # Single mechanism for every overridable gap — candidate group, exclusive
    # signal, and recommend/multi_recommend/clarify decision are all derived
    # from taxonomy tag membership (see _resolve_domain_override), not from
    # per-gap hardcoded program-id sets.
    if gap_set & _OVERRIDABLE_GAPS:
        active_gaps = ",".join(sorted(gap_set & _OVERRIDABLE_GAPS))
        resolved = _resolve_domain_override(state, all_scores, taxonomy)
        if resolved:
            behavior, conf, programs = resolved
            matches = [_to_program_match(s) for s in programs]
            recommended = [m["program_id"] for m in matches]
            _emit_rejection_events(all_scores, taxonomy, state, set(recommended))
            _emit_decision_event(behavior, conf, recommended, gaps,
                                  all_scores=all_scores,
                                  override=f"domain_override:{active_gaps}")
            return _RecommendationResult(
                behavior=behavior,
                confidence=conf,
                program_matches=matches,
                recommended_programs=recommended,
            )
        # Domain group did not resolve to a confident answer — clarify rather
        # than fall through to general scoring, which could surface an
        # unrelated program with no connection to the signaled domain.
        _emit_rejection_events(all_scores, taxonomy, state, set())
        _emit_decision_event("clarify", "none", [], gaps, all_scores=all_scores,
                              override=f"domain_override_no_match:{active_gaps}")
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
            _emit_rejection_events(all_scores, taxonomy, state, {prog_id})
            _emit_decision_event("recommend", "high", [prog_id], gaps,
                                  all_scores=all_scores, override="high_single")
            return _RecommendationResult(
                behavior="recommend",
                confidence="high",
                program_matches=[match],
                recommended_programs=[prog_id],
            )

        # ── Engineering PhD special case ───────────────────────────────────
        if prog_id == "phd-engineering-computational-math" and top_overall.raw_score > 0:
            match = _to_program_match(top_overall)
            _emit_rejection_events(all_scores, taxonomy, state, {prog_id})
            _emit_decision_event("partial_match_with_caveat", top_overall.confidence, [prog_id], gaps,
                                  all_scores=all_scores, override="engineering_caveat")
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
                recommended = [m["program_id"] for m in matches]
                _emit_rejection_events(all_scores, taxonomy, state, set(recommended))
                _emit_decision_event("multi_recommend", conf, recommended, gaps,
                                      all_scores=all_scores, override="medium_spread_pair")
                return _RecommendationResult(
                    behavior="multi_recommend",
                    confidence=conf,
                    program_matches=matches,
                    recommended_programs=recommended,
                )

        # ── Single MEDIUM program ──────────────────────────────────────────
        if top_overall.confidence == "medium":
            match = _to_program_match(top_overall)
            _emit_rejection_events(all_scores, taxonomy, state, {prog_id})
            _emit_decision_event("recommend", "medium", [prog_id], gaps,
                                  all_scores=all_scores, override="medium_single")
            return _RecommendationResult(
                behavior="recommend",
                confidence="medium",
                program_matches=[match],
                recommended_programs=[prog_id],
            )

        # ── Low confidence: partial_match_with_caveat ──────────────────────
        if top_overall.confidence == "low":
            match = _to_program_match(top_overall)
            _emit_rejection_events(all_scores, taxonomy, state, {prog_id})
            _emit_decision_event("partial_match_with_caveat", "low", [prog_id], gaps,
                                  all_scores=all_scores, override="low_partial")
            return _RecommendationResult(
                behavior="partial_match_with_caveat",
                confidence="low",
                program_matches=[match],
                recommended_programs=[prog_id],
            )

    # No eligible programs at all → clarify
    _emit_rejection_events(all_scores, taxonomy, state, set())
    _emit_decision_event("clarify", "none", [], gaps, all_scores=all_scores,
                          override="no_eligible_program")
    return _clarify_result()
