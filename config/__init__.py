"""
config — centralized configuration.

  settings.py — plain Python constants for deployment-sensitive values
                (embedding model, Chroma path/TTL, retrieval defaults,
                taxonomy path, log path, a couple of reused thresholds).
                Domain vocabulary, routing signal phrases, and
                recommendation weights are NOT here — see settings.py's
                module docstring for why they stay in code.
"""
