"""
agents/recommendation_explainer.py
Phase 7B — LLM-generated explanations for deterministic recommendations.

Phase 7A established the rule this module exists to enforce: the LLM
explains, it never decides. agents/recommendation_engine.py remains the
single source of truth for which programs are recommended, at what
confidence, and why (score_basis) — this module's only job is turning an
ALREADY-FINAL, ALREADY-COMPUTED ProgramMatch into a natural-language
sentence. It cannot change which programs are recommended, their order,
their confidence, or their score_basis — it only ever ADDS an optional
"explanation" string field alongside them.

Disabled by default (LLM_EXPLANATION_ENABLED=false) — a separate flag from
agents/llm_synthesizer.py's LLM_SYNTHESIS_ENABLED, deliberately, so an
operator can enable one feature without the other.

Pipeline position (Phase 7B Step 1 audit):
    Journey Agent (extract signals)
        -> Recommendation Engine (select_recommendation() — deterministic,
           final, immutable ProgramMatch list)
        -> THIS MODULE (attach_explanations(), optional, additive only)
        -> Response Builder (responses.builder.build_response())
        -> API response

    This is the only safe insertion point: anything earlier (inside
    recommendation_engine.py) would mean an LLM call could influence
    scoring; anything later (inside responses/builder.py) would mean
    duplicating per-route logic that belongs to the recommendation domain,
    not the generic response-assembly layer.

What this module receives (Phase 7B Step 2):
    Only a ProgramMatch dict (program_id, confidence, score_basis, ...) and
    a read-only taxonomy lookup (agents.recommendation_engine._load_taxonomy(),
    for the program's display name and degree type — descriptive metadata,
    not new evidence). It does NOT receive raw user conversation history,
    JourneyState, or anything not already part of the deterministic
    recommendation's own output. score_basis strings are parsed into
    matched_degree / matched_career_goals / matched_interests /
    matched_background / orientation_match — exactly the breakdown
    compute_program_score() already computed; nothing is re-derived or
    guessed. orientation_mismatch entries are deliberately excluded from
    the evidence handed to the LLM — a mismatch is a scoring penalty, not
    "why this program fits," and explaining unfit-by-design as if it were
    supporting evidence would be misleading.

Public API
----------
    attach_explanations(program_matches: list[ProgramMatch]) -> None
        Mutates program_matches in place, adding "explanation" to each
        entry where generation succeeds. Never raises. Never alters any
        other field. No-op entirely when disabled.

Observability
-------------
    llm.explanation.start  — emitted before the Ollama call
    llm.explanation.result — emitted on success
    llm.explanation.error  — emitted on any failure (network, validation, etc.)
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

import requests

from gradcenter_logging import emit
from utils.retry import retry_call
from contracts.response_types import ProgramMatch
from agents.recommendation_engine import _load_taxonomy
from prompts.loader import load_prompt


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_ENABLED  = os.getenv("LLM_EXPLANATION_ENABLED", "false").lower() == "true"
_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
_MODEL    = os.getenv("LLM_SYNTHESIS_MODEL", "qwen2.5:7b-instruct")
_TIMEOUT  = int(os.getenv("LLM_SYNTHESIS_TIMEOUT_S", "30"))

_CHAT_URL = f"{_BASE_URL}/api/chat"


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------
# Phase 7E: extracted to prompts/recommendation/explanation_v1.md — wording
# unchanged (verified byte-identical at extraction time). Loading is cached
# (prompts/loader.py), so this module-level read costs nothing beyond the
# first import.

_SYSTEM_PROMPT = load_prompt("recommendation_explanation")


# ---------------------------------------------------------------------------
# score_basis parsing — derives evidence categories from the recommendation
# engine's own output strings, without touching recommendation_engine.py
# ---------------------------------------------------------------------------

def _parse_score_basis(score_basis: list[str]) -> dict:
    """
    Parse compute_program_score()'s score_basis strings (e.g.
    "unique_career:nurse_practitioner", "interest_1:nursing",
    "background_2plus:nursing,clinical_rn_experience",
    "orientation_match:research") into categorized evidence.

    orientation_mismatch entries are intentionally dropped — see module
    docstring.
    """
    evidence = {
        "matched_degree":       False,
        "matched_career_goals": [],
        "matched_interests":    [],
        "matched_background":   [],
        "orientation_match":    False,
    }
    for entry in score_basis:
        if entry == "degree_type":
            evidence["matched_degree"] = True
        elif entry.startswith("unique_career:") or entry.startswith("shared_career:"):
            evidence["matched_career_goals"].append(entry.split(":", 1)[1])
        elif (
            entry.startswith("interests_3plus:")
            or entry.startswith("interests_2:")
            or entry.startswith("interest_1:")
        ):
            tags = entry.split(":", 1)[1].split(",")
            evidence["matched_interests"].extend(t for t in tags if t)
        elif entry.startswith("background_2plus:") or entry.startswith("background_1:"):
            tags = entry.split(":", 1)[1].split(",")
            evidence["matched_background"].extend(t for t in tags if t)
        elif entry.startswith("orientation_match:"):
            evidence["orientation_match"] = True
        # orientation_mismatch:* — deliberately not collected as evidence
    return evidence


def _has_any_evidence(evidence: dict) -> bool:
    return (
        evidence["matched_degree"]
        or evidence["matched_career_goals"]
        or evidence["matched_interests"]
        or evidence["matched_background"]
        or evidence["orientation_match"]
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def attach_explanations(program_matches: list[ProgramMatch]) -> None:
    """
    Mutate program_matches in place, adding "explanation" to each entry
    where generation succeeds. No-op entirely when disabled. Never raises —
    any failure for one program simply leaves that entry without an
    "explanation" key, exactly as if this function had never been called.
    """
    if not _ENABLED or not program_matches:
        return

    taxonomy_by_id = {p.get("program_id", ""): p for p in _load_taxonomy()}

    for match in program_matches:
        explanation = _generate_explanation(match, taxonomy_by_id.get(match.get("program_id", "")))
        if explanation is not None:
            match["explanation"] = explanation


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _generate_explanation(match: ProgramMatch, program: Optional[dict]) -> Optional[str]:
    """Returns the explanation string on success, None on any failure or
    when there's no evidence to explain — never raises."""
    evidence = _parse_score_basis(match.get("score_basis") or [])
    if not _has_any_evidence(evidence):
        return None

    program_id = match.get("program_id", "")
    emit("llm.explanation.start", model=_MODEL, program_id=program_id)
    t0 = time.monotonic()

    try:
        content = _call_ollama(match, program, evidence)
    except Exception as exc:
        emit("llm.explanation.error", level="ERROR",
             model=_MODEL, program_id=program_id, error=str(exc))
        return None

    result = _validate(content)
    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)

    if result is None:
        emit("llm.explanation.error", level="WARNING",
             model=_MODEL, program_id=program_id, error="response validation failed")
        return None

    emit("llm.explanation.result",
         model=_MODEL, program_id=program_id, elapsed_ms=elapsed_ms)
    return result


def _call_ollama(match: ProgramMatch, program: Optional[dict], evidence: dict) -> str:
    """
    POST to Ollama /api/chat and return the raw content string.

    Raises on any HTTP or network failure — caller is responsible for
    catching. Connection/timeout failures are retried via
    utils.retry.retry_call before giving up.
    """
    program_name = (program or {}).get("canonical_name", match.get("program_id", ""))
    degree_type  = (program or {}).get("degree_type", "")

    user_payload = {
        "program_name":         program_name,
        "degree_type":          degree_type,
        "confidence":           match.get("confidence", ""),
        "matched_degree":       evidence["matched_degree"],
        "matched_career_goals": evidence["matched_career_goals"],
        "matched_interests":    evidence["matched_interests"],
        "matched_background":   evidence["matched_background"],
        "orientation_match":    evidence["orientation_match"],
    }

    payload = {
        "model":    _MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "format":  "json",
        "stream":  False,
        "options": {"temperature": 0},
    }

    def _post() -> requests.Response:
        resp = requests.post(_CHAT_URL, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp

    resp = retry_call(_post, operation="llm_explanation.ollama_post")
    return resp.json().get("message", {}).get("content", "")


def _validate(content: str) -> Optional[str]:
    """Parse and validate the model response. Pure — no emit calls."""
    if not content or not content.strip():
        return None

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None

    explanation = parsed.get("explanation", "")
    if not isinstance(explanation, str) or not explanation.strip():
        return None

    return explanation.strip()
