"""
tools/__init__.py
Public API for the CSULB Grad Center tools layer (Phase 2).

Each tool is a thin, single-responsibility module that:
  - Wraps one data source (advisor data, RAG store, JSON fallback, or email)
  - Returns a consistent base schema: {found, tool, sources, error, ...}
  - Can be imported individually or via this package-level namespace

Typical usage:
    from tools import get_advisor, draft_email, build_outlook_url
    from tools import search_rag, get_deadlines, get_eligibility, get_application_steps

Tool modules:
    advisor_tool        — fuzzy advisor lookup via rapidfuzz
    email_tool          — email draft builder + Outlook deep-link generator
    rag_tool            — raw semantic search over the full vector store
    deadlines_tool      — deadline-scoped RAG retrieval
    eligibility_tool    — eligibility RAG + admissions.json fallback
    application_steps_tool — application process RAG + admissions.json fallback
"""

from tools.advisor_tool import get_advisor
from tools.email_tool import draft_email, build_outlook_url
from tools.rag_tool import search_rag
from tools.deadlines_tool import get_deadlines
from tools.eligibility_tool import get_eligibility
from tools.application_steps_tool import get_application_steps

__all__ = [
    "get_advisor",
    "draft_email",
    "build_outlook_url",
    "search_rag",
    "get_deadlines",
    "get_eligibility",
    "get_application_steps",
]
