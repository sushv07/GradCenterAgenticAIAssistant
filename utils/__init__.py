"""
utils — small, dependency-free cross-cutting helpers.

  retry.py — retry_call(), a tiny retry wrapper for the handful of
             external HTTP calls in the live request path that can fail
             transiently. Not a general-purpose retry framework — see
             retry.py's module docstring for what it deliberately doesn't do.
"""
