"""
test_handle_query.py
Manual test script for handle_query() covering all routing paths.

Run:
    python test_handle_query.py
"""

from advisor_retrieval import handle_query

queries = [
    "I want to apply for a PhD",
    "I don't know where to start",
    "dnp advisor",
    "public health doctorate advisor",
    "help me apply",
    "who should I contact",
]

SEP = "=" * 60

print(SEP)
print("  handle_query() — Test Suite")
print(SEP)

for i, query in enumerate(queries, start=1):
    print(f"\n[{i}] Query: {query!r}\n")
    print(handle_query(query))
    print(f"\n{SEP}")
