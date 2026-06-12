"""next_steps.py — backward-compatibility shim. Real module: agents/next_steps.py

IMPORTANT: get_next_steps and format_next_steps are re-exported by name (not just
via star-import) so that patch("next_steps.get_next_steps") in test_router.py and
test_golden_routes.py continues to resolve to this module's attribute.
"""
from agents.next_steps import *  # noqa: F401, F403
from agents.next_steps import get_next_steps, format_next_steps  # explicit for mock patch
