"""
experiments/rag_vs_finetuning/track_a/smoke_questions.py
A tiny DEVELOPMENT-only question set for debugging the Track A pipeline.

This is NOT the evaluation dataset (that is built in a later phase). These are
obvious diagnostic questions only.
"""
from __future__ import annotations

DEV_QUESTIONS: tuple[str, ...] = (
    "What is the application deadline for Accountancy?",
    "Who should I contact for Social Work?",
    "What is the International Affairs program about?",
    "Is the Accountancy program STEM designated?",
)
