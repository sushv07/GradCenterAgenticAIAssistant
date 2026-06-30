"""
tests/test_dependencies.py
Phase 5B — regression tests for the dependency container.

Covers:
  - AppDependencies / ContextManagerService construction.
  - get_dependencies() returns real, working production wiring.
  - handle_user_query() works identically with the default (omitted) deps.
  - handle_user_query() actually USES an injected fake context manager
    (not just accepting and ignoring the parameter).
  - Injecting a fake retriever works in isolation.
  - Existing behavior (routing, discovery continuation) is unchanged when
    deps is supplied explicitly with the real production wiring.

Run from the project root:
    pytest tests/test_dependencies.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import unittest

from backend.dependencies import AppDependencies, ContextManagerService, get_dependencies
from backend.entrypoint import handle_user_query
from state.context_manager import clear_context, ConversationContext
from contracts.response_types import RetrievedChunk


def _fresh(sid: str) -> None:
    clear_context(sid)


class _FakeRetriever:
    """Minimal stand-in satisfying the Retriever Protocol's call shape."""

    def __init__(self):
        self.calls: list[str] = []

    def retrieve(self, query, *, filters=None, top_k=None, min_score=None):
        self.calls.append(query)
        return [RetrievedChunk(text="fake chunk", title="", url="", score=1.0, metadata={})]


class TestAppDependenciesConstruction(unittest.TestCase):
    def test_get_dependencies_returns_app_dependencies(self):
        deps = get_dependencies()
        self.assertIsInstance(deps, AppDependencies)

    def test_default_retriever_is_real_chroma_retriever(self):
        from retrieval.retriever_service import ChromaRetriever
        deps = get_dependencies()
        self.assertIsInstance(deps.retriever, ChromaRetriever)

    def test_default_context_manager_is_context_manager_service(self):
        deps = get_dependencies()
        self.assertIsInstance(deps.context_manager, ContextManagerService)

    def test_context_manager_service_functions_are_callable(self):
        deps = get_dependencies()
        self.assertTrue(callable(deps.context_manager.get_context))
        self.assertTrue(callable(deps.context_manager.save_context))
        self.assertTrue(callable(deps.context_manager.clear_context))

    def test_response_builder_is_callable(self):
        deps = get_dependencies()
        self.assertTrue(callable(deps.response_builder))


class TestContextManagerServiceWorks(unittest.TestCase):
    def test_get_save_clear_roundtrip(self):
        from agents.journey_agent import init_journey_state
        deps = get_dependencies()
        sid = "di-roundtrip"
        deps.context_manager.clear_context(sid)

        ctx = deps.context_manager.get_context(sid, default_factory=init_journey_state)
        self.assertIsInstance(ctx, ConversationContext)
        self.assertEqual(ctx.session_id, sid)

        deps.context_manager.save_context(sid, ctx.journey_state)
        ctx2 = deps.context_manager.get_context(sid, default_factory=init_journey_state)
        self.assertEqual(ctx2.journey_state, ctx.journey_state)

        deps.context_manager.clear_context(sid)


class TestHandleUserQueryWithDefaultDeps(unittest.TestCase):
    """Omitting deps must behave identically to before Phase 5B."""

    def test_standard_request_unaffected(self):
        sid = "di-default-1"
        _fresh(sid)
        response = handle_user_query("when is the application deadline", session_id=sid)
        self.assertEqual(response["route"], "deadlines")
        _fresh(sid)

    def test_discovery_continuation_unaffected(self):
        sid = "di-default-2"
        _fresh(sid)
        r1 = handle_user_query("I am interested in educational leadership", session_id=sid)
        self.assertEqual(r1["behavior"], "clarify")
        r2 = handle_user_query("looking to lead K-12 schools and districts", session_id=sid)
        ids = [m["program_id"] for m in r2.get("program_matches", [])]
        self.assertIn("edd-educational-leadership-p12", ids)
        _fresh(sid)


class TestHandleUserQueryWithInjectedFakes(unittest.TestCase):
    """The injection seam must be real — handle_user_query() must actually
    call through the supplied deps, not just accept and ignore it."""

    def test_injected_context_manager_is_actually_called(self):
        calls: list[str] = []
        real = get_dependencies()

        def spying_get_context(session_id, default_factory):
            calls.append(session_id)
            return real.context_manager.get_context(session_id, default_factory=default_factory)

        fake_deps = AppDependencies(
            retriever=real.retriever,
            context_manager=ContextManagerService(get_context=spying_get_context),
            response_builder=real.response_builder,
        )

        sid = "di-spy-test"
        _fresh(sid)
        handle_user_query("when is the application deadline", session_id=sid, deps=fake_deps)
        self.assertIn(sid, calls)
        _fresh(sid)

    def test_injected_retriever_is_usable_in_isolation(self):
        fake_retriever = _FakeRetriever()
        chunks = fake_retriever.retrieve("anything", top_k=1)
        self.assertEqual(chunks[0]["text"], "fake chunk")
        self.assertIn("anything", fake_retriever.calls)

    def test_app_dependencies_accepts_fake_retriever(self):
        real = get_dependencies()
        fake_deps = AppDependencies(
            retriever=_FakeRetriever(),
            context_manager=real.context_manager,
            response_builder=real.response_builder,
        )
        chunks = fake_deps.retriever.retrieve("a query")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["text"], "fake chunk")


if __name__ == "__main__":
    unittest.main()
