"""
journey_state.py
Mutable session state for the Student Interest Journey Agent.

JourneyState accumulates interest signals across turns and drives the
discovery → recommendation flow.  It is NOT a response contract — it is
the agent's working memory for a single student session.

Phase model
──────────────────────────────────────────────────────────────────────
  "init"          → session just started; no signals collected
  "collecting"    → agent is gathering signals via clarifying questions
  "recommending"  → enough signal collected; recommendation surfaced
  "clarifying"    → signals present but ambiguous; follow-up question asked

Controlled vocabularies (mirrored from program_taxonomy.json)
──────────────────────────────────────────────────────────────────────
  orientation   : "research" | "professional" | "applied" | "clinical"
  degree_type   : "PhD" | "EdD" | "DNP" | "DPT" | "DrPH"
  modality_pref : "online" | "in_person" | "hybrid"

interests, academic_background, recommended_programs, delegated_routes
  use tag/id strings from the taxonomy — never free-form values.
"""
from __future__ import annotations

from typing import TypedDict


# ---------------------------------------------------------------------------
# Active program — the single canonical program context for the session
# ---------------------------------------------------------------------------

class ActiveProgram(TypedDict, total=False):
    """The one program the conversation is currently 'about'.

    Set whenever a program is confidently identified (explicit mention, single
    recommendation, clarification selection, or a confident route result) and
    read to resolve later contextual references ("this program", "it", …). A
    single canonical field — routes must NOT introduce their own program-state
    fields.
    """
    program_id:      str   # stable taxonomy id, e.g. "drph-public-health" ("" if unknown)
    canonical_name:  str   # taxonomy canonical_name, e.g. "Public Health"
    tool_name:       str   # the name the route tools understand, e.g. "Public Health (DR.P.H.)"
    source:          str   # "explicit_mention" | "recommendation" | "clarification_selection" | "route_result"


# ---------------------------------------------------------------------------
# Pending clarification — a resumable question the assistant is waiting on
# ---------------------------------------------------------------------------

class PendingClarification(TypedDict, total=False):
    """A clarification the assistant asked and is waiting for a reply to.

    Generic and reusable: `kind` selects the resumer that consumes the user's
    next reply (see state/clarification.py's registry); the other fields carry
    the context needed to resume the original request. A new clarification type
    is added by registering a resumer for a new `kind` and setting this one
    field — never a per-type boolean or a parallel resume path.
    """
    kind:           str   # e.g. "applicant_type"
    route:          str   # the route to resume after the reply, e.g. "application"
    question:       str   # the question shown to the user
    original_query: str   # the request that triggered the clarification


# ---------------------------------------------------------------------------
# Required fields — must be set when creating a new JourneyState
# ---------------------------------------------------------------------------

class _JourneyStateRequired(TypedDict):
    session_id:           str        # mirrors session_id from orchestrator.run()
    phase:                str        # "init" | "collecting" | "recommending" | "clarifying"
    turn_count:           int        # turns elapsed in this session (0-indexed)
    interests:            list[str]  # extracted interest tags (taxonomy vocabulary)
    academic_background:  list[str]  # extracted background tags (taxonomy vocabulary)
    recommended_programs: list[str]  # program_ids from program_taxonomy.json
    delegated_routes:     list[str]  # routes already delegated, e.g. ["advisor", "deadlines"]


# ---------------------------------------------------------------------------
# Optional domain signals — populated as the conversation reveals them
# ---------------------------------------------------------------------------

class JourneyState(_JourneyStateRequired, total=False):
    orientation:          str        # "research" | "professional" | "applied" | "clinical"
    degree_type:          str        # "PhD" | "EdD" | "DNP" | "DPT" | "DrPH"
    career_goal_signals:  list[str]  # extracted career_goal_tags (taxonomy vocabulary)
    work_experience:      str        # free-text or extracted tag, e.g. "clinical_rn_experience"
    funding_priority:     bool       # True when student has signalled funding is a concern
    modality_pref:        str        # "online" | "in_person" | "hybrid"
    last_question_asked:  str        # last clarification question sent to the student
    stated_uncertainty:   bool       # True when student explicitly signalled unsureness ("not sure", "exploring")
    active_program:       ActiveProgram  # single canonical program context for pronoun/generic follow-ups
    applicant_type:       str            # "domestic" | "international" | "" — one canonical field
    pending_clarification: PendingClarification  # a resumable clarification awaiting the user's reply
