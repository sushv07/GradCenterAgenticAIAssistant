"""
journey_agent.py
Student Interest Journey Agent — Phase C state machine.

Phase C responsibilities:
  - Extract taxonomy-aligned signals from a query (deterministic keyword maps, no LLM)
  - Accumulate signals across turns into JourneyState
  - Detect missing signal types (gaps)
  - Decide: clarify (ask a question) OR surface a placeholder DiscoveryResponse
  - Enforce the 3-question stopping rule

NOT in Phase C:
  - Scoring programs against signals (Phase D)
  - Populating recommended_programs (Phase D)
  - Determining final confidence level (Phase D)
  - LLM reasoning, LangGraph, multi-agent patterns

Invariants enforced here:
  - Every response has recommended_programs=[]  (Phase D fills this)
  - Every response has confidence="none"         (Phase D fills this)
  - should_clarify() returns False when turn_count >= 3 (stopping rule)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from contracts.journey_state import JourneyState
from contracts.response_types import DiscoveryResponse
from agents.recommendation_engine import (
    _RecommendationResult,
    _load_taxonomy,
    select_recommendation,
)
from gradcenter_logging import emit
from state.context_manager import get_context, save_context
from responses.builder import build_response
from agents.recommendation_explainer import attach_explanations


# ---------------------------------------------------------------------------
# Taxonomy signal maps
# All dicts are sorted longest-phrase-first at module load so substring
# matching favours the most specific phrase (e.g. "nurse practitioner"
# matches before "nurse").
# ---------------------------------------------------------------------------

_INTEREST_MAP: dict[str, str] = {
    # DPT
    "physical therapy":           "physical_therapy",
    "physical therapist":         "physical_therapy",
    "physical therapists":        "physical_therapy",
    "rehabilitation":             "rehabilitation",
    "biomechanics":               "biomechanics",
    "movement science":           "movement_science",
    # DNP
    "mental health nursing":      "mental_health",
    "mental health nurse":        "mental_health",
    "psychiatric nursing":        "mental_health",
    "nursing":                    "nursing",
    "nurse":                      "nursing",
    "pediatric care":             "pediatric_care",
    "pediatrics":                 "pediatric_care",
    "pediatric":                  "pediatric_care",
    "gerontology":                "gerontology",
    "elderly care":               "gerontology",
    "patient care":               "patient_care",
    "healthcare leadership":      "healthcare_leadership",
    "clinical leadership":        "healthcare_leadership",
    # DrPH
    "population health":          "public_health",
    "global health":              "global_health",
    "community health":           "community_health",
    "health policy":              "health_policy",
    "health informatics":         "health_informatics",
    "public health":              "public_health",
    "health disparities":         "public_health",
    "underserved communities":    "community_health",
    "underserved":                "community_health",
    # DPT rehabilitation phrases
    "recover movement":           "rehabilitation",
    "movement recovery":          "rehabilitation",
    "restore movement":           "rehabilitation",
    # EdD-CC
    "community college":          "community_college",
    "student affairs":            "student_affairs",
    "institutional leadership":   "institutional_leadership",
    "higher education":           "higher_education",
    # EdD-P12
    "urban public school":        "k12_education",
    "urban school":               "k12_education",
    "student outcomes":           "school_reform",
    "k-12":                       "k12_education",
    "k12":                        "k12_education",
    "school reform":              "school_reform",
    "education policy":           "education_policy",
    "curriculum instruction":     "curriculum_instruction",
    "curriculum":                 "curriculum_instruction",
    # Shared education (CC + P12)
    "educational leadership":     "education_leadership",
    "education leadership":       "education_leadership",
    # Engineering
    "computational mathematics":  "computational_mathematics",
    "applied mathematics":        "applied_mathematics",
    "mathematical modeling":      "applied_mathematics",
    "engineering research":       "engineering",
    "engineering":                "engineering",
}

_CAREER_MAP: dict[str, str] = {
    # DPT — unique to this program
    "become a physical therapist": "physical_therapist",
    "physical therapist":          "physical_therapist",
    "become a pt":                 "physical_therapist",
    # DNP — unique
    "family nurse practitioner":   "nurse_practitioner",
    "advanced practice nursing":   "nurse_practitioner",
    "advanced practice nurse":     "nurse_practitioner",
    "nurse practitioner":          "nurse_practitioner",
    "fnp":                         "nurse_practitioner",
    # DrPH — unique
    "public health director":      "public_health_leader",
    "public health executive":     "public_health_leader",
    "health executive":            "public_health_leader",
    "health director":             "public_health_leader",
    "policy maker":                "policy_maker",
    "policymaker":                 "policy_maker",
    "applied researcher":          "applied_researcher",
    # EdD-CC — unique
    "community college president": "college_administrator",
    "community college leader":    "college_administrator",
    "community college dean":      "college_administrator",
    "college administrator":       "college_administrator",
    "college dean":                "college_administrator",
    "vice president":              "college_administrator",
    "dean":                        "college_administrator",
    # EdD-P12 — unique
    "district administrator":      "school_administrator",
    "district leadership":         "school_administrator",
    "district leader":             "school_administrator",
    "school administrator":        "school_administrator",
    "school principal":            "school_administrator",
    "superintendent":              "school_administrator",
    "principal":                   "school_administrator",
    # Shared DNP + DrPH
    "teach at a university":       "university_educator",
    "university educator":         "university_educator",
    "faculty member":              "university_educator",
    "professor":                   "university_educator",
    "faculty":                     "university_educator",
    # Shared DPT + DNP
    "clinical leader":             "clinical_leader",
}

_BACKGROUND_MAP: dict[str, str] = {
    "nursing background":          "nursing",
    "registered nurse":            "nursing",
    "bsn rn":                      "nursing",
    "bsn":                         "nursing",
    "healthcare background":       "healthcare",
    "health care":                 "healthcare",
    "healthcare":                  "healthcare",
    "public health background":    "public_health",
    "social sciences":             "social_sciences",
    "social science":              "social_sciences",
    "sociology":                   "social_sciences",
    "psychology":                  "social_sciences",
    "education background":        "education",
    "teaching background":         "education",
    "teaching":                    "education",
    "teacher":                     "education",
    "education":                   "education",    # one-word domain answer from domain_unclear clarification
    "biology":                     "biology",
    "engineering background":      "engineering",
    "mathematics background":      "mathematics",
    "math background":             "mathematics",
    "business":                    "business",
}

_ORIENTATION_MAP: dict[str, str] = {
    "academic research":     "research",
    "research degree":       "research",
    "do research":           "research",
    "researcher":            "research",
    "research":              "research",
    "clinical practice":     "clinical",
    "clinical work":         "clinical",
    "clinical":              "clinical",
    "professional practice": "professional",
    "applied practice":      "applied",
    "applied":               "applied",
    "community-based":       "applied",
}

_DEGREE_MAP: dict[str, str] = {
    "doctor of nursing practice":  "DNP",
    "doctor of physical therapy":  "DPT",
    "doctor of public health":     "DrPH",
    "doctor of education":         "EdD",
    "doctor of philosophy":        "PhD",
    "dnp":                         "DNP",
    "dpt":                         "DPT",
    "drph":                        "DrPH",
    "dr.p.h":                      "DrPH",
    "edd":                         "EdD",
    "ed.d":                        "EdD",
    "phd":                         "PhD",
    "ph.d":                        "PhD",
}

_OUT_OF_SCOPE_MAP: dict[str, str] = {
    "master of business administration": "masters_business",
    "mba":                    "masters_business",
    "master of science":      "masters_level",
    "master of arts":         "masters_level",
    "master of education":    "masters_level",
    "master's degree":        "masters_level",
    "masters degree":         "masters_level",
    "master's":               "masters_level",
    "undergraduate":          "undergrad",
    "bachelor":               "undergrad",
    "easiest to get into":    "difficulty_framing",
    "easiest doctoral":       "difficulty_framing",
    "easiest program":        "difficulty_framing",
    "medical school":         "medical_school",
    "md program":             "medical_school",
    "usc":                    "other_institution",
    "ucla":                   "other_institution",
    "quantum computing":      "unsupported_topic",
    "artificial intelligence": "unsupported_topic",
}

# Phrases that, when present, make "leadership" or "education" unambiguous
# (no Q5 term-disambiguation needed)
_LEADERSHIP_QUALIFIERS: frozenset[str] = frozenset({
    "educational leadership", "education leadership",
    "healthcare leadership", "clinical leadership",
    "institutional leadership", "community college leadership",
    "school leadership", "district leadership", "k-12 leadership",
})

# Doctor-phrase triggers for MD-vs-doctoral disambiguation
_DOCTOR_PHRASES: tuple[str, ...] = (
    "i want to be a doctor",
    "want to be a doctor",
    "become a doctor",
    "be a doctor",
    "i want to be doctor",
)

# Phrases that signal the student is explicitly uncertain or exploring options.
# Detected in extract_signals(); accumulated as stated_uncertainty=True in JourneyState.
_STATED_UNCERTAINTY_PHRASES: frozenset[str] = frozenset({
    "not sure",
    "don't know",
    "do not know",
    "exploring",
    "figure out",
    "not certain",
    "unsure",
})

# Phrases indicating the student is describing an ALREADY-HELD credential,
# not a stated goal — e.g. "I have a PhD" vs "I want a PhD". Each phrase
# includes the article/possessive ("have a", "earned my") so it can't match
# unrelated constructions like "I have interest in..." or "I have a question
# about...". Checked only immediately before a degree_type/out_of_scope
# trigger phrase (see _has_preceding_possession_context) — this is a
# deterministic substring/proximity check, not a parser.
_POSSESSION_CONTEXT_PHRASES: frozenset[str] = frozenset({
    "already have a", "already have an",
    "i have a", "i have an",
    "currently hold a", "currently hold an",
    "hold a", "hold an",
    "earned a", "earned an", "earned my",
    "completed a", "completed an", "completed my",
    "received a", "received an", "received my",
    "graduated with a", "graduated with an",
})

# Max characters allowed between the end of a possession-context phrase and
# the start of the trigger phrase it suppresses — enough slack for an
# adjective ("a recent PhD") but tight enough that an unrelated "have"/
# "earned" elsewhere in a longer sentence can't suppress a distant,
# legitimate match.
_PRECEDING_CONTEXT_WINDOW = 25


def _has_preceding_possession_context(q: str, trigger_start: int) -> bool:
    """True if a possession/history phrase ends shortly before trigger_start,
    meaning the upcoming trigger phrase describes an existing credential
    rather than a stated goal."""
    for phrase in _POSSESSION_CONTEXT_PHRASES:
        idx = q.find(phrase)
        if idx == -1:
            continue
        gap = trigger_start - (idx + len(phrase))
        if 0 <= gap <= _PRECEDING_CONTEXT_WINDOW:
            return True
    return False

# Interest tags exclusive to DrPH (not present in DNP or DPT interest_tags).
# When ALL health interests fall within this set, the program is already
# distinguishable — health_undifferentiated should not fire.
_DRPH_EXCLUSIVE_INTERESTS: frozenset[str] = frozenset({
    "public_health", "global_health", "community_health",
    "health_policy", "health_informatics",
})

# Domain membership sets (taxonomy tags, not query keywords)
_HEALTH_CLINICAL_INTERESTS: frozenset[str] = frozenset({
    "nursing", "physical_therapy", "rehabilitation", "biomechanics",
    "patient_care", "mental_health", "pediatric_care", "gerontology",
})
_HEALTH_DOMAIN_INTERESTS: frozenset[str] = frozenset({
    "nursing", "physical_therapy", "rehabilitation", "biomechanics",
    "patient_care", "mental_health", "pediatric_care", "gerontology",
    "public_health", "global_health", "community_health",
    "health_policy", "health_informatics", "healthcare_leadership",
})
_HEALTH_BACKGROUNDS: frozenset[str] = frozenset({
    "nursing", "healthcare", "public_health", "biology",
})
_EDUCATION_DOMAIN_INTERESTS: frozenset[str] = frozenset({
    "education_leadership", "higher_education", "community_college",
    "student_affairs", "institutional_leadership",
    "k12_education", "school_reform", "education_policy", "curriculum_instruction",
})
_CC_SECTOR_INTERESTS: frozenset[str] = frozenset({
    "community_college", "higher_education", "student_affairs", "institutional_leadership",
})
_P12_SECTOR_INTERESTS: frozenset[str] = frozenset({
    "k12_education", "school_reform", "education_policy", "curriculum_instruction",
})
_ENGINEERING_INTERESTS: frozenset[str] = frozenset({
    "engineering", "computational_mathematics", "applied_mathematics",
})
_UNIQUE_CAREER_TAGS: frozenset[str] = frozenset({
    "physical_therapist", "nurse_practitioner",
    "public_health_leader", "policy_maker", "applied_researcher",
    "college_administrator", "school_administrator",
})
_HEALTH_CAREER_TAGS: frozenset[str] = frozenset({
    "nurse_practitioner", "physical_therapist",
    "public_health_leader", "policy_maker", "applied_researcher", "clinical_leader",
})


# ---------------------------------------------------------------------------
# Internal data type
# ---------------------------------------------------------------------------

@dataclass
class _SignalBundle:
    interests:          list[str]     = field(default_factory=list)
    career_goals:       list[str]     = field(default_factory=list)
    academic_bg:        list[str]     = field(default_factory=list)
    orientation:        Optional[str] = None
    degree_type:        Optional[str] = None
    out_of_scope:       Optional[str] = None   # redirect code, or None
    out_of_scope_phrase: Optional[str] = None  # literal matched phrase — observability only
    term_ambiguity:     Optional[str] = None   # "doctor" | "leadership" | "education"
    stated_uncertainty: bool          = False   # student expressed unsureness / exploration intent


# ---------------------------------------------------------------------------
# Signal extraction
# ---------------------------------------------------------------------------

def _sorted_phrases(m: dict[str, str]) -> list[tuple[str, str]]:
    return sorted(m.items(), key=lambda kv: len(kv[0]), reverse=True)


# Pre-sorted at module load — not rebuilt per call
_INTEREST_PHRASES    = _sorted_phrases(_INTEREST_MAP)
_CAREER_PHRASES      = _sorted_phrases(_CAREER_MAP)
_BACKGROUND_PHRASES  = _sorted_phrases(_BACKGROUND_MAP)
_ORIENTATION_PHRASES = _sorted_phrases(_ORIENTATION_MAP)
_DEGREE_PHRASES      = _sorted_phrases(_DEGREE_MAP)
_OOS_PHRASES         = _sorted_phrases(_OUT_OF_SCOPE_MAP)


def _multi_match(q: str, phrases: list[tuple[str, str]]) -> list[str]:
    """Return all distinct tags whose phrase appears in q (longest-first, deduped)."""
    seen: set[str] = set()
    result: list[str] = []
    for phrase, tag in phrases:
        if phrase in q and tag not in seen:
            result.append(tag)
            seen.add(tag)
    return result


def extract_signals(query: str) -> _SignalBundle:
    """
    Extract taxonomy-aligned signals from a single query.
    Signal extraction runs before guard evaluation — guards read the completed bundle.
    Phrase-first matching (longest phrase wins ties).
    """
    # Normalize curly quotes (smart-quote autocorrect in browsers/OSes) to ASCII
    # apostrophes so phrase maps like _OUT_OF_SCOPE_MAP match regardless of input source.
    q = query.lower().replace("’", "'").replace("‘", "'")
    bundle = _SignalBundle()

    # Step 1 — Out-of-scope (short-circuit: no further extraction needed)
    # Skipped when the phrase describes an already-held credential (e.g.
    # "I already have an undergraduate degree") rather than a request —
    # see _has_preceding_possession_context.
    for phrase, code in _OOS_PHRASES:
        idx = q.find(phrase)
        if idx != -1 and not _has_preceding_possession_context(q, idx):
            bundle.out_of_scope = code
            bundle.out_of_scope_phrase = phrase
            return bundle

    # Step 1.5 — Stated uncertainty (student explicitly signals unsureness or exploration)
    bundle.stated_uncertainty = any(p in q for p in _STATED_UNCERTAINTY_PHRASES)

    # Step 2 — Degree type (explicit; highest specificity signal)
    # Skipped when the phrase describes an already-held credential (e.g.
    # "I already have a PhD") rather than a stated goal.
    for phrase, dtype in _DEGREE_PHRASES:
        idx = q.find(phrase)
        if idx != -1 and not _has_preceding_possession_context(q, idx):
            bundle.degree_type = dtype
            break

    # Step 3 — Career goals (before interests: "physical therapist" is career + interest)
    bundle.career_goals = _multi_match(q, _CAREER_PHRASES)

    # Step 4 — Interest tags
    bundle.interests = _multi_match(q, _INTEREST_PHRASES)

    # Step 5 — Academic background
    bundle.academic_bg = _multi_match(q, _BACKGROUND_PHRASES)

    # Step 6 — Orientation
    for phrase, orient in _ORIENTATION_PHRASES:
        if phrase in q:
            bundle.orientation = orient
            break

    # Step 7 — Term ambiguity guards (run after extraction so context is available)
    _has_clinical_context = bool(
        bundle.career_goals or bundle.degree_type or
        set(bundle.interests) & _HEALTH_CLINICAL_INTERESTS
    )
    if any(p in q for p in _DOCTOR_PHRASES) and not _has_clinical_context:
        # "I want to be a doctor" without any clinical signal → MD disambiguation
        bundle.term_ambiguity = "doctor"
    elif "leadership" in q and not any(lq in q for lq in _LEADERSHIP_QUALIFIERS):
        # "leadership" alone without a domain qualifier → sector disambiguation
        bundle.term_ambiguity = "leadership"
    elif "education_leadership" in bundle.interests:
        # "educational leadership" extracted but no CC/P12 sector signal present
        if not (set(bundle.interests) & _CC_SECTOR_INTERESTS) and \
           not (set(bundle.interests) & _P12_SECTOR_INTERESTS):
            bundle.term_ambiguity = "education"

    return bundle


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def init_journey_state(session_id: str) -> JourneyState:
    return JourneyState(
        session_id=session_id,
        phase="init",
        turn_count=0,
        interests=[],
        academic_background=[],
        recommended_programs=[],
        delegated_routes=[],
    )


def _dedup_extend(base: list[str], additions: list[str]) -> list[str]:
    seen = set(base)
    return base + [x for x in additions if x not in seen]


def _update_state(state: JourneyState, bundle: _SignalBundle) -> JourneyState:
    """Return a new JourneyState with signals from bundle accumulated (non-mutating)."""
    updated: JourneyState = {
        **state,
        "interests":           _dedup_extend(state["interests"], bundle.interests),
        "academic_background": _dedup_extend(state["academic_background"], bundle.academic_bg),
        "career_goal_signals": _dedup_extend(
            state.get("career_goal_signals", []), bundle.career_goals
        ),
        "turn_count": state["turn_count"] + 1,
    }
    if bundle.orientation and not state.get("orientation"):
        updated["orientation"] = bundle.orientation
    if bundle.degree_type and not state.get("degree_type"):
        updated["degree_type"] = bundle.degree_type
    # stated_uncertainty is sticky: once a student signals unsureness, preserve it
    if bundle.stated_uncertainty and not state.get("stated_uncertainty"):
        updated["stated_uncertainty"] = True
    return updated


# ---------------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------------

def detect_gaps(state: JourneyState, bundle: _SignalBundle) -> list[str]:
    """
    Identify which signal types are missing from the accumulated state.
    bundle is needed only for term_ambiguity (extracted on the current turn).
    Returns a list of gap codes (order has no significance here; priority is
    applied in select_question()).
    """
    gaps: list[str] = []

    # Term ambiguity from the current query (highest-priority clarification need)
    if bundle.term_ambiguity:
        gaps.append(f"term_ambiguity_{bundle.term_ambiguity}")

    interests    = state["interests"]
    career_goals = state.get("career_goal_signals", [])
    background   = state["academic_background"]
    degree_type  = state.get("degree_type")
    orientation  = state.get("orientation")

    # No field signal at all (vague query with no taxonomy tags extracted)
    if not interests and not career_goals and not degree_type:
        health_bg = set(background) & _HEALTH_BACKGROUNDS
        # Clinical orientation or healthcare background with no program-specific
        # interest yet → ask a goal-oriented question before surfacing programs
        if orientation == "clinical" or health_bg:
            gaps.append("healthcare_goal_unclear")
        elif "education" in background:
            # Education background with no sector signal yet — same escape as
            # health_bg above, mirrored for the education domain
            gaps.append("education_undifferentiated")
        elif orientation:
            gaps.append("orientation_only")
        elif state.get("stated_uncertainty"):
            # Student explicitly said "not sure" / "exploring" — domain-first question
            gaps.append("domain_unclear")
        else:
            gaps.append("no_field_signal")
        return gaps  # no further analysis useful without any field signal

    # Education domain without CC vs. P-12 sector differentiation
    ed_interests = set(interests) & _EDUCATION_DOMAIN_INTERESTS
    if ed_interests:
        has_cc  = bool(set(interests) & _CC_SECTOR_INTERESTS)
        has_p12 = bool(set(interests) & _P12_SECTOR_INTERESTS)
        has_cc_career  = "college_administrator" in career_goals
        has_p12_career = "school_administrator" in career_goals
        if not has_cc and not has_p12 and not has_cc_career and not has_p12_career:
            gaps.append("education_undifferentiated")

    # Health domain with ≥2 interests but no role/career differentiator
    health_interests = set(interests) & _HEALTH_DOMAIN_INTERESTS
    has_health_career = bool(set(career_goals) & _HEALTH_CAREER_TAGS)
    if len(health_interests) >= 2 and not has_health_career:
        # If ALL health interests are DrPH-exclusive, the program is already
        # distinguishable — don't ask the user to choose further.
        if not (health_interests <= _DRPH_EXCLUSIVE_INTERESTS):
            gaps.append("health_undifferentiated")

    # Health background present but no specific health interest or career yet
    health_bg = set(background) & _HEALTH_BACKGROUNDS
    if health_bg and not health_interests and not has_health_career:
        gaps.append("health_undifferentiated")

    # Admission-gated programs (DNP/DPT) are likely candidates but background unknown.
    # Skip when a unique career tag is already present — it resolves the program
    # unambiguously and asking for background would be redundant friction.
    has_unique_career = bool(set(career_goals) & _UNIQUE_CAREER_TAGS)
    clinical_signals = bool(set(interests) & _HEALTH_CLINICAL_INTERESTS) or \
                       bool(set(career_goals) & {"physical_therapist", "nurse_practitioner", "clinical_leader"})
    if clinical_signals and not background and not has_unique_career:
        gaps.append("admission_gated")

    return gaps


# ---------------------------------------------------------------------------
# Clarification decision
# ---------------------------------------------------------------------------

_CLARIFY_GAPS: frozenset[str] = frozenset({
    "term_ambiguity_doctor",
    "term_ambiguity_leadership",
    "term_ambiguity_education",
    "no_field_signal",
    "domain_unclear",
    "orientation_only",
    "healthcare_goal_unclear",
    "education_undifferentiated",
    "health_undifferentiated",
    "admission_gated",
})


def should_clarify(state: JourneyState, gaps: list[str]) -> bool:
    """
    Return True if the agent should ask a clarifying question this turn.
    Returns False unconditionally when turn_count >= 3 (stopping rule).
    """
    if state["turn_count"] >= 3:
        return False
    return bool(set(gaps) & _CLARIFY_GAPS)


# ---------------------------------------------------------------------------
# Clarification question selection (Q1–Q5 priority order)
# ---------------------------------------------------------------------------

_CLARIFICATION_QUESTIONS: dict[str, str] = {
    "term_ambiguity_doctor": (
        "Are you interested in becoming a medical doctor (MD), or an advanced clinical "
        "doctoral degree such as a Doctor of Nursing Practice (DNP) or Doctor of Physical "
        "Therapy (DPT)? CSULB does not offer an MD program."
    ),
    "term_ambiguity_leadership": (
        "What sector are you looking to lead in — K-12 education, "
        "community college and higher education, or healthcare?"
    ),
    "term_ambiguity_education": (
        "Are you looking to lead in K-12 schools and districts, "
        "or in community college and higher education settings?"
    ),
    "education_undifferentiated": (
        "Are you looking to lead in K-12 schools and districts, "
        "or in community college and higher education settings?"
    ),
    "admission_gated": (
        "What is your current educational background and professional experience? "
        "For example, do you hold a nursing license (BSN/RN) or have pre-physical "
        "therapy coursework completed?"
    ),
    "healthcare_goal_unclear": (
        "What kind of role or impact are you hoping to have in healthcare? "
        "For example, are you interested in direct patient care, nursing leadership, "
        "public health, rehabilitation, or something else?"
    ),
    "health_undifferentiated": (
        "Are you looking for a program focused on academic or applied public health "
        "research, or clinical patient care practice?"
    ),
    "domain_unclear": (
        "Which area interests you most? CSULB doctoral programs span healthcare and patient "
        "care, education and leadership, public health and community impact, and research and "
        "engineering. Which sounds closest to what you're exploring?"
    ),
    "orientation_only": (
        "What field or area are you most drawn to studying or working in?"
    ),
    "no_field_signal": (
        "Tell me a bit about what you're drawn to — are you more interested in healthcare, "
        "education, public health, or research? Any starting point helps."
    ),
}

# Priority: disambiguation → background gate → domain-first → domain-specific → field
_QUESTION_PRIORITY: list[str] = [
    "term_ambiguity_doctor",
    "term_ambiguity_leadership",
    "term_ambiguity_education",
    "admission_gated",
    "domain_unclear",              # exploration entry point — ask broad domain before drilling in
    "healthcare_goal_unclear",     # goal-oriented before program-menu questions
    "health_undifferentiated",
    "education_undifferentiated",
    "orientation_only",
    "no_field_signal",
]


def select_question(gaps: list[str]) -> str:
    for gap_code in _QUESTION_PRIORITY:
        if gap_code in gaps:
            return _CLARIFICATION_QUESTIONS[gap_code]
    return _CLARIFICATION_QUESTIONS["no_field_signal"]


def _clarification_type(gaps: list[str]) -> str:
    """Return the gap code that determined which question select_question()
    asked. Mirrors select_question()'s own priority search — observability
    only, does not change which question is selected."""
    for gap_code in _QUESTION_PRIORITY:
        if gap_code in gaps:
            return gap_code
    return "no_field_signal"


# ---------------------------------------------------------------------------
# Behavior classification (Phase D hook)
# ---------------------------------------------------------------------------

def _classify_behavior(state: JourneyState) -> str:
    """
    Classify what Phase D should do with the accumulated signals.
    Phase C never scores programs — this sets the behavior code only.
    recommended_programs stays [] and confidence stays "none" until Phase D.
    """
    interests    = state["interests"]
    career_goals = state.get("career_goal_signals", [])
    degree_type  = state.get("degree_type")

    # Explicit degree or unique career tag → single program recommendation likely
    if degree_type:
        return "recommend"
    if any(t in _UNIQUE_CAREER_TAGS for t in career_goals):
        return "recommend"

    # Engineering interest only, no career signal → partial match only
    # (Engineering PhD has career_goal_tags=null in taxonomy)
    eng = set(interests) & _ENGINEERING_INTERESTS
    non_eng = set(interests) - eng
    if eng and not non_eng and not career_goals:
        return "partial_match_with_caveat"

    # Shared career tags (clinical_leader, university_educator) → multi-program
    if career_goals and not any(t in _UNIQUE_CAREER_TAGS for t in career_goals):
        return "multi_recommend"

    # Health domain interests without differentiating career → multi-program
    if set(interests) & _HEALTH_DOMAIN_INTERESTS and not career_goals:
        return "multi_recommend"

    # Education domain interests without sector or career → multi-program
    if set(interests) & _EDUCATION_DOMAIN_INTERESTS and not career_goals:
        return "multi_recommend"

    # Has some signal — let Phase D figure out exact match
    if interests or career_goals:
        return "recommend"

    return "partial_match_with_caveat"


# ---------------------------------------------------------------------------
# Response builder
# ---------------------------------------------------------------------------

_BEHAVIOR_SUMMARIES: dict[str, str] = {
    "clarify":                   "I need a bit more information to find the right program for you.",
    "redirect":                  "That's outside the scope of CSULB doctoral programs I can help with.",
    "partial_match_with_caveat": "I may have a potential match, but there are important caveats to flag.",
    "recommend":                 "I have enough signal to narrow down doctoral programs for you.",
    "multi_recommend":           "There are a few programs that could fit — let me surface them for you.",
}

_OUT_OF_SCOPE_MESSAGES: dict[str, str] = {
    "masters_level":     "My recommendations are strongest for CSULB doctoral programs right now. For master's programs, please review the CSULB Graduate Studies program directory at csulb.edu/graduate-studies. If you're open to doctoral programs, I can help you explore those.",
    "masters_business":  "The MBA is a master's-level program; I focus on doctoral programs. Visit the CSULB College of Business for MBA details.",
    "difficulty_framing":"I match programs based on your career goals and interests, not admission difficulty. Tell me about your goals.",
    "other_institution": "I can only help with CSULB programs. Please contact that institution's graduate admissions directly.",
    "medical_school":    "CSULB does not offer an MD program. If you are interested in an advanced clinical doctoral degree (DNP or DPT), I can help.",
    "undergrad":         "I focus on doctoral programs at CSULB. For undergraduate admissions, visit csulb.edu/admissions.",
    "unsupported_topic": "I don't have specific information on quantum computing or AI doctoral programs at CSULB. If you're interested in engineering or computational/mathematical research more broadly, I can help you explore the PhD in Engineering and Computational Mathematics.",
}


def _build_response(
    query: str,
    session_id: str,
    behavior_or_result,
    question: Optional[str] = None,
    out_of_scope_code: Optional[str] = None,
) -> DiscoveryResponse:
    # Accept either a plain behavior string (redirect/clarify paths) or a
    # Phase D _RecommendationResult (scoring paths).
    if isinstance(behavior_or_result, _RecommendationResult):
        result       = behavior_or_result
        behavior     = result.behavior
        question     = result.question
        rec_programs = result.recommended_programs
        confidence   = result.confidence
        prog_matches = result.program_matches
    else:
        behavior     = behavior_or_result
        rec_programs = []
        confidence   = "none"
        prog_matches = []

    summary = _BEHAVIOR_SUMMARIES.get(behavior, "")

    if behavior == "clarify":
        primary_action = question or "Can you tell me more about your career goals?"
        next_actions = [
            "Tell me your career goal",
            "What field interests you most?",
            "What degree type are you considering?",
        ]
    elif behavior == "redirect":
        primary_action = _OUT_OF_SCOPE_MESSAGES.get(
            out_of_scope_code or "", "I can only assist with CSULB doctoral programs."
        )
        next_actions = [
            "Tell me about DNP programs",
            "Tell me about DPT programs",
            "What doctoral programs does CSULB offer?",
        ]
    else:
        primary_action = "Program matching in progress — contact the program advisor to confirm fit."
        next_actions = [
            "Tell me more about your background",
            "What career do you want to pursue?",
            "Are you interested in research or clinical work?",
        ]

    extra: dict = {
        "recommended_programs": rec_programs,
        "confidence":           confidence,
        "behavior":             behavior,
    }
    if question:
        extra["clarification_question"] = question
    if prog_matches:
        extra["program_matches"] = prog_matches

    response: DiscoveryResponse = build_response(
        query=query,
        route="discovery",
        session_id=session_id,
        summary=summary,
        primary_action=primary_action,
        source={"file": "", "url": "https://www.csulb.edu/graduate-center"},
        next_actions=next_actions,
        extra=extra,
    )
    return response


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def handle_discovery(
    query: str,
    session_id: str,
    state: Optional[JourneyState] = None,
) -> tuple[DiscoveryResponse, JourneyState]:
    """
    Main entry point for the discovery route.

    Returns (DiscoveryResponse, updated_state).
    The updated state is also persisted via state.context_manager.save_context()
    so the orchestrator does not need to manage state directly.

    Phase C invariants:
      - recommended_programs=[] always
      - confidence="none" always
      - should_clarify() returns False when turn_count >= 3
    """
    # Restore or initialize state
    if state is None:
        state = get_context(session_id, default_factory=init_journey_state).journey_state

    # Step 1 — Extract signals (must happen before any guard evaluation)
    bundle = extract_signals(query)

    # Step 2 — Update accumulated state
    updated = _update_state(state, bundle)

    # Step 3 — Out-of-scope redirect (from current bundle, not accumulated state)
    if bundle.out_of_scope:
        updated["phase"] = "init"  # don't advance phase for out-of-scope queries
        emit("recommendation.redirect", level="INFO",
             redirect_reason="out_of_scope",
             redirect_type=bundle.out_of_scope,
             triggering_signal=bundle.out_of_scope_phrase or "")
        response = _build_response(
            query, session_id, "redirect", out_of_scope_code=bundle.out_of_scope
        )
        save_context(session_id, updated)
        return response, updated

    # Step 4 — Detect gaps
    gaps = detect_gaps(updated, bundle)

    # Step 5 — Clarify or proceed
    if should_clarify(updated, gaps):
        question = select_question(gaps)
        updated["phase"] = "clarifying"
        updated["last_question_asked"] = question
        emit("recommendation.clarify", level="INFO",
             gaps_considered=gaps,
             clarification_question=question,
             clarification_type=_clarification_type(gaps))
        response = _build_response(query, session_id, "clarify", question=question)
        save_context(session_id, updated)
        return response, updated

    # Step 6 — Phase D recommendation scoring
    result = select_recommendation(updated, gaps, _load_taxonomy())
    updated["phase"] = "recommending" if result.behavior != "clarify" else "clarifying"
    if result.program_matches:
        updated["recommended_programs"] = [m["program_id"] for m in result.program_matches]
    if result.behavior == "clarify" and not result.question:
        # Phase D's gap-override conditions weren't met (e.g. education_undifferentiated
        # with only a background match, no interest match) and it fell through to a
        # bare clarify with no question. Use the same domain-specific question Phase C
        # would have asked, instead of letting _build_response() fall back to the
        # generic "Can you tell me more about your career goals?" placeholder.
        result.question = select_question(gaps)
    if result.behavior == "clarify":
        # Phase D can also reach a clarify outcome (gap-override conditions not met) —
        # this event is the user-facing-question layer; recommendation.decision
        # (emitted inside select_recommendation()) is the scoring-layer explanation
        # for why no program was confident enough. Deliberately not duplicating
        # score/override details here.
        emit("recommendation.clarify", level="INFO",
             gaps_considered=gaps,
             clarification_question=result.question or "",
             clarification_type=_clarification_type(gaps))
    # Phase 7B: optional, additive LLM explanation — runs AFTER
    # select_recommendation() has produced its final, immutable
    # program_matches and BEFORE response assembly. Mutates each
    # ProgramMatch in place, adding only "explanation"; program_id,
    # confidence, score_basis, advisor_email, deadline_fall are untouched.
    # No-op when LLM_EXPLANATION_ENABLED=false (the default) or on any
    # generation failure — the deterministic recommendation is unaffected
    # either way.
    if result.program_matches:
        attach_explanations(result.program_matches)

    # Program-context continuity: a single confident recommendation becomes the
    # session's active program so later contextual follow-ups ("its deadline",
    # "how do I apply to it") resolve to it. Multiple/clarify outcomes do NOT
    # set an active program — we never arbitrarily pick one.
    if result.behavior == "recommend" and len(result.program_matches) == 1:
        from state.program_context import make_active_program
        _pid = result.program_matches[0].get("program_id", "")
        _cname = {p["program_id"]: p for p in _load_taxonomy()}.get(_pid, {}).get(
            "canonical_name", "")
        updated["active_program"] = make_active_program(
            _pid, _cname, source="recommendation")

    response = _build_response(query, session_id, result)
    save_context(session_id, updated)
    return response, updated
