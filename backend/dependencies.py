"""
backend/dependencies.py
Phase 5B — lightweight dependency container.

Problem this solves:
    backend/entrypoint.py imports its runtime dependencies directly —
    `import orchestrator`, `from state.context_manager import get_context`
    — which is fine for a single production wiring, but means a test or a
    future FastAPI handler that wants a fake Retriever or a fake context
    store has no seam to substitute one without monkeypatching module
    globals.

What this module does:
    AppDependencies bundles the handful of components that are genuinely
    swappable — Retriever (already a Protocol as of Phase 4B, built for
    exactly this), the Context Manager's three functions (bundled into one
    ContextManagerService so callers hold one reference instead of three
    separate imports), and the Response Builder. get_dependencies()
    constructs the real, production AppDependencies; tests can construct
    their own AppDependencies with fakes instead.

What this module deliberately does NOT do (Phase 5B non-goals):
    - It is not a DI framework or container library — no registration,
      no auto-wiring, no decorators. AppDependencies is a plain dataclass;
      get_dependencies() is a plain function.
    - It does not wrap orchestrator.run(), the router, the recommendation
      engine, or rag/store.py's internals. Those are deterministic
      algorithm modules / already one layer below an existing abstraction
      (Retriever) — wrapping them again here would be unjustified
      indirection, not a real swap point. See the Phase 5B output report's
      classification for the reasoning per dependency.
    - It does not change any function's existing required parameters —
      everywhere it's used, the dependency container is an additive,
      optional argument with a default that reproduces today's behavior
      exactly.

Usage:
    from backend.dependencies import get_dependencies, AppDependencies

    deps = get_dependencies()                       # real production wiring
    deps.context_manager.get_context(session_id, default_factory=...)
    deps.retriever.retrieve(query, top_k=3)
    deps.response_builder(route=..., summary=..., ...)

    # In a test:
    fake_deps = AppDependencies(
        retriever=FakeRetriever(),
        context_manager=ContextManagerService(),
        response_builder=build_response,
    )
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from retrieval.retriever_service import Retriever, ChromaRetriever
from state.context_manager import get_context, save_context, clear_context
from responses.builder import build_response


# ---------------------------------------------------------------------------
# Context Manager service wrapper
# ---------------------------------------------------------------------------

@dataclass
class ContextManagerService:
    """
    Bundles state.context_manager's three free functions into one
    injectable unit. Not a new abstraction over them — same functions, same
    signatures — just one object to hold and pass instead of three imports.
    """
    get_context:   Callable = get_context
    save_context:  Callable = save_context
    clear_context: Callable = clear_context


# ---------------------------------------------------------------------------
# Dependency container
# ---------------------------------------------------------------------------

@dataclass
class AppDependencies:
    """
    The backend's swappable runtime dependencies.

    retriever:        Retriever Protocol implementation (Phase 4B). The
                       clearest "should inject now" candidate — already
                       abstracted specifically so backends can be swapped.
    context_manager:  ContextManagerService — get_context/save_context/
                       clear_context bundled as one unit.
    response_builder: responses.builder.build_response — included for
                       parity with the other two; it's a pure function with
                       nothing to swap today, but giving it a slot here
                       means a future caller (a test capturing every built
                       response, a FastAPI layer wanting a different
                       envelope shape) has one place to override it.
    """
    retriever:        Retriever
    context_manager:  ContextManagerService
    response_builder: Callable = build_response


def get_dependencies() -> AppDependencies:
    """
    Construct the default, production AppDependencies.

    Call this once at the backend entry point; pass a different
    AppDependencies instance (e.g. with a fake retriever) to override it in
    tests.
    """
    return AppDependencies(
        retriever=ChromaRetriever(),
        context_manager=ContextManagerService(),
        response_builder=build_response,
    )
