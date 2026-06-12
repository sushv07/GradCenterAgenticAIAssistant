"""router.py — backward-compatibility shim. Real module: routing/router.py"""
from routing.router import *  # noqa: F401, F403
from routing.router import Route, RouteDecision, decide_route, detect_route  # explicit for IDEs/type-checkers
