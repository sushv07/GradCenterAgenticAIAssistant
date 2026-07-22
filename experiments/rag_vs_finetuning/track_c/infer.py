"""
experiments/rag_vs_finetuning/track_c/infer.py
Track C hybrid inference harness (Phase P10) — runs on the 3.9 MLX interpreter.

Pipeline: question -> (subprocess) frozen Track A retrieval -> grounded prompt ->
frozen 4-bit base + official Track B LoRA adapter -> grounded answer + citations.
Retrieved context is the authoritative knowledge source; the adapter only shapes
behaviour (P9 finding). Returns the ResponseRecord schema shared with Tracks A/B.

Standard library + mlx_lm only (chromadb is not importable here); retrieval is
obtained by invoking track_c/retrieve.py under the 3.13 interpreter. This module
does NOT run the benchmark and computes NO metrics (that is Phase P11).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import mlx.core as mx
from mlx_lm import load
from mlx_lm.generate import generate
from mlx_lm.sample_utils import make_sampler

from experiments.rag_vs_finetuning.track_c import prompt_builder as pb

REPO = Path(__file__).resolve().parents[3]
ADAPTER = REPO / "experiments/rag_vs_finetuning/artifacts/adapters/track_b_selected"
BASE_MODEL = "mlx-community/Qwen2.5-7B-Instruct-4bit"
# Official Track B selected adapter (iter-40) from Phase P8.1 — reused unchanged.
EXPECTED_ADAPTER_SHA = (
    "sha256:a2a0908612b0e9c6b960f1470af19fa304415b892db8059d7c25ea2b8e390345")

# Interpreter that has chromadb/sentence-transformers (retrieval stage).
RETRIEVER_PYTHON = os.environ.get(
    "TRACK_C_RETRIEVER_PYTHON", "/opt/miniconda3/bin/python3")

SEED = 42
MAX_TOKENS = 256
MODEL_NAME = "qwen2.5-7b-instruct-4bit+track_b_lora"
TRACK = "track_c_hybrid"


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def retrieve_via_subprocess(question: str, *, top_k: int | None = None,
                            threshold: float | None = None) -> dict:
    """Invoke the frozen Track A retrieval stage in the 3.13 interpreter."""
    cmd = [RETRIEVER_PYTHON, "-m",
           "experiments.rag_vs_finetuning.track_c.retrieve", "--question", question]
    if top_k is not None:
        cmd += ["--top-k", str(top_k)]
    if threshold is not None:
        cmd += ["--threshold", str(threshold)]
    proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"retrieval failed ({RETRIEVER_PYTHON}):\n{proc.stderr[-2000:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TrackCModel:
    """Loads the base + official Track B adapter once; generates grounded answers."""

    def __init__(self) -> None:
        adapter_sha = _sha256(ADAPTER / "adapters.safetensors")
        if adapter_sha != EXPECTED_ADAPTER_SHA:
            raise SystemExit(
                f"ABORT: adapter checksum mismatch\n  expected {EXPECTED_ADAPTER_SHA}"
                f"\n  found    {adapter_sha}")
        self.adapter_checksum = adapter_sha
        mx.random.seed(SEED)
        self.model, self.tokenizer = load(BASE_MODEL, adapter_path=str(ADAPTER))
        self.sampler = make_sampler(temp=0.0)  # deterministic greedy

    def generate_grounded(self, bundle: dict) -> dict:
        """bundle: output of retrieve_context/retrieve_via_subprocess."""
        question = bundle["question"]
        chunks = bundle.get("chunks", [])
        retrieved_ids = bundle.get("retrieved_chunk_ids", [])
        now = datetime.now(timezone.utc).isoformat()
        versions = {"base_model": BASE_MODEL, "adapter_checksum": self.adapter_checksum,
                    "prompt_version": pb.PROMPT_VERSION, "retrieval_version":
                    bundle.get("retrieval_version"), "embedding_model":
                    bundle.get("embedding_model"), "decoding": "greedy(temp=0)",
                    "max_tokens": MAX_TOKENS, "seed": SEED}

        # Grounding failure mode (mirrors Track A): no evidence -> refuse, no model call.
        if not chunks:
            ans = pb.INSUFFICIENT_ANSWER
            return self._record(question, bundle, ans, insufficient=True,
                                citations=[], gen_ms=0.0, versions=versions,
                                now=now, model_called=False)

        messages = pb.build_messages(question, chunks)
        prompt = self.tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False)
        t0 = time.time()
        ans = generate(self.model, self.tokenizer, prompt=prompt,
                       max_tokens=MAX_TOKENS, sampler=self.sampler, verbose=False).strip()
        gen_ms = round((time.time() - t0) * 1000, 3)
        insufficient = pb.is_insufficient(ans)
        citations = pb.select_citations(ans, retrieved_ids, insufficient=insufficient)
        return self._record(question, bundle, ans, insufficient=insufficient,
                            citations=citations, gen_ms=gen_ms, versions=versions,
                            now=now, model_called=True)

    def _record(self, question, bundle, answer, *, insufficient, citations,
                gen_ms, versions, now, model_called) -> dict:
        return {
            "question": question, "answer": answer,
            "insufficient_evidence": insufficient,
            "retrieved_chunk_ids": bundle.get("retrieved_chunk_ids", []),
            "citation_chunk_ids": citations,
            "similarity_scores": bundle.get("similarity_scores", []),
            "retrieval_latency_ms": bundle.get("retrieval_latency_ms", 0.0),
            "generation_latency_ms": gen_ms,
            "answer_char_count": len(answer),
            "model": MODEL_NAME, "prompt_version": pb.PROMPT_VERSION,
            "model_called": model_called, "track": TRACK,
            "timestamp": now, "versions": versions,
        }

    def answer_question(self, question: str, *, top_k=None, threshold=None) -> dict:
        bundle = retrieve_via_subprocess(question, top_k=top_k, threshold=threshold)
        return self.generate_grounded(bundle)


def run_bundle_file(bundle_path: Path) -> list[dict]:
    """Batch path for a precomputed retrieval bundle (used by Phase P11)."""
    model = TrackCModel()
    out = []
    for line in Path(bundle_path).read_text("utf-8").splitlines():
        if line.strip():
            out.append(model.generate_grounded(json.loads(line)))
    return out


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "Who should I contact for Social Work?"
    m = TrackCModel()
    rec = m.answer_question(q)
    print(json.dumps(rec, ensure_ascii=False, indent=2))
