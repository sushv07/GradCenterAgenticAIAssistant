"""Comparative analysis (Phase P9) — Track A (Pure RAG) vs Track B (Fine-Tuned).

Analysis-only: consumes the frozen Track A / Track B responses and reports and
derives a head-to-head comparison. Trains nothing, reruns no benchmark, and
changes no evaluation metric. All numbers are recomputed from existing outputs
through the UNMODIFIED evaluation pipeline (and verified to reproduce the frozen
reports exactly) so both tracks are scored on one identical code path.
"""
