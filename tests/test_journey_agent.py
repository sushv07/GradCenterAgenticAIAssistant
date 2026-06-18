"""
test_journey_agent.py
Unit tests for agents/journey_agent.py — Phase C state machine.

Tests are ordered highest-risk first (per Phase C design audit):
  1. "I want to be a doctor" — term ambiguity Q5 must fire, not recommend
  2. EdD sector differentiation — CC vs. P-12 distinguished correctly
  3. Engineering partial-match — engineering signal surfaces without recommendation

Run from the project root:
    python tests/test_journey_agent.py
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.journey_agent import (
    extract_signals,
    init_journey_state,
    _update_state,
    detect_gaps,
    should_clarify,
    select_question,
    _classify_behavior,
    handle_discovery,
    _SESSION_STORE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_state(session_id: str = "test"):
    return init_journey_state(session_id)


def _run(query: str, session_id: str = "test") -> dict:
    """Run handle_discovery with a fresh state (clears any stored state first)."""
    _SESSION_STORE.pop(session_id, None)
    response, _ = handle_discovery(query, session_id)
    return response


def _test(desc: str, passed: bool) -> bool:
    status = "✓" if passed else "✗"
    print(f"  {status}  {desc}")
    return passed


# ---------------------------------------------------------------------------
# ── HIGH-RISK TEST 1: "I want to be a doctor" → clarify Q5 (not recommend)
# ---------------------------------------------------------------------------

def _risk1_doctor_ambiguity() -> list[bool]:
    results = []

    # Core case: "I want to be a doctor" has no clinical context → Q5
    r = _run("I want to be a doctor")
    results.append(_test(
        'HIGH-RISK 1a: "I want to be a doctor" → behavior=clarify',
        r["behavior"] == "clarify",
    ))
    results.append(_test(
        'HIGH-RISK 1b: "I want to be a doctor" → Q5 (MD disambiguation)',
        "clarification_question" in r and "MD" in r["clarification_question"],
    ))
    results.append(_test(
        'HIGH-RISK 1c: "I want to be a doctor" → recommended_programs=[]',
        r["recommended_programs"] == [],
    ))
    results.append(_test(
        'HIGH-RISK 1d: "I want to be a doctor" → confidence="none"',
        r["confidence"] == "none",
    ))

    # Negative: "I want a doctor of physical therapy" has clinical context → no Q5
    r2 = _run("I want a doctor of physical therapy")
    results.append(_test(
        'HIGH-RISK 1e: "I want a doctor of physical therapy" does NOT trigger Q5',
        not ("clarification_question" in r2 and "MD" in r2.get("clarification_question", "")),
    ))

    # Negative: "become a doctor of nursing practice" → degree_type=DNP, no Q5
    bundle = extract_signals("I want to become a doctor of nursing practice")
    results.append(_test(
        'HIGH-RISK 1f: "doctor of nursing practice" → degree_type=DNP, no term_ambiguity',
        bundle.degree_type == "DNP" and bundle.term_ambiguity is None,
    ))

    return results


# ---------------------------------------------------------------------------
# ── HIGH-RISK TEST 2: EdD sector differentiation (CC vs. P-12)
# ---------------------------------------------------------------------------

def _risk2_edd_differentiation() -> list[bool]:
    results = []

    # "educational leadership" alone → education_undifferentiated → Q5-education
    r = _run("I want to pursue educational leadership")
    results.append(_test(
        'HIGH-RISK 2a: "educational leadership" → behavior=clarify (undifferentiated)',
        r["behavior"] == "clarify",
    ))
    results.append(_test(
        'HIGH-RISK 2b: "educational leadership" → Q5-education (CC vs. P-12)',
        "clarification_question" in r and "K-12" in r["clarification_question"],
    ))

    # "leadership" alone (no educational qualifier) → Q5-leadership (sector)
    r2 = _run("I want a career in leadership")
    results.append(_test(
        'HIGH-RISK 2c: "leadership" alone → clarify Q5-leadership (sector)',
        r2["behavior"] == "clarify" and
        "clarification_question" in r2 and
        "sector" in r2["clarification_question"].lower(),
    ))

    # "community college dean" → unique career → recommend (not multi)
    r3 = _run("I want to become a community college dean")
    results.append(_test(
        'HIGH-RISK 2d: "community college dean" → behavior=recommend (unique career)',
        r3["behavior"] == "recommend",
    ))
    results.append(_test(
        'HIGH-RISK 2e: "community college dean" → recommended_programs=[] (Phase D fills)',
        r3["recommended_programs"] == [],
    ))

    # "school superintendent" → unique career → recommend (P-12, not CC)
    r4 = _run("I want to become a school superintendent")
    results.append(_test(
        'HIGH-RISK 2f: "school superintendent" → behavior=recommend (unique P-12 career)',
        r4["behavior"] == "recommend",
    ))

    # "educational leadership for community college" → CC sector → recommend (not undiff)
    r5 = _run("I want educational leadership for community college")
    results.append(_test(
        'HIGH-RISK 2g: "educational leadership for community college" → NOT undifferentiated',
        r5["behavior"] != "clarify" or
        "K-12" not in r5.get("clarification_question", ""),
    ))

    return results


# ---------------------------------------------------------------------------
# ── HIGH-RISK TEST 3: Engineering partial-match (no recommendation)
# ---------------------------------------------------------------------------

def _risk3_engineering_partial_match() -> list[bool]:
    results = []

    # Engineering interest alone → partial_match_with_caveat
    r = _run("I am interested in engineering research")
    results.append(_test(
        'HIGH-RISK 3a: "engineering research" → behavior=partial_match_with_caveat',
        r["behavior"] == "partial_match_with_caveat",
    ))
    results.append(_test(
        'HIGH-RISK 3b: "engineering research" → recommended_programs=[] (invariant)',
        r["recommended_programs"] == [],
    ))
    results.append(_test(
        'HIGH-RISK 3c: "engineering research" → confidence="none" (invariant)',
        r["confidence"] == "none",
    ))

    # Engineering + applied mathematics → still partial (no career signal)
    r2 = _run("I am interested in engineering and mathematical modeling")
    results.append(_test(
        'HIGH-RISK 3d: "engineering + mathematical modeling" → partial_match_with_caveat',
        r2["behavior"] == "partial_match_with_caveat",
    ))

    # "engineering" with a career signal would change behavior (Phase D logic),
    # but in Phase C the career tag just influences classify_behavior
    bundle = extract_signals("I want to do research in computational mathematics")
    results.append(_test(
        'HIGH-RISK 3e: "computational mathematics" → interest tag extracted',
        "computational_mathematics" in bundle.interests,
    ))

    # Engineering + explicit PhD → recommend (degree_type overrides)
    r3 = _run("I want to pursue a PhD in engineering")
    results.append(_test(
        'HIGH-RISK 3f: "PhD in engineering" → degree_type sets behavior=recommend',
        r3["behavior"] == "recommend",
    ))

    return results


# ---------------------------------------------------------------------------
# ── Tests 4-20: full suite
# ---------------------------------------------------------------------------

def _test_init_state() -> list[bool]:
    s = init_journey_state("s1")
    return [
        _test("init_state: phase=init",           s["phase"] == "init"),
        _test("init_state: turn_count=0",          s["turn_count"] == 0),
        _test("init_state: interests=[]",          s["interests"] == []),
        _test("init_state: academic_background=[]", s["academic_background"] == []),
        _test("init_state: recommended_programs=[]", s["recommended_programs"] == []),
        _test("init_state: delegated_routes=[]",   s["delegated_routes"] == []),
    ]


def _test_extract_unique_career() -> list[bool]:
    b = extract_signals("I want to become a physical therapist")
    return [
        _test("extract_career: physical_therapist extracted",
              "physical_therapist" in b.career_goals),
        _test("extract_career: no term_ambiguity",
              b.term_ambiguity is None),
    ]


def _test_extract_interest_tags() -> list[bool]:
    b = extract_signals("I am passionate about biomechanics and rehabilitation")
    return [
        _test("extract_interest: biomechanics extracted", "biomechanics" in b.interests),
        _test("extract_interest: rehabilitation extracted", "rehabilitation" in b.interests),
    ]


def _test_extract_background() -> list[bool]:
    b = extract_signals("I am a registered nurse and want a doctoral degree")
    return [
        _test("extract_background: nursing extracted", "nursing" in b.academic_bg),
    ]


def _test_extract_degree_type() -> list[bool]:
    b = extract_signals("I want to get a DNP")
    return [
        _test("extract_degree: DNP extracted", b.degree_type == "DNP"),
    ]


def _test_no_clarify_unique_career() -> list[bool]:
    r = _run("I want to become a physical therapist")
    return [
        _test("no_clarify_unique_career: behavior=recommend",
              r["behavior"] == "recommend"),
        _test("no_clarify_unique_career: recommended_programs=[] (Phase D)",
              r["recommended_programs"] == []),
    ]


def _test_no_clarify_degree_explicit() -> list[bool]:
    r = _run("I want to get a DNP")
    return [
        _test("no_clarify_degree: behavior=recommend (explicit degree)",
              r["behavior"] == "recommend"),
    ]


def _test_clarify_no_signals() -> list[bool]:
    r = _run("I want to help people")
    return [
        _test("clarify_no_signals: behavior=clarify",
              r["behavior"] == "clarify"),
        _test("clarify_no_signals: Q1 (field exploration)",
              "clarification_question" in r and "field" in r["clarification_question"].lower()),
    ]


def _test_clarify_vague() -> list[bool]:
    r = _run("I want to advance my career")
    return [
        _test("clarify_vague: behavior=clarify",
              r["behavior"] == "clarify"),
    ]


def _test_clarify_orientation_only() -> list[bool]:
    r = _run("I want to do research")
    return [
        _test("clarify_orientation_only: behavior=clarify (research only, no field)",
              r["behavior"] == "clarify"),
    ]


def _test_redirect_masters() -> list[bool]:
    r = _run("I want an MBA")
    return [
        _test("redirect_masters: behavior=redirect", r["behavior"] == "redirect"),
        _test("redirect_masters: recommended_programs=[]", r["recommended_programs"] == []),
        _test("redirect_masters: confidence=none",   r["confidence"] == "none"),
    ]


def _test_redirect_other_institution() -> list[bool]:
    r = _run("I want to go to USC for graduate school")
    return [
        _test("redirect_other_institution: behavior=redirect", r["behavior"] == "redirect"),
    ]


def _test_stopping_rule() -> list[bool]:
    s = init_journey_state("stop-test")
    s["turn_count"] = 3
    gaps = ["no_field_signal", "education_undifferentiated", "term_ambiguity_doctor"]
    return [
        _test("stopping_rule: should_clarify=False at turn_count=3 regardless of gaps",
              should_clarify(s, gaps) is False),
        _test("stopping_rule: should_clarify=False at turn_count=4",
              should_clarify({**s, "turn_count": 4}, gaps) is False),
        _test("stopping_rule: should_clarify=True at turn_count=2 with gaps",
              should_clarify({**s, "turn_count": 2}, gaps) is True),
    ]


def _test_state_accumulation() -> list[bool]:
    _SESSION_STORE.pop("acc-test", None)
    _, s1 = handle_discovery("I want to become a physical therapist", "acc-test")
    _, s2 = handle_discovery("I also have a biomechanics background", "acc-test")
    return [
        _test("accumulation: turn_count increments", s2["turn_count"] == 2),
        _test("accumulation: career from turn 1 preserved",
              "physical_therapist" in s2.get("career_goal_signals", [])),
        _test("accumulation: interests deduplicated (no double-adds)",
              s2["interests"].count("physical_therapy") <= 1),
    ]


def _test_phase_transitions() -> list[bool]:
    _SESSION_STORE.pop("phase-test", None)
    # Strong first signal → recommending
    _, s_rec = handle_discovery("I want to become a nurse practitioner", "phase-test")
    results = [
        _test("phase_transition: strong first signal → phase=recommending",
              s_rec["phase"] == "recommending"),
    ]
    # Vague first signal → clarifying
    _SESSION_STORE.pop("phase-test2", None)
    _, s_clar = handle_discovery("I want to help people", "phase-test2")
    results.append(_test(
        "phase_transition: vague first signal → phase=clarifying",
        s_clar["phase"] == "clarifying",
    ))
    # Out-of-scope → stays at init
    _SESSION_STORE.pop("phase-test3", None)
    _, s_oos = handle_discovery("I want an MBA", "phase-test3")
    results.append(_test(
        "phase_transition: out-of-scope → phase=init",
        s_oos["phase"] == "init",
    ))
    return results


def _test_invariants() -> list[bool]:
    """Every Phase C response must have recommended_programs=[] and confidence='none'."""
    cases = [
        "I want to become a physical therapist",
        "I want to help people",
        "I want an MBA",
        "I want educational leadership",
        "I want to be a doctor",
        "I'm interested in engineering",
    ]
    results = []
    for q in cases:
        _SESSION_STORE.pop("inv-test", None)
        r = _run(q, "inv-test")
        results.append(_test(
            f'invariant recommended_programs=[] for: "{q[:45]}"',
            r["recommended_programs"] == [],
        ))
        results.append(_test(
            f'invariant confidence="none" for: "{q[:45]}"',
            r["confidence"] == "none",
        ))
    return results


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_tests(verbose: bool = True) -> bool:
    if verbose:
        print("=" * 64)
        print("test_journey_agent.py — Phase C state machine unit tests")
        print("=" * 64)

    all_results: list[bool] = []

    print("\n── HIGH-RISK TESTS ──────────────────────────────────────────")
    all_results += _risk1_doctor_ambiguity()
    all_results += _risk2_edd_differentiation()
    all_results += _risk3_engineering_partial_match()

    print("\n── SIGNAL EXTRACTION ────────────────────────────────────────")
    all_results += _test_init_state()
    all_results += _test_extract_unique_career()
    all_results += _test_extract_interest_tags()
    all_results += _test_extract_background()
    all_results += _test_extract_degree_type()

    print("\n── CLARIFY VS RESPOND ───────────────────────────────────────")
    all_results += _test_no_clarify_unique_career()
    all_results += _test_no_clarify_degree_explicit()
    all_results += _test_clarify_no_signals()
    all_results += _test_clarify_vague()
    all_results += _test_clarify_orientation_only()

    print("\n── REDIRECTS ────────────────────────────────────────────────")
    all_results += _test_redirect_masters()
    all_results += _test_redirect_other_institution()

    print("\n── STATE MACHINE ────────────────────────────────────────────")
    all_results += _test_stopping_rule()
    all_results += _test_state_accumulation()
    all_results += _test_phase_transitions()

    print("\n── PHASE C INVARIANTS ───────────────────────────────────────")
    all_results += _test_invariants()

    passed = sum(all_results)
    total  = len(all_results)
    print(f"\n{'=' * 64}")
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print(f"\n  ✗ {total - passed} test(s) FAILED — see details above.")
    else:
        print("\n  All journey agent tests passed.")
    return passed == total


if __name__ == "__main__":
    ok = run_tests(verbose=True)
    sys.exit(0 if ok else 1)
