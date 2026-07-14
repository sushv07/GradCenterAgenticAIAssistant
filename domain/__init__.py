"""
domain/
Engine-independent domain models for the Grad Center assistant.

Packages under domain/ hold canonical, retrieval-neutral data models and their
deterministic validation. They depend only on the Python standard library and
Pydantic — never on RAG, Chroma, embeddings, inference, FastAPI, Streamlit, or
the experiment package — so they are reusable in another repository unchanged.

Current members:
    domain.programs — CanonicalProgram (masters | doctoral | certificate | other)

Reserved for future siblings (not implemented here):
    domain.recommendation, domain.advisors
"""
