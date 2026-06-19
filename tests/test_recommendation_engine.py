"""
test_recommendation_engine.py
Phase D — Recommendation Scoring Engine: 10 highest-risk tests.

TDD Step 1: tests are written BEFORE the engine exists.
All 10 tests will FAIL with ImportError / ModuleNotFoundError until
agents/recommendation_engine.py is created and select_recommendation()
is implemented.

Run from the project root:
    pytest tests/test_recommendation_engine.py -v

Test inventory (highest-risk first):
  T01  DISC-001  Physical therapist → DPT high recommend
  T02  DISC-021  Educational leadership → EdD-CC + EdD-P12 multi_recommend (Phase C override)
  T03  DISC-014  Engineering research → PhD-Eng medium partial_match_with_caveat
  T04  DISC-026  Professor → DrPH + DNP multi_recommend (Engineering invisible – known gap)
  T05  DISC-025  Healthcare background only → clarify (programs at low, not medium)
  T06  DISC-048  Computational biology → DrPH partial_match_with_caveat at low
  T07  DISC-016  Explicit DNP → high recommend + correct advisor email + deadline
  T08  DISC-029  Clinical doctoral degree → DNP + DPT multi_recommend medium
  T09  Admission-gated guard must NOT be bypassed by Phase D
  T10  DISC-050  Psychology + healthcare background → DrPH partial_match_with_caveat at low
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

# ── This import will FAIL (ModuleNotFoundError) until recommendation_engine.py
#    is created.  That is the expected TDD failure state for Step 1.
from agents.recommendation_engine import (  # noqa: E402
    _load_taxonomy,
    select_recommendation,
    _RecommendationResult,
)
from agents.journey_agent import init_journey_state


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _state(**kwargs):
    """
    Return a JourneyState initialised with the given field overrides.
    turn_count defaults to 1 so the stopping rule (>= 3) is not a factor.
    """
    s = init_journey_state("test")
    s["turn_count"] = 1
    for key, val in kwargs.items():
        s[key] = val
    return s


def _program_ids(result: _RecommendationResult) -> list[str]:
    """Return just the program_id values from result.program_matches."""
    return [m["program_id"] for m in result.program_matches]


# ---------------------------------------------------------------------------
# T01 — DISC-001
# Physical therapist → DPT, confidence=high, behavior=recommend
# Risk: high-confidence recommendation on the wrong program is the most
#       severe failure mode (eval philosophy P1).
# ---------------------------------------------------------------------------

def test_t01_disc001_physical_therapist_high_recommend():
    """Unique career tag physical_therapist must produce high-confidence DPT recommend."""
    state = _state(
        interests=["physical_therapy"],
        career_goal_signals=["physical_therapist"],
    )
    result = select_recommendation(state, [], _load_taxonomy())

    assert result.behavior == "recommend", (
        f"expected 'recommend', got {result.behavior!r}"
    )
    assert len(result.program_matches) >= 1, "expected at least one program_match"
    top = result.program_matches[0]
    assert top["program_id"] == "dpt-physical-therapy", (
        f"expected dpt-physical-therapy, got {top['program_id']!r}"
    )
    assert top["confidence"] == "high", (
        f"unique career tag must produce high confidence; got {top['confidence']!r}"
    )
    assert top["advisor_email"] == "CHHS-PT@csulb.edu", (
        f"wrong advisor email: {top.get('advisor_email')!r}"
    )


# ---------------------------------------------------------------------------
# T02 — DISC-021
# "I want to pursue educational leadership."
# Expected: EdD-CC + EdD-P12, confidence=medium, behavior=multi_recommend
# Risk: Phase C fires education_undifferentiated → clarify.
#       Phase D must override this to multi_recommend because education_leadership
#       is domain-exclusive to the EdD pair.
# ---------------------------------------------------------------------------

def test_t02_disc021_educational_leadership_phase_c_override():
    """
    Phase C passes education_undifferentiated gap to Phase D.
    Phase D must override clarify → multi_recommend when exactly 2 EdD programs
    both score ≥ low on a domain-exclusive interest tag.
    """
    state = _state(interests=["education_leadership"])
    gaps = ["education_undifferentiated"]
    result = select_recommendation(state, gaps, _load_taxonomy())

    assert result.behavior == "multi_recommend", (
        f"expected 'multi_recommend' (Phase C override), got {result.behavior!r}"
    )
    assert result.confidence == "medium", (
        f"education_leadership is domain-exclusive to EdD pair → 'medium'; "
        f"got {result.confidence!r}"
    )
    ids = _program_ids(result)
    assert "edd-educational-leadership-cc" in ids, (
        f"EdD-CC must be surfaced; got {ids}"
    )
    assert "edd-educational-leadership-p12" in ids, (
        f"EdD-P12 must be surfaced; got {ids}"
    )


# ---------------------------------------------------------------------------
# T03 — DISC-014
# "I'm interested in engineering research combined with mathematical modeling."
# Expected: PhD-Eng, confidence=medium, behavior=partial_match_with_caveat
# Risk: Engineering PhD has null career_goal_tags.  Even at medium confidence
#       (2 interest tags), the behavior MUST be partial_match_with_caveat —
#       never recommend — because career alignment cannot be confirmed.
# ---------------------------------------------------------------------------

def test_t03_disc014_engineering_partial_match_with_caveat():
    """
    Two interest tags give Engineering PhD medium confidence, but null
    career_goal_tags forces behavior=partial_match_with_caveat, never recommend.
    """
    state = _state(
        interests=["engineering", "applied_mathematics"],
        orientation="research",
    )
    result = select_recommendation(state, [], _load_taxonomy())

    assert result.behavior == "partial_match_with_caveat", (
        f"Engineering null career_goal_tags must produce partial_match_with_caveat; "
        f"got {result.behavior!r}"
    )
    assert len(result.program_matches) >= 1, "expected at least one program_match"
    top = result.program_matches[0]
    assert top["program_id"] == "phd-engineering-computational-math", (
        f"expected PhD-Eng at top; got {top['program_id']!r}"
    )
    assert top["confidence"] == "medium", (
        f"2 interest tags → medium; got {top['confidence']!r}"
    )


# ---------------------------------------------------------------------------
# T04 — DISC-026 (known gap)
# "I want to become a professor."
# Expected: DrPH + DNP, medium, multi_recommend.
#           Engineering PhD invisible because career_goal_tags=null +
#           career_goal_signals non-empty → career gap penalty fires.
# ---------------------------------------------------------------------------

def test_t04_disc026_professor_engineering_invisible_known_gap():
    """
    university_educator is shared by DrPH and DNP only.
    PhD-Eng has null career_goal_tags AND career signals are present
    → career gap penalty × 0.50 applied → PhD-Eng score = 0 → not surfaced.
    Result: DrPH + DNP multi_recommend at medium.
    """
    state = _state(career_goal_signals=["university_educator"])
    result = select_recommendation(state, [], _load_taxonomy())

    assert result.behavior == "multi_recommend", (
        f"expected 'multi_recommend'; got {result.behavior!r}"
    )
    assert result.confidence == "medium", (
        f"shared career tag → medium; got {result.confidence!r}"
    )
    ids = _program_ids(result)
    assert "drph-public-health" in ids, f"DrPH must be surfaced; got {ids}"
    assert "dnp-nursing" in ids, f"DNP must be surfaced; got {ids}"
    assert "phd-engineering-computational-math" not in ids, (
        f"PhD-Eng must be invisible (career gap penalty); found in {ids}"
    )


# ---------------------------------------------------------------------------
# T05 — DISC-025
# "I have a healthcare background and want a doctoral degree."
# Expected: clarify — NOT multi_recommend.
# Risk: Phase C fires health_undifferentiated. Phase D sees DrPH + DNP
#       both at LOW confidence (background only = 0.10 each).
#       Phase D override requires MEDIUM confidence → NOT triggered.
#       Must keep clarify.
# ---------------------------------------------------------------------------

def test_t05_disc025_healthcare_background_only_stays_clarify():
    """
    Healthcare background puts DrPH and DNP at low confidence (0.10 each).
    DPT has null academic_background_tags → score = 0.
    Phase D override requires medium confidence → not triggered → clarify.
    Must NOT produce multi_recommend.
    """
    state = _state(academic_background=["healthcare"])
    gaps = ["health_undifferentiated"]
    result = select_recommendation(state, gaps, _load_taxonomy())

    assert result.behavior == "clarify", (
        f"low-confidence programs must not override to multi_recommend; "
        f"got {result.behavior!r}"
    )


# ---------------------------------------------------------------------------
# T06 — DISC-048
# "I want to study computational biology."
# Expected: DrPH, confidence=low, behavior=partial_match_with_caveat
# Risk: adjacent field — must surface a caveat, not a high-confidence rec.
# ---------------------------------------------------------------------------

def test_t06_disc048_computational_biology_adjacent_field():
    """
    'biology' → background tag matches DrPH (score = 0.10, confidence = low).
    No interest tags, no career signal. Adjacent field → partial_match_with_caveat.
    """
    state = _state(academic_background=["biology"])
    result = select_recommendation(state, [], _load_taxonomy())

    assert result.behavior == "partial_match_with_caveat", (
        f"adjacent field must produce partial_match_with_caveat; got {result.behavior!r}"
    )
    assert len(result.program_matches) >= 1
    top = result.program_matches[0]
    assert top["program_id"] == "drph-public-health", (
        f"DrPH should be top match (biology background); got {top['program_id']!r}"
    )
    assert top["confidence"] == "low", (
        f"background-only match → low confidence; got {top['confidence']!r}"
    )


# ---------------------------------------------------------------------------
# T07 — DISC-016
# "I want to get a Doctor of Nursing Practice."
# Expected: DNP, high, recommend + correct advisor email + correct deadline
# Risk: advisor_accuracy is a hard requirement (P5 in eval philosophy).
# ---------------------------------------------------------------------------

def test_t07_disc016_explicit_dnp_high_with_advisor_deadline():
    """
    Explicit degree_type=DNP must produce high-confidence recommend.
    program_matches must contain the correct advisor email and deadline.
    """
    state = _state(degree_type="DNP")
    result = select_recommendation(state, [], _load_taxonomy())

    assert result.behavior == "recommend", (
        f"explicit degree must produce 'recommend'; got {result.behavior!r}"
    )
    assert len(result.program_matches) == 1, (
        f"only one program for explicit DNP; got {len(result.program_matches)}"
    )
    m = result.program_matches[0]
    assert m["program_id"] == "dnp-nursing"
    assert m["confidence"] == "high"
    assert m["advisor_email"] == "cleddhy.arellano@csulb.edu", (
        f"wrong advisor email: {m.get('advisor_email')!r}"
    )
    assert m["deadline_fall"] == "January 15", (
        f"wrong deadline: {m.get('deadline_fall')!r}"
    )


# ---------------------------------------------------------------------------
# T08 — DISC-029
# "I want a clinical doctoral degree in health."
# Expected: DNP + DPT, medium, multi_recommend
# Risk: only orientation signal present → Phase C fires orientation_only.
#       Phase D must recognise clinical orientation as domain-specific to
#       DNP+DPT and override orientation_only → multi_recommend.
# ---------------------------------------------------------------------------

def test_t08_disc029_clinical_orientation_dnp_dpt_multi_recommend():
    """
    orientation='clinical' is domain-specific to DNP and DPT (both have
    clinical orientation in taxonomy).  Phase D must override orientation_only
    → multi_recommend at medium when exactly 2 clinical programs exist.
    """
    state = _state(orientation="clinical")
    gaps = ["orientation_only"]
    result = select_recommendation(state, gaps, _load_taxonomy())

    assert result.behavior == "multi_recommend", (
        f"clinical orientation should override orientation_only → multi_recommend; "
        f"got {result.behavior!r}"
    )
    assert result.confidence == "medium", (
        f"clinical domain-exclusive orientation → medium; got {result.confidence!r}"
    )
    ids = _program_ids(result)
    assert "dnp-nursing" in ids, f"DNP must be surfaced; got {ids}"
    assert "dpt-physical-therapy" in ids, f"DPT must be surfaced; got {ids}"


# ---------------------------------------------------------------------------
# T09 — Admission-gated guard: Phase D must NEVER bypass this gap
# ---------------------------------------------------------------------------

def test_t09_admission_gated_never_bypassed():
    """
    When gaps contains 'admission_gated', Phase D must return behavior=clarify.
    No programs may be surfaced.  This guard is unconditional.
    """
    state = _state(
        interests=["patient_care", "nursing"],
        career_goal_signals=[],
    )
    gaps = ["admission_gated"]
    result = select_recommendation(state, gaps, _load_taxonomy())

    assert result.behavior == "clarify", (
        f"admission_gated must always produce 'clarify'; got {result.behavior!r}"
    )
    assert result.program_matches == [], (
        f"no programs when clarifying; got {result.program_matches}"
    )


# ---------------------------------------------------------------------------
# T10 — DISC-050
# "I have an undergraduate degree in psychology and want to continue in healthcare."
# Expected: DrPH, confidence=low, behavior=partial_match_with_caveat
# Risk: psychology → social_sciences background → DrPH matches.
#       DNP requires BSN+RN (not met) — should score lower than DrPH.
# ---------------------------------------------------------------------------

def test_t10_disc050_psychology_healthcare_drph_partial():
    """
    psychology → social_sciences (DrPH bg), healthcare → healthcare (DrPH + DNP bg).
    DrPH: 2 background matches (+0.20, low confidence).
    DNP: 1 background match (+0.10, low confidence).
    DrPH wins by score spread → partial_match_with_caveat at low.
    """
    state = _state(academic_background=["social_sciences", "healthcare"])
    result = select_recommendation(state, [], _load_taxonomy())

    assert result.behavior == "partial_match_with_caveat", (
        f"expected 'partial_match_with_caveat'; got {result.behavior!r}"
    )
    assert len(result.program_matches) >= 1
    top = result.program_matches[0]
    assert top["program_id"] == "drph-public-health", (
        f"DrPH should be top match (social_sciences + healthcare); "
        f"got {top['program_id']!r}"
    )
    assert top["confidence"] == "low", (
        f"background-only match → low confidence; got {top['confidence']!r}"
    )
