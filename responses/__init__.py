"""
responses — shared backend Response Builder.

  builder.py — single function that assembles the common response envelope
               (query/route/session_id/summary/primary_action/source/
               next_actions) used by every route; callers merge in their
               own route-specific fields via `extra`.
"""
