"""
coordination/ — the Multi-Agent Coordinator (Version 2).

An OPTIONAL, additive orchestration layer that sits beside — never replaces —
the existing single-intent orchestration. It activates only when the
ENABLE_MULTI_AGENT_COORDINATOR flag is on AND an incoming request is composite
(carries several intents in one message, e.g. "recommend a program, tell me the
advisor, and explain how an international student applies").

Design invariants (see the Phase 1 architecture notes):
  * No existing workflow business logic is modified or duplicated. Each agent
    adapter (agents/*_agent.py) wraps an existing capability.
  * Deterministic throughout — detection, planning, execution ordering, and
    synthesis. No LLM decides the plan; no autonomous planning.
  * Backwards compatible — with the flag off, this package is never reached and
    the production request path is unchanged.
"""
