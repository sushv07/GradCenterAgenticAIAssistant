"""
tools/__init__.py
Package marker for the CSULB Grad Center tools layer.

Import each tool directly from its module — do not add eager imports here.
Eager imports of rag_tool / deadlines_tool / eligibility_tool / application_steps_tool
pull in rag.store → langchain_community at import time, which breaks the
lightweight Streamlit Cloud environment that does not install LangChain/Chroma.

Direct import pattern (use this everywhere):
    from tools.program_interest_tool import generate_program_specific_response
    from tools.advisor_tool import get_advisor
    from tools.email_tool import draft_email, build_outlook_url
    from tools.rag_tool import search_rag          # backend only
    from tools.deadlines_tool import get_deadlines  # backend only
    from tools.eligibility_tool import get_eligibility  # backend only
    from tools.application_steps_tool import get_application_steps  # backend only
"""
