"""
test_queries.py
Realistic messy query test loop for the CSULB Graduate Advisor AI Assistant.

Run:
    python test_queries.py
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).parent.parent))


from retrieval.advisor_retrieval import handle_query

# ---------------------------------------------------------------------------
# Test queries
# ---------------------------------------------------------------------------

# Easy — clear intent, minor variation
easy = [
    "dnp",
    "physical therapy",
    "aerospace engineering",
    "accountancy",
]

# Medium — messy phrasing, abbreviations, mixed intent
medium = [
    "anthro",
    "who do I contact for nursing",
    "I want to apply for applied anthropology, who is the advisor",
    "accounting masters program advisor",
    "aero grad program",
]

# Hard — vague, ambiguous, or completely invalid
hard = [
    "AI program",
    "business masters",
    "asdfghjkl",
]

test_queries = easy + medium + hard

# ---------------------------------------------------------------------------
# Labels for display
# ---------------------------------------------------------------------------

labels = (
    ["[Easy]"] * len(easy)
    + ["[Medium]"] * len(medium)
    + ["[Hard]"] * len(hard)
)

# ---------------------------------------------------------------------------
# Test loop
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  CSULB Graduate Advisor — Query Test Suite")
    print("=" * 60)
    print()

    for label, query in zip(labels, test_queries):
        print(f"{label} User: {query!r}")
        print(handle_query(query))
        print("-" * 60)
        print()
