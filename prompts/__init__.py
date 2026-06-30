"""
prompts — versioned LLM prompt assets.

Problem this solves:
    Before Phase 7E, both LLM-touching modules (agents/recommendation_explainer.py,
    agents/llm_synthesizer.py) embedded their system prompt as a Python
    string literal. Changing prompt wording meant editing the same file as
    the grounding/validation/retry business logic, with no version history
    distinct from code changes and no way for an eval report to say which
    prompt version produced a given result.

What this package does:
    Prompt text lives in plain .md files, one per prompt version, organized
    by feature (recommendation/, grounded_answers/). registry.py maps a
    short logical name ("recommendation_explanation",
    "grounded_answer_synthesis") to a PromptMetadata record (name, version,
    description, intended_model, file path). loader.py reads and caches
    the file content by name.

What this package deliberately does NOT do (Phase 7E non-goals):
    - No frontmatter parsing, no YAML, no template engine — a prompt file
      is just its raw text, nothing more. Metadata lives in Python
      (registry.py), not embedded in the files, so loading a prompt never
      requires parsing anything beyond "read this file."
    - No external prompt management platform, no LangSmith prompt hub, no
      PromptLayer, no DSPy, no semantic prompt search, no automatic
      prompt tuning. This is a versioned-file convention, not a service.
    - No registry persistence beyond this Python module — "version
      tracking" means "a new file with a new version suffix and a new
      registry entry," not a database.

  registry.py — PromptMetadata records, keyed by logical prompt name.
  loader.py   — load_prompt(name) -> str (cached), get_prompt_metadata(name).
"""
