"""
experiments/rag_vs_finetuning/track_a/trace.py
Persist Track A run traces (Phase P7).

Traces are model-dependent run outputs (the future evaluation input). They are
written to a git-ignored location — the committed reproducible artifacts remain
the frozen corpus, projection, chunks, and manifests, not volatile LLM outputs.
"""
from __future__ import annotations

import json
from pathlib import Path

from experiments.rag_vs_finetuning.track_a.models import RunTrace

DEFAULT_TRACES_PATH = Path(
    "experiments/rag_vs_finetuning/data/traces/track_a_traces.jsonl")


def persist_trace(trace: RunTrace, traces_path: Path = DEFAULT_TRACES_PATH) -> None:
    traces_path = Path(traces_path)
    traces_path.parent.mkdir(parents=True, exist_ok=True)
    with traces_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(trace.model_dump(mode="json"), ensure_ascii=False) + "\n")


def load_traces(traces_path: Path = DEFAULT_TRACES_PATH) -> list[RunTrace]:
    traces_path = Path(traces_path)
    if not traces_path.exists():
        return []
    return [RunTrace.model_validate_json(l)
            for l in traces_path.read_text("utf-8").splitlines() if l.strip()]
