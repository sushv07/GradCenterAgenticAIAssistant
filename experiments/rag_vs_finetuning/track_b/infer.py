"""
experiments/rag_vs_finetuning/track_b/infer.py
Official Track B inference on the frozen benchmark (Phase P8.2).

Runs the FINE-TUNED model (frozen 4-bit base + official P8.1 LoRA adapter) on all
84 frozen benchmark questions and writes one response record per case. Retrieval
is COMPLETELY disabled: no Chroma, no embeddings, retrieved_chunk_ids == [] and
citation_chunk_ids == []. Deterministic greedy decoding, fixed seed, identical
prompt template for every question. This is the ONLY place the adapter touches
the benchmark.

MLX runs on Apple Silicon under the CommandLineTools Python 3.9 interpreter, so
this module is intentionally self-contained: standard library + mlx_lm only (no
pydantic, no repo imports). The repo's Python-3.13 evaluator (track_b/evaluate.py)
reads the JSONL this produces. Run from the repo root:

  /Library/Developer/CommandLineTools/usr/bin/python3 \
      experiments/rag_vs_finetuning/track_b/infer.py
"""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import mlx.core as mx
from mlx_lm import load
from mlx_lm.generate import generate
from mlx_lm.sample_utils import make_sampler

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "experiments/rag_vs_finetuning/data"
BENCHMARK = DATA / "evaluation/eval_dataset.json"
ADAPTER = REPO / "experiments/rag_vs_finetuning/artifacts/adapters/track_b_selected"
RESULTS = DATA / "evaluation/results/track_b_responses.jsonl"

BASE_MODEL = "mlx-community/Qwen2.5-7B-Instruct-4bit"
# Official selected adapter from Phase P8.1 (iter-40, lowest validation loss).
EXPECTED_ADAPTER_SHA = (
    "sha256:a2a0908612b0e9c6b960f1470af19fa304415b892db8059d7c25ea2b8e390345")

# The system prompt the model was fine-tuned with (training/models.SYSTEM_PROMPT),
# kept byte-identical so inference matches training. Track B has no retrieval, so
# the user turn is the bare question — the model must answer from fine-tuned
# parametric knowledge alone.
SYSTEM_PROMPT = (
    "You are the CSULB Graduate Center assistant. Answer using only the Graduate "
    "Center program data. If the data does not contain the answer, say you don't "
    "have enough information. Never fabricate facts; preserve published wording.")
PROMPT_VERSION = "track_b_sft_v1"

# Deterministic decoding: temperature 0 / greedy (mirrors Track A's temp-0 setting).
# max_tokens is capped at 256 — generous for the short factual answers in the
# benchmark, and a runtime bound for on-device MLX generation. Answers stop at the
# model's EOS token well before this in normal cases.
SEED = 42
MAX_TOKENS = 256

# Abstention detector. The runner's abstained() keys on the insufficient_evidence
# flag OR a fixed phrase list; the fine-tuned refusal ("I don't have enough
# information in the provided Graduate Center data to answer that.") is NOT in that
# phrase list, so we must set the flag here. These patterns capture the trained
# refusal and its close paraphrases without matching substantive answers.
_REFUSAL_PATTERNS = (
    "don't have enough information",
    "do not have enough information",
    "don't have that information",
    "do not have that information",
    "don't have enough data",
    "not enough information",
    "no information available",
    "not in the provided",
    "cannot answer",
    "can't answer",
    "unable to answer",
    "i don't have access",
)


def is_refusal(answer: str) -> bool:
    low = answer.lower()
    return any(p in low for p in _REFUSAL_PATTERNS)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    adapter_sha = _sha256(ADAPTER / "adapters.safetensors")
    if adapter_sha != EXPECTED_ADAPTER_SHA:
        raise SystemExit(
            f"ABORT: adapter checksum mismatch\n  expected {EXPECTED_ADAPTER_SHA}"
            f"\n  found    {adapter_sha}")
    print(f"[track-b] adapter checksum OK: {adapter_sha[:23]}…")

    dataset = json.loads(BENCHMARK.read_text("utf-8"))
    cases = dataset["cases"]
    print(f"[track-b] benchmark cases: {len(cases)} "
          f"(checksum {dataset['dataset_checksum'][:23]}…)")

    mx.random.seed(SEED)
    model, tokenizer = load(BASE_MODEL, adapter_path=str(ADAPTER))
    sampler = make_sampler(temp=0.0)  # greedy / deterministic
    print(f"[track-b] loaded {BASE_MODEL} + adapter; generating…")

    now = datetime.now(timezone.utc).isoformat()
    versions = {"base_model": BASE_MODEL, "adapter_checksum": adapter_sha,
                "prompt_version": PROMPT_VERSION, "mlx_lm": "0.29.1",
                "decoding": "greedy(temp=0)", "max_tokens": MAX_TOKENS, "seed": SEED}
    records = []
    for i, case in enumerate(cases, 1):
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": case["question"]}]
        prompt = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=False)
        t0 = time.time()
        answer = generate(model, tokenizer, prompt=prompt,
                          max_tokens=MAX_TOKENS, sampler=sampler, verbose=False)
        gen_ms = round((time.time() - t0) * 1000, 3)
        answer = answer.strip()
        records.append({
            "question_id": case["id"], "question": case["question"],
            "category": case["category"], "program": case["program"],
            "answerable": case["answerable"], "source_missing": case["source_missing"],
            "model": "qwen2.5-7b-instruct-4bit+track_b_lora",
            "prompt_version": PROMPT_VERSION,
            "answer": answer,
            "insufficient_evidence": is_refusal(answer),
            # Retrieval is disabled for Track B — always empty.
            "retrieved_chunk_ids": [], "citation_chunk_ids": [],
            "similarity_scores": [],
            "retrieval_latency_ms": 0.0, "generation_latency_ms": gen_ms,
            "total_latency_ms": gen_ms, "answer_char_count": len(answer),
            "timestamp": now, "versions": versions,
            "track": "track_b_finetuned_no_rag"})
        print(f"[track-b] {i:>2}/{len(cases)} {case['id']} "
              f"{gen_ms:>8.0f}ms refusal={records[-1]['insufficient_evidence']}")

    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True)
             for r in sorted(records, key=lambda r: r["question_id"])]
    RESULTS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[track-b] wrote {len(records)} responses -> {RESULTS}")


if __name__ == "__main__":
    main()
