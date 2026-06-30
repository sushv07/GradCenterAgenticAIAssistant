"""
obs/request_trace.py
Phase 8E — end-to-end request trace reconstruction.

Reads logs/gradcenter.log (NDJSON — see gradcenter_logging.py), groups
every event by request_id, and reconstructs one RequestTrace per request:
what query came in, what route it resolved to, which stages ran
(routing / retrieval / recommendation / llm / retry / tool / error), how
long each took, and what the final outcome was. Pure log-reading — never
calls into routing, retrieval, recommendation, or LLM code, and never
changes what any of those layers do or return.

Why this is reconstruction, not new instrumentation:
    Every stage already logs structured events (Phase 2F's
    recommendation.*, Phase 7B/7C's llm.*, Phase 8B's retrieval.*, the
    long-standing route.decision/tool.result/advisor.match/keyword.*).
    The only genuine gap the Phase 8E audit found was request-level
    bookends with reliable request_id/session_id/route coverage for EVERY
    caller (see backend/entrypoint.py's "Phase 8E" docstring section for
    the two specific gaps fixed: api/app.py never minted a request_id at
    all, and discovery-continuation turns never emitted route.decision).
    Everything else in this module is pure aggregation over events that
    already existed.

Event → stage mapping (Step 3): prefix-matched against the part of the
event name before its first ".":

    request    → request   (request.started / request.completed,
                             and app.py's pre-existing request.start /
                             request.complete)
    route      → routing   (route.decision)
    retrieval  → retrieval (retrieval.started/.vector_search/.filtering/
                             .completed/.failed/.result — rag/retriever.py)
    keyword    → retrieval (keyword.retrieval/.result — the "answer"
                             route's non-vector retrieval path)
    faq_rag    → retrieval (retrieval/faq_rag_module.py)
    advisor    → retrieval (advisor.match — fuzzy-match lookup is a form
                             of retrieval against the advisor directory)
    tool       → tool      (tool.result — deadlines/eligibility/
                             application_steps tools)
    recommendation → recommendation (score/rejected/decision/clarify/redirect)
    llm        → llm       (llm.synthesis.* and llm.explanation.* — both
                             land in the same stage; "kind" distinguishes
                             them within the stage, see _llm_summary())
    retry      → retry     (retry.attempt/.success/.exhausted — also
                             cross-referenced into whichever stage the
                             retried operation belongs to, via the
                             operation field's prefix, e.g.
                             "llm_synthesis.ollama_post" → llm)
    store      → infrastructure (rag/store.py, faq_rag_module.py vector
                             store build/validation — can fire outside any
                             request context, e.g. at first-ever access)
    taxonomy   → error      (taxonomy.load_failed)
    backend    → error      (backend.unhandled_exception)

Unrecognized event prefixes fall into "other" rather than being dropped —
silent data loss in a trace is worse than an imprecise bucket name.

What is intentionally excluded from a RequestTrace (Step 2):
    - Full retrieved chunk text — never logged by any event in the first
      place (Phase 8B's explicit non-goal), so there is nothing to
      include or exclude here; the trace only ever sees chunk_ids/scores.
    - Full user conversation history — JourneyState/ConversationContext
      are never logged either; a trace reflects ONE request's events only.
    - Raw LLM prompt/response text — llm.* events log model/confidence/
      elapsed_ms/error, never prompt or generated content.

How this differs from OpenTelemetry / LangSmith (explicit non-goal):
    No spans, no exporters, no distributed context propagation across
    process/network boundaries, no external service. This is a single-
    process, single-log-file batch reconstruction tool you run after the
    fact against logs/gradcenter.log — see ARCHITECTURE_ANALYSIS.md's
    Phase 8E section for the future path to a real tracing backend should
    one ever be adopted (the request_id/session_id ContextVar plumbing
    already in place is what such a migration would build on).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config.settings import LOG_FILE


# ---------------------------------------------------------------------------
# Event → stage mapping
# ---------------------------------------------------------------------------

_PREFIX_TO_STAGE: dict[str, str] = {
    "request":        "request",
    "route":          "routing",
    "retrieval":      "retrieval",
    "keyword":        "retrieval",
    "faq_rag":        "retrieval",
    "advisor":        "retrieval",
    "tool":           "tool",
    "recommendation": "recommendation",
    "llm":            "llm",
    "retry":          "retry",
    "store":          "infrastructure",
    "taxonomy":       "error",
    "backend":        "error",
}


def stage_for_event(event_name: str) -> str:
    """Map a raw event name (e.g. "retrieval.completed") to its trace
    stage (e.g. "retrieval"), via the prefix before the first '.'.
    Unrecognized prefixes map to "other" rather than raising — a trace
    should never lose an event just because its name is unfamiliar."""
    prefix = event_name.split(".", 1)[0]
    return _PREFIX_TO_STAGE.get(prefix, "other")


# ---------------------------------------------------------------------------
# Trace model (Step 2)
# ---------------------------------------------------------------------------

@dataclass
class RequestTrace:
    request_id:        str
    session_id:         str = ""
    query:               str = ""
    route:               Optional[str] = None
    final_behavior:      Optional[str] = None
    started_at:          Optional[str] = None
    completed_at:        Optional[str] = None
    total_elapsed_ms:    Optional[float] = None
    stages:              dict[str, list[dict]] = field(default_factory=dict)
    errors:              list[dict] = field(default_factory=list)
    fallbacks:           list[dict] = field(default_factory=list)
    retrieval_summary:   dict = field(default_factory=dict)
    recommendation_summary: dict = field(default_factory=dict)
    llm_summary:          dict = field(default_factory=dict)
    event_count:          int = 0


# ---------------------------------------------------------------------------
# Log reading
# ---------------------------------------------------------------------------

def _read_all_events(log_path: Path) -> list[dict]:
    """Read every parseable NDJSON line. Malformed lines are skipped, not
    raised on — this is a read-only reporting tool over a log file that
    could in principle contain a hand-edited or truncated line."""
    if not log_path.exists():
        return []
    events: list[dict] = []
    with log_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def group_events_by_request_id(events: list[dict]) -> dict[str, list[dict]]:
    """
    Group events by request_id, preserving log (chronological) order
    within each group. Events with request_id == "" (or missing) are
    grouped together under the "" key — these are events emitted outside
    any request context, e.g. rag/store.py's lazy first-build of the
    vector store at import time, or a caller that never set one.
    """
    groups: dict[str, list[dict]] = {}
    for event in events:
        rid = event.get("request_id", "") or ""
        groups.setdefault(rid, []).append(event)
    return groups


# ---------------------------------------------------------------------------
# Per-stage summaries
# ---------------------------------------------------------------------------

def _retrieval_summary(events: list[dict]) -> dict:
    """Summarize whatever retrieval.* events are present for one request —
    deliberately tolerant of a partial set (e.g. only retrieval.failed, no
    .started, for a request whose vector store was unavailable)."""
    completed = [e for e in events if e.get("event") == "retrieval.completed"]
    failed     = [e for e in events if e.get("event") == "retrieval.failed"]
    legacy     = [e for e in events if e.get("event") == "retrieval.result"]

    summary: dict = {
        "ran":              bool(completed or failed or legacy),
        "completed_count":  len(completed),
        "failed_count":      len(failed),
    }
    if completed:
        last = completed[-1]
        summary["returned_count"] = last.get("returned_count")
        summary["top_score"]      = last.get("top_score")
        summary["chunk_ids"]      = last.get("chunk_ids", [])
    if failed:
        summary["failure_reasons"] = [e.get("reason", "unknown") for e in failed]
    return summary


def _recommendation_summary(events: list[dict]) -> dict:
    decisions = [e for e in events if e.get("event") == "recommendation.decision"]
    clarifies = [e for e in events if e.get("event") == "recommendation.clarify"]
    redirects = [e for e in events if e.get("event") == "recommendation.redirect"]

    summary: dict = {
        "ran": bool(decisions or clarifies or redirects),
    }
    if decisions:
        last = decisions[-1]
        summary["behavior"]             = last.get("behavior")
        summary["confidence"]           = last.get("confidence")
        summary["recommended_programs"] = last.get("recommended_programs", [])
    elif clarifies:
        summary["behavior"]              = "clarify"
        summary["clarification_question"] = clarifies[-1].get("clarification_question", "")
    elif redirects:
        summary["behavior"]      = "redirect"
        summary["redirect_reason"] = redirects[-1].get("redirect_reason", "")
    return summary


def _llm_summary(events: list[dict]) -> dict:
    synthesis_events   = [e for e in events if e.get("event", "").startswith("llm.synthesis.")]
    explanation_events = [e for e in events if e.get("event", "").startswith("llm.explanation.")]

    summary: dict = {
        "synthesis_ran":   bool(synthesis_events),
        "explanation_ran": bool(explanation_events),
    }
    synth_result = next((e for e in synthesis_events if e.get("event") == "llm.synthesis.result"), None)
    if synth_result:
        summary["synthesis_confidence"] = synth_result.get("confidence")
        summary["synthesis_elapsed_ms"] = synth_result.get("elapsed_ms")
    if any(e.get("event") == "llm.synthesis.error" for e in synthesis_events):
        summary["synthesis_fell_back"] = True

    explanation_result = next(
        (e for e in explanation_events if e.get("event") == "llm.explanation.result"), None
    )
    if explanation_result:
        summary["explanation_elapsed_ms"] = explanation_result.get("elapsed_ms")
    if any(e.get("event") == "llm.explanation.error" for e in explanation_events):
        summary["explanation_fell_back"] = True

    return summary


# ---------------------------------------------------------------------------
# Trace assembly (Step 4)
# ---------------------------------------------------------------------------

def _infer_route(events: list[dict], stages: dict[str, list[dict]]) -> Optional[str]:
    """Prefer request.completed's route (most authoritative — set from the
    real response, covers every caller including discovery-continuation
    turns that never emit route.decision). Falls back to the most recent
    route.decision, then to "discovery" if recommendation events ran with
    no routing event at all (the exact gap request.completed now closes
    going forward; this fallback only matters for log data captured
    before this phase)."""
    completions = [e for e in events if e.get("event") == "request.completed"]
    if completions and completions[-1].get("route"):
        return completions[-1]["route"]

    decisions = [e for e in events if e.get("event") == "route.decision"]
    if decisions:
        return decisions[-1].get("route")

    if stages.get("recommendation"):
        return "discovery"
    return None


def _infer_query(events: list[dict]) -> str:
    for e in events:
        if e.get("event") in ("request.started", "request.start") and e.get("query"):
            return e["query"]
    for e in events:
        if e.get("event") == "retrieval.started" and e.get("query"):
            return e["query"]
    return ""


def _infer_session_id(events: list[dict]) -> str:
    for e in events:
        sid = e.get("session_id")
        if sid:
            return sid
    return ""


def build_trace(request_id: str, events: list[dict]) -> RequestTrace:
    """Reconstruct one RequestTrace from every event sharing one
    request_id, in the order they were logged."""
    stages: dict[str, list[dict]] = {}
    for e in events:
        stage = stage_for_event(e.get("event", ""))
        stages.setdefault(stage, []).append(e)

    errors    = [e for e in events if e.get("level") == "ERROR"]
    fallbacks = [
        e for e in events
        if e.get("event") in (
            "llm.synthesis.error", "llm.explanation.error",
            "retry.exhausted", "retrieval.failed",
        )
    ]

    timestamps = [e["ts"] for e in events if e.get("ts")]
    started_at   = min(timestamps) if timestamps else None
    completed_at = max(timestamps) if timestamps else None

    completions = [e for e in events if e.get("event") in ("request.completed", "request.complete")]
    total_elapsed_ms = completions[-1].get("elapsed_ms") if completions else None

    final_behavior = None
    rec_summary = _recommendation_summary(stages.get("recommendation", []))
    if rec_summary.get("ran"):
        final_behavior = rec_summary.get("behavior")

    return RequestTrace(
        request_id=request_id,
        session_id=_infer_session_id(events),
        query=_infer_query(events),
        route=_infer_route(events, stages),
        final_behavior=final_behavior,
        started_at=started_at,
        completed_at=completed_at,
        total_elapsed_ms=total_elapsed_ms,
        stages=stages,
        errors=errors,
        fallbacks=fallbacks,
        retrieval_summary=_retrieval_summary(stages.get("retrieval", [])),
        recommendation_summary=rec_summary,
        llm_summary=_llm_summary(stages.get("llm", [])),
        event_count=len(events),
    )


def reconstruct_traces(log_path: Optional[Path] = None, include_empty_request_id: bool = False) -> list[RequestTrace]:
    """
    Read log_path (default: the live logs/gradcenter.log) and reconstruct
    one RequestTrace per distinct request_id found.

    include_empty_request_id: when False (default), the "" group — events
    emitted with no active request_id, e.g. infrastructure events at
    import time, or any caller that never set one — is excluded from the
    returned list. Pass True to include it as a single trace whose
    request_id is "".
    """
    log_path = log_path or LOG_FILE
    events = _read_all_events(log_path)
    groups = group_events_by_request_id(events)

    traces: list[RequestTrace] = []
    for rid, group_events in groups.items():
        if rid == "" and not include_empty_request_id:
            continue
        traces.append(build_trace(rid, group_events))
    return traces
