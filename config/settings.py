"""
config/settings.py
Phase 5A — centralized configuration.

Problem this solves:
    Deployment-sensitive values — the embedding model name, the Chroma
    persistence path, retrieval defaults, the taxonomy file path, the log
    file path — were hardcoded as module-level constants scattered across
    rag/store.py, rag/retriever.py, rag/chunking.py,
    retrieval/faq_rag_module.py, agents/recommendation_engine.py, and
    gradcenter_logging.py. Changing any of them for a different environment
    meant editing multiple files instead of one.

What belongs here vs. what doesn't (Step 2 classification):
    MOVED — stable, deployment-sensitive, or reused-across-modules values:
        embedding model/device/normalization, Chroma path/collection/TTL,
        retrieval min_relevance/top_k, chunk size/overlap, the FAQ store's
        separate TTL, the taxonomy file path, the log file path, the
        default session_id string, the advisor "strong match" threshold.

    NOT MOVED, deliberately:
        - Recommendation weights (agents/recommendation_engine.py) — these
          are a tightly-coupled algorithm tuning surface with their own
          dedicated sensitivity-analysis tooling (evals/weight_validation.py,
          evals/experimental_scoring.py). Moving them to a generic config
          module would duplicate, not replace, that tooling, and the Phase
          5A non-goals explicitly say not to touch scoring values.
        - Routing signal phrases and journey_agent's interest/career maps
          (routing/router.py, agents/journey_agent.py) — domain vocabulary,
          not deployment config. Externalizing it here would make it
          harder, not easier, to read alongside the matching logic that
          uses it.
        - The 3-turn discovery stopping rule (turn_count >= 3) — a business
          rule that's easier to verify correct sitting next to
          should_clarify()'s docstring than as a disconnected number in a
          settings file.
        - Tool-specific min_score/k defaults in deadlines_tool.py /
          eligibility_tool.py / rag_tool.py — these are NOT the same value
          duplicated for no reason: deadlines_tool.py deliberately uses
          min_score=0.25 while the others use 0.30. Centralizing them would
          risk silently homogenizing intentionally different tuned values.

Why plain constants, not Pydantic/YAML:
    This is a single-process app with one deployment target today — there's
    no multi-environment config-file-selection problem to solve yet. Plain
    module constants are what the rest of this codebase already uses
    (EMBEDDING_MODEL, CHUNK_SIZE, MIN_RELEVANCE, etc. were all plain
    UPPER_CASE constants before this phase); matching that convention here
    keeps this a true "move," not a redesign. No environment-variable
    overrides are added either — that would start to be "environment-
    specific deployment logic," which is explicitly out of scope for this
    phase. See the Phase 5A report's "Remaining Configuration Work" for
    where that would go later.
"""
from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent


def _env_flag(name: str, default: bool) -> bool:
    """Read a boolean feature flag from the environment.

    Absent → the given default. Present → truthy iff one of the common
    affirmative spellings; anything else (including "0"/"false"/"") is False.
    Kept tiny and dependency-free to match this module's plain-constant style.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    """Read an int config value from the environment; falls back to default on
    absence or an unparseable value (never raises at import time)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    """Read a float config value from the environment; falls back to default on
    absence or an unparseable value."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    """Read a string config value from the environment; blank/absent → default."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


# ---------------------------------------------------------------------------
# Retrieval / RAG configuration
# ---------------------------------------------------------------------------

EMBEDDING_MODEL     = "all-MiniLM-L6-v2"
EMBEDDING_DEVICE    = "cpu"
EMBEDDING_NORMALIZE = True

CHROMA_DIR             = _PROJECT_ROOT / "chroma_db"
CHROMA_COLLECTION_NAME = "csulb_grad_center"
CHROMA_STORE_TTL_SECONDS = 86_400   # 24 hours — rag/store.py's persistent store

# retrieval/faq_rag_module.py's separate, smaller in-memory store. Kept as
# its own value (not merged with CHROMA_STORE_TTL_SECONDS) because the two
# stores are deliberately on different rebuild cycles.
FAQ_VECTORSTORE_TTL_SECONDS = 3_600  # 1 hour

RETRIEVAL_MIN_RELEVANCE = 0.30
RETRIEVAL_DEFAULT_TOP_K = 3

CHUNK_SIZE    = 500
CHUNK_OVERLAP = 75


# ---------------------------------------------------------------------------
# Domain data paths
# ---------------------------------------------------------------------------

PROGRAM_TAXONOMY_PATH = _PROJECT_ROOT / "data" / "program_taxonomy.json"

# Phase 7E — root directory for versioned LLM prompt assets (see prompts/).
PROMPTS_DIR = _PROJECT_ROOT / "prompts"


# ---------------------------------------------------------------------------
# Logging / observability configuration
# ---------------------------------------------------------------------------

LOGGER_NAME = "gradcenter"
LOG_DIR     = _PROJECT_ROOT / "logs"
LOG_FILE    = LOG_DIR / "gradcenter.log"


# ---------------------------------------------------------------------------
# Application configuration
# ---------------------------------------------------------------------------

DEFAULT_SESSION_ID = "default"

# Shared by orchestrator.py's advisor response wording and
# retrieval/advisor_retrieval.py's CLI formatter — both independently
# hardcoded the same partial_ratio cutoff for "Strong match" vs "Good match".
ADVISOR_STRONG_MATCH_THRESHOLD = 90


# ---------------------------------------------------------------------------
# Retry configuration (Phase 6B)
# ---------------------------------------------------------------------------
# Used only by utils/retry.py, and only for the handful of external HTTP
# calls in the live request path that the Phase 6B retry audit classified
# as "safe to retry" (transient connection/timeout failures where a retry
# has a realistic chance of succeeding) — see ARCHITECTURE_ANALYSIS.md's
# Phase 6B section for the full classification. Deterministic logic
# (routing, recommendation scoring, taxonomy loading) never reads these.

RETRY_MAX_ATTEMPTS       = 3     # 1 initial attempt + 2 retries
RETRY_BASE_DELAY_SECONDS = 0.5   # exponential backoff: 0.5s, 1.0s, ...


# ---------------------------------------------------------------------------
# Multi-Agent Coordinator (Version 2 — additive, optional orchestration layer)
# ---------------------------------------------------------------------------
# The coordinator (coordination/) is an OPTIONAL layer that activates only when
# BOTH this flag is on AND an incoming request is composite (multiple intents in
# one message). Default False → production behavior is byte-for-byte identical
# to the existing single-intent orchestration; the coordinator is never reached.
# Overridable per-deployment via the ENABLE_MULTI_AGENT_COORDINATOR env var
# without a code change. See coordination/coordinator.py.
ENABLE_MULTI_AGENT_COORDINATOR = _env_flag("ENABLE_MULTI_AGENT_COORDINATOR", False)


# ---------------------------------------------------------------------------
# Phase 4 — Grounded FAQ Conversational Synthesis (additive, flag-gated)
# ---------------------------------------------------------------------------
# All flags default to OFF / current behavior, so with none set the assistant
# behaves byte-for-byte as it does today: no FAQ synthesis, no supporting-page
# crawl. These constants are declared here in Phase 4.0 and are intentionally
# NOT yet read by any runtime path — later Phase 4 steps wire them in. Env vars
# allow per-deployment tuning without a code change. See docs/AI_OBSERVABILITY.md
# and the Phase 4 plan.

# Master gate for the answer-workflow FAQ synthesis path (Phase 4.3). Off → the
# answer route behaves exactly as today (keyword retrieve + optional synthesis).
FAQ_SYNTHESIS_ENABLED = _env_flag("FAQ_SYNTHESIS_ENABLED", False)

# Gate for depth-1 supporting-page ingestion (Phase 4.2). Off → only atomic FAQ
# entries are ingested; no linked pages are crawled.
FAQ_CRAWL_SUPPORTING = _env_flag("FAQ_CRAWL_SUPPORTING", False)

# Retrieval breadth for FAQ synthesis — a little wider than the topic tools so a
# grounded answer can combine several FAQs / a FAQ plus its supporting page.
FAQ_TOP_K = _env_int("FAQ_TOP_K", 6)

# Minimum cosine relevance for FAQ retrieval. Matches the global retriever
# default (RETRIEVAL_MIN_RELEVANCE = 0.30) so FAQ behaves consistently.
FAQ_MIN_SCORE = _env_float("FAQ_MIN_SCORE", 0.30)

# Upper bound on the characters of retrieved evidence packed into the synthesis
# prompt — caps prompt size / latency for multi-source answers.
FAQ_CONTEXT_MAX_CHARS = _env_int("FAQ_CONTEXT_MAX_CHARS", 6000)

# Supporting-page crawl guardrails (Phase 4.2). Depth is a hard cap of 1 by
# design; the allowlist confines crawling to the university domain.
FAQ_CRAWL_DEPTH = _env_int("FAQ_CRAWL_DEPTH", 1)
FAQ_DOMAIN_ALLOWLIST = _env_str("FAQ_DOMAIN_ALLOWLIST", "csulb.edu")
