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
