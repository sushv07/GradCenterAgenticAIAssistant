"""
test_student_interest.py
Student Interest Agent — Phase 1 evaluation set (20 scenarios).

Tests cover:
  Group A — Clear doctoral exploration (signal present in Turn 1)
  Group B — Broad/ambiguous exploration (domain_unclear gap)
  Group C — Master's-like exploration (redirect, no hallucination)
  Group D — Out-of-scope exploration (redirect)
  Group E — Multi-turn exploration (domain → domain-specific → recommendation)
  Group F — Routing regressions (deadline/advisor/eligibility must not be stolen)

Run from the project root:
    pytest tests/test_student_interest.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from agents.journey_agent import handle_discovery, _SESSION_STORE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh(sid: str) -> None:
    _SESSION_STORE.pop(sid, None)


def _program_ids(r: dict) -> list[str]:
    return [m["program_id"] for m in r.get("program_matches", [])]


# ===========================================================================
# Group A — Clear doctoral exploration
# Signal present in Turn 1; journey agent should eventually reach a program
# match (may be clarify or recommend depending on signal strength).
# ===========================================================================

class TestClearDoctoralExploration:

    def test_a01_public_health_doctoral(self):
        """Public health interest routes to discovery and surfaces DrPH."""
        _fresh("a01")
        r, _ = handle_discovery(
            "I'm interested in public health and want a doctoral degree", "a01"
        )
        assert r["route"] == "discovery"
        ids = _program_ids(r)
        # DrPH must be the top match — accept any behavior (recommend / partial)
        assert "drph-public-health" in ids or r["behavior"] == "clarify", (
            f"Expected DrPH in matches or clarification; got behavior={r['behavior']!r}, ids={ids}"
        )
        # If programs are surfaced, DrPH must lead
        if ids:
            assert ids[0] == "drph-public-health", (
                f"DrPH must be top match; got {ids}"
            )

    def test_a02_community_health_impact(self):
        """Community health interest surfaces DrPH."""
        _fresh("a02")
        r, _ = handle_discovery("I want to make an impact in community health", "a02")
        assert r["route"] == "discovery"
        ids = _program_ids(r)
        if ids:
            assert "drph-public-health" in ids, (
                f"DrPH must be surfaced for community health; got {ids}"
            )

    def test_a03_dnp_doctoral_nursing_routes_discovery(self):
        """Doctoral nursing query routes to discovery (may clarify for background)."""
        _fresh("a03")
        r, _ = handle_discovery("I want to pursue a doctoral degree in nursing", "a03")
        assert r["route"] == "discovery"
        # System may ask admission_gated question or recommend DNP directly
        if r["behavior"] == "clarify":
            # acceptable — admission background not yet provided
            assert r["confidence"] == "none"
        else:
            assert "dnp-nursing" in _program_ids(r), (
                f"If not clarifying, DNP must be surfaced; got {_program_ids(r)}"
            )

    def test_a04_exploring_education_doctoral_clarifies(self):
        """Education exploration triggers clarification for CC vs P-12 sector."""
        _fresh("a04")
        r, _ = handle_discovery("I'm exploring doctoral programs in education", "a04")
        assert r["route"] == "discovery"
        # 'exploring' → stated_uncertainty; 'education' background extracted
        # Should clarify education sector or domain
        assert r["behavior"] == "clarify", (
            f"Should clarify education sector; got behavior={r['behavior']!r}"
        )

    def test_a05_educational_leadership_career_clarifies(self):
        """Educational leadership interest triggers sector clarification."""
        _fresh("a05")
        r, _ = handle_discovery("I want a career in educational leadership", "a05")
        assert r["route"] == "discovery"
        assert r["behavior"] == "clarify", (
            f"Education undifferentiated should clarify; got {r['behavior']!r}"
        )
        q = (r.get("clarification_question") or "").lower()
        # Question must distinguish CC vs P-12
        assert any(kw in q for kw in ("k-12", "school", "community college", "higher education")), (
            f"Clarification must distinguish education sectors; got: {q!r}"
        )


# ===========================================================================
# Group B — Broad/ambiguous exploration
# These queries have stated_uncertainty and no domain signal.
# Expected: domain_unclear gap → domain-oriented clarification question.
# ===========================================================================

class TestBroadAmbiguousExploration:

    def _assert_domain_question(self, r: dict) -> None:
        """The question must name all four doctoral domains."""
        assert r["behavior"] == "clarify", (
            f"Expected clarify; got {r['behavior']!r}"
        )
        assert r["confidence"] == "none"
        assert r.get("recommended_programs", []) == []
        q = (r.get("clarification_question") or r.get("primary_action") or "").lower()
        for domain in ("healthcare", "education", "public health", "research"):
            assert domain in q, (
                f"Question must mention '{domain}'; got: {q!r}"
            )

    def test_b06_not_sure_what_program(self):
        """'I'm not sure what graduate program fits me.' → domain_unclear clarification."""
        _fresh("b06")
        r, s = handle_discovery(
            "I'm not sure what graduate program fits me.", "b06"
        )
        assert r["route"] == "discovery"
        self._assert_domain_question(r)
        assert s.get("stated_uncertainty") is True

    def test_b07_exploring_options(self):
        """'I'm exploring my options for doctoral study.' → domain-oriented clarification."""
        _fresh("b07")
        r, s = handle_discovery("I'm exploring my options for doctoral study.", "b07")
        assert r["route"] == "discovery"
        self._assert_domain_question(r)
        assert s.get("stated_uncertainty") is True

    def test_b08_dont_know_what_to_choose(self):
        """'I don't know what to choose for graduate school.' → domain-oriented clarification."""
        _fresh("b08")
        r, _ = handle_discovery("I don't know what to choose for graduate school.", "b08")
        assert r["route"] == "discovery"
        assert r["behavior"] == "clarify"
        assert r["confidence"] == "none"

    def test_b09_help_me_figure_out(self):
        """'Help me figure out what graduate program is right for me.' → clarification."""
        _fresh("b09")
        r, _ = handle_discovery(
            "Help me figure out what graduate program is right for me.", "b09"
        )
        assert r["route"] == "discovery"
        assert r["behavior"] == "clarify"
        assert r["confidence"] == "none"

    def test_b10_want_to_help_people(self):
        """'I want to help people but don't know how.' → clarification, no program forced."""
        _fresh("b10")
        r, s = handle_discovery("I want to help people but don't know how.", "b10")
        assert r["route"] == "discovery"
        assert r["behavior"] == "clarify"
        assert r.get("recommended_programs", []) == []
        # stated_uncertainty sticky from "don't know"
        assert s.get("stated_uncertainty") is True

    def test_b06_domain_unclear_question_has_all_four_domains(self):
        """Separate domain-coverage assertion for the canonical exploratory query."""
        _fresh("b06b")
        r, _ = handle_discovery("I'm not sure what graduate program fits me.", "b06b")
        q = (r.get("clarification_question") or "").lower()
        assert "healthcare" in q
        assert "education" in q
        assert "public health" in q
        assert "research" in q

    def test_b06_domain_unclear_no_program_menu(self):
        """Domain-first question must not present program abbreviations."""
        _fresh("b06c")
        r, _ = handle_discovery("I'm not sure what graduate program fits me.", "b06c")
        q = (r.get("clarification_question") or "").lower()
        for abbr in ("dpt", "dnp", "drph", "edd", "phd", "doctor of nursing", "doctor of physical"):
            assert abbr not in q, (
                f"Question must not present a program menu; found {abbr!r} in: {q!r}"
            )


# ===========================================================================
# Group C — Master's-like exploration
# No master's program should be recommended; redirects only.
# ===========================================================================

class TestMastersExploration:

    def test_c11_master_or_doctorate_no_masters_recommendation(self):
        """'I'm not sure whether I should do a master's or doctorate.' → no master's rec."""
        _fresh("c11")
        r, _ = handle_discovery(
            "I'm not sure whether I should do a master's or doctorate.", "c11"
        )
        # master's triggers out-of-scope redirect OR doctoral clarification
        # Either way: no master's program recommended
        for m in r.get("program_matches", []):
            assert "master" not in m.get("program_id", "").lower(), (
                f"Must not recommend a master's program; got {m['program_id']}"
            )
        # If behavior is redirect, the message must acknowledge doctoral coverage
        if r["behavior"] == "redirect":
            msg = (r.get("primary_action") or "").lower()
            assert "doctoral" in msg or "graduate" in msg, (
                f"Redirect should mention doctoral options; got: {msg!r}"
            )

    def test_c12_masters_public_health_redirect(self):
        """'I want a master's degree in public health.' → redirect, no master's rec."""
        _fresh("c12")
        r, _ = handle_discovery("I want a master's degree in public health.", "c12")
        assert r["behavior"] == "redirect", (
            f"Explicit master's must redirect; got {r['behavior']!r}"
        )
        assert r.get("recommended_programs", []) == [], (
            "Must not surface any programs for master's query"
        )

    def test_c12b_masters_public_health_redirect_curly_apostrophe(self):
        """Same query with a curly apostrophe (smart-quote autocorrect) must still redirect.

        Streamlit/browser autocorrect commonly substitutes U+2019 (’) for the
        ASCII apostrophe ('). Without normalization, 'master's degree' would not
        match '_OUT_OF_SCOPE_MAP' and the query would fall through to doctoral
        program matching instead of redirecting.
        """
        _fresh("c12b")
        r, _ = handle_discovery(
            "I want a master’s degree in public health.", "c12b"
        )
        assert r["behavior"] == "redirect", (
            f"Curly-apostrophe master's query must still redirect; got {r['behavior']!r}"
        )
        assert r.get("recommended_programs", []) == [], (
            f"Must not surface any doctoral programs; got {r.get('recommended_programs')}"
        )
        assert r.get("program_matches", []) == [], (
            f"Must not surface program_matches; got {r.get('program_matches')}"
        )

    def test_c13_masters_education_redirect(self):
        """'I'm interested in a master's program in education.' → redirect."""
        _fresh("c13")
        r, _ = handle_discovery("I'm interested in a master's program in education.", "c13")
        assert r["behavior"] == "redirect"
        assert r.get("recommended_programs", []) == []
        # Redirect message should acknowledge doctoral coverage
        msg = (r.get("primary_action") or "").lower()
        assert "doctoral" in msg or "graduate" in msg, (
            f"Redirect should guide toward doctoral; got: {msg!r}"
        )

    def test_c14_masters_full_path_via_orchestrator_ascii(self):
        """Full UI path (router → discovery → redirect) for ASCII apostrophe.

        handle_discovery() called directly bypasses the router entirely — this
        test goes through orchestrator.run() to prove the router actually sends
        master's queries to discovery instead of Branch 5 (advisor_suggestions)
        or Branch 6 (doctoral_no_match).
        """
        import orchestrator as orch
        r = orch.run("I want a master's degree in public health.", session_id="c14")
        assert r.get("route") == "discovery", (
            f"Master's query must route to discovery; got route={r.get('route')!r}"
        )
        assert r.get("behavior") == "redirect", (
            f"Must redirect, not suggest doctoral programs; got behavior={r.get('behavior')!r}"
        )
        assert r.get("recommended_programs", []) == [], (
            f"Must not surface doctoral programs; got {r.get('recommended_programs')}"
        )
        assert r.get("program_matches", []) == [], (
            f"Must not surface program_matches; got {r.get('program_matches')}"
        )

    def test_c14b_masters_full_path_via_orchestrator_curly(self):
        """Full UI path for curly apostrophe — the exact query from manual UI testing.

        Before the router fix, this fell through to Branch 5 and returned
        route=advisor with suggestions=["Public Health (DR.P.H.)", "Nursing (D.N.P.)",
        "Anthropology"] instead of a graceful redirect.
        """
        import orchestrator as orch
        r = orch.run("I want a master’s degree in public health.", session_id="c14b")
        assert r.get("route") == "discovery", (
            f"Master's query must route to discovery; got route={r.get('route')!r}"
        )
        assert r.get("behavior") == "redirect", (
            f"Must redirect, not suggest doctoral programs; got behavior={r.get('behavior')!r}"
        )
        assert r.get("recommended_programs", []) == [], (
            f"Must not surface doctoral programs; got {r.get('recommended_programs')}"
        )
        assert r.get("program_matches", []) == [], (
            f"Must not surface program_matches; got {r.get('program_matches')}"
        )

    def test_c14c_masters_or_doctorate_full_path(self):
        """Full UI path for 'master's or doctorate' uncertainty query.

        Before the router fix, this fell through to Branch 6 (doctoral_no_match)
        because the 'doctorate' token triggered the doctoral fallback before
        the master's signal could ever be considered.
        """
        import orchestrator as orch
        r = orch.run(
            "I'm not sure whether I should do a master's or doctorate.",
            session_id="c14c",
        )
        assert r.get("route") == "discovery", (
            f"Must route to discovery; got route={r.get('route')!r}"
        )
        for m in r.get("program_matches", []) or []:
            assert "master" not in m.get("program_id", "").lower()


# ===========================================================================
# Group D — Out-of-scope exploration
# ===========================================================================

class TestOutOfScopeExploration:

    def test_d14_medical_school_redirect(self):
        """'I want to go to medical school.' → redirect, no CSULB doctoral rec."""
        _fresh("d14")
        r, _ = handle_discovery("I want to go to medical school.", "d14")
        assert r["behavior"] == "redirect"
        assert r.get("recommended_programs", []) == []

    def test_d15_other_institution_redirect(self):
        """'I'm interested in programs at UCLA.' → redirect, no CSULB rec."""
        _fresh("d15")
        r, _ = handle_discovery("I'm interested in programs at UCLA.", "d15")
        assert r["behavior"] == "redirect"
        assert r.get("recommended_programs", []) == []


# ===========================================================================
# Group E — Multi-turn exploration
# ===========================================================================

class TestMultiTurnExploration:

    def test_e16_healthcare_to_physical_therapy_to_dpt(self):
        """T1 uncertain → T2 healthcare → T3 physical therapy → DPT surfaces."""
        sid = "e16"
        _fresh(sid)

        # Turn 1 — exploration, no domain
        r1, s1 = handle_discovery("I'm not sure what fits me.", sid)
        assert r1["behavior"] == "clarify"
        assert s1.get("stated_uncertainty") is True
        assert _program_ids(r1) == []

        # Turn 2 — domain signal (healthcare background)
        r2, s2 = handle_discovery("healthcare", sid)
        assert r2["behavior"] == "clarify"   # should ask goal-oriented healthcare question
        assert r2["route"] == "discovery"

        # Turn 3 — specific signal (physical therapy)
        r3, s3 = handle_discovery("physical therapy", sid)
        assert r3["route"] == "discovery"
        ids3 = _program_ids(r3)
        assert "dpt-physical-therapy" in ids3, (
            f"DPT must surface after physical therapy signal; got {ids3}"
        )

    def test_e17_exploring_to_education_to_k12_to_edd_p12(self):
        """T1 exploring → T2 education → T3 K-12 → EdD-P12 surfaces.

        T2 must escape domain_unclear into education_undifferentiated and ask
        the CC-vs-P12 sector question — it must NOT repeat the domain_unclear
        question. This is the regression covered by the Issue 1 fix.
        """
        sid = "e17"
        _fresh(sid)

        r1, _ = handle_discovery("I'm exploring my options.", sid)
        assert r1["behavior"] == "clarify"

        r2, _ = handle_discovery("education", sid)
        assert r2["route"] == "discovery"
        assert r2["behavior"] == "clarify", (
            f"Education background alone should still clarify; got {r2['behavior']!r}"
        )
        q2 = (r2.get("clarification_question") or "").lower()
        assert "k-12" in q2 or "k12" in q2, (
            f"Turn 2 must ask the K-12 vs CC/higher-ed sector question; got: {q2!r}"
        )
        assert "community college" in q2 or "higher education" in q2, (
            f"Turn 2 question must mention community college / higher education; got: {q2!r}"
        )
        # Must NOT repeat the domain_unclear question (no four-domain enumeration)
        assert "research and engineering" not in q2, (
            f"Turn 2 must escape domain_unclear, not repeat it; got: {q2!r}"
        )
        # Must NOT be the generic Phase D clarify-fallback placeholder
        assert "career goals" not in q2, (
            f"Turn 2 must not fall back to the generic career-goals question; got: {q2!r}"
        )

        r3, _ = handle_discovery("K-12 schools", sid)
        assert r3["route"] == "discovery"
        ids3 = _program_ids(r3)
        assert "edd-educational-leadership-p12" in ids3, (
            f"EdD-P12 must surface after K-12 signal; got {ids3}"
        )

    def test_e17b_education_undifferentiated_survives_phase_d_fallback(self):
        """Root-cause regression: when the 3-turn stopping rule forces Phase D
        (select_recommendation) to handle the clarify decision instead of Phase C,
        and the EdD multi_recommend override conditions aren't met (only a
        background match, no interest match), the question must still be the
        domain-specific K-12/CC question — not the generic _build_response()
        placeholder ("Can you tell me more about your career goals?").

        This is the actual root cause behind the manual UI report: by the time
        'education' lands on a session with turn_count already >= 2, should_clarify()
        is bypassed by the stopping rule, select_recommendation() falls through to
        a bare _clarify_result() with no question, and _build_response() used to
        substitute the generic fallback.
        """
        sid = "e17b"
        _fresh(sid)

        handle_discovery("I'm exploring my options.", sid)          # turn 1
        handle_discovery("still not sure, just exploring", sid)     # turn 2

        r3, s3 = handle_discovery("education", sid)                 # turn 3 -> stopping rule
        assert s3["turn_count"] == 3
        assert r3["behavior"] == "clarify"
        q3 = (r3.get("clarification_question") or r3.get("primary_action") or "").lower()
        assert "k-12" in q3 or "k12" in q3, (
            f"Phase D fallback must still ask the K-12/CC question; got: {q3!r}"
        )
        assert "community college" in q3 or "higher education" in q3, (
            f"Phase D fallback question must mention CC/higher-ed; got: {q3!r}"
        )
        assert "career goals" not in q3, (
            f"Phase D fallback must not use the generic career-goals placeholder; got: {q3!r}"
        )

    def test_e18_dont_know_to_public_health_policy_drph(self):
        """T1 don't know → T2 public health policy → DrPH recommended."""
        sid = "e18"
        _fresh(sid)

        r1, _ = handle_discovery("I don't know what path to take.", sid)
        assert r1["behavior"] == "clarify"

        r2, _ = handle_discovery("public health policy", sid)
        assert r2["route"] == "discovery"
        ids2 = _program_ids(r2)
        assert "drph-public-health" in ids2, (
            f"DrPH must surface after public health policy signal; got {ids2}"
        )
        assert r2["behavior"] in ("recommend", "multi_recommend", "partial_match_with_caveat"), (
            f"Should surface a recommendation; got {r2['behavior']!r}"
        )

    def test_e18_stated_uncertainty_sticky(self):
        """stated_uncertainty set in T1 persists into T2."""
        sid = "e18b"
        _fresh(sid)
        _, s1 = handle_discovery("I don't know what path to take.", sid)
        assert s1.get("stated_uncertainty") is True
        _, s2 = handle_discovery("public health", sid)
        assert s2.get("stated_uncertainty") is True


# ===========================================================================
# Group F — Routing regressions
# Deadline / advisor / eligibility queries must NOT be stolen by discovery.
# ===========================================================================

class TestRoutingRegressions:

    def test_f19_deadline_not_discovery(self):
        """'I'm not sure what the deadline is.' → deadlines route, not discovery."""
        import orchestrator as orch
        r = orch.run("I'm not sure what the deadline is.", session_id="f19")
        assert r.get("route") != "discovery", (
            f"Deadline query must not route to discovery; got route={r.get('route')!r}"
        )
        assert r.get("route") == "deadlines", (
            f"Deadline query must route to deadlines; got route={r.get('route')!r}"
        )

    def test_f19b_deadlines_plural_not_discovery(self):
        """'I'm not sure what the deadlines are.' → deadlines, not discovery."""
        import orchestrator as orch
        r = orch.run("I'm not sure what the deadlines are.", session_id="f19b")
        assert r.get("route") != "discovery", (
            f"Deadlines query must not route to discovery; got {r.get('route')!r}"
        )

    def test_f20_advisor_not_discovery(self):
        """'Who is the advisor for the program I'm exploring?' → NOT discovery.
        The advisor signal in the query blocks Branch 1.5 (discovery).
        Downstream route depends on fuzzy-match score — we only verify discovery is blocked.
        """
        import orchestrator as orch
        r = orch.run(
            "Who is the advisor for the program I'm exploring?", session_id="f20"
        )
        assert r.get("route") != "discovery", (
            f"Advisor query must not route to discovery; got route={r.get('route')!r}"
        )

    def test_f20b_eligibility_not_discovery(self):
        """'What are the GPA requirements?' → eligibility, not discovery."""
        import orchestrator as orch
        r = orch.run("What are the GPA requirements?", session_id="f20b")
        assert r.get("route") != "discovery", (
            f"Eligibility query must not route to discovery; got {r.get('route')!r}"
        )
        assert r.get("route") == "eligibility", (
            f"Eligibility query must route to eligibility; got route={r.get('route')!r}"
        )
