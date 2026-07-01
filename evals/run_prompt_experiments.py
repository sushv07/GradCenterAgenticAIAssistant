#!/usr/bin/env python3
"""
evals/run_prompt_experiments.py
Phase 8C — offline prompt experimentation framework.

Compares a baseline prompt against a candidate prompt using the SAME
deterministic evaluation machinery Phase 7D already built — this module
reuses evals.run_llm_evals._run_explanation_case() / _run_answer_case()
and evals.metrics_llm.compute_*_metrics() verbatim. No evaluation logic is
duplicated here; this file only adds comparison (delta + status) on top of
metrics those functions already produce.

Why a separate candidate DATASET, not just a patched prompt string:
    Every case's Ollama response in the existing eval datasets is fully
    scripted via a "simulate" spec (Phase 7D's explicit, intentional
    design — "no live LLM required by default", deterministic and
    offline). Patching agents.recommendation_explainer._SYSTEM_PROMPT
    alone would have zero effect on a case's *scripted* output, so it
    cannot by itself reveal how a candidate prompt's wording changes
    behavior. Instead, the candidate dataset
    (llm_explanation_eval_cases_candidate_v2.json) records what the
    candidate prompt's outputs are expected/observed to look like for the
    SAME inputs as the baseline dataset — the same way a real experiment
    would sample candidate-prompt outputs by hand (or from a one-off
    --live run, not implemented here) before encoding them for repeatable,
    deterministic comparison. The prompt text itself IS still loaded via
    prompts.loader.load_prompt() and patched onto the module for the
    duration of the candidate run, purely for traceability/correctness —
    see _run_dataset_with_prompt().

Guarantees this script upholds (Phase 8C non-goals):
    - Never writes to prompts/registry.py or any prompt .md file.
    - Never changes which prompt agents/recommendation_explainer.py loads
      in production — _SYSTEM_PROMPT is patched via unittest.mock.patch,
      which always restores the original value on exit, even on error.
    - Never calls a live LLM — every case's response is scripted, exactly
      like evals/run_llm_evals.py.
    - Never recommends or performs automatic promotion — it prints a
      recommendation string for a human to act on.

Usage (from project root):
    python evals/run_prompt_experiments.py
    python -m evals.run_prompt_experiments [--no-archive] [--verbose]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import patch

# ── Project root on sys.path ────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import agents.recommendation_explainer as explainer  # noqa: E402
from evals.run_llm_evals import _run_explanation_case, _load_dataset  # noqa: E402
from evals.metrics_llm import compute_explanation_metrics  # noqa: E402
from prompts.loader import load_prompt, get_prompt_info  # noqa: E402

# ── Paths ────────────────────────────────────────────────────────────────────
_EVALS_DIR   = Path(__file__).parent
_REPORTS_DIR = _EVALS_DIR / "reports"

_DEFAULT_BASELINE_DATASET  = _EVALS_DIR / "llm_explanation_eval_cases.json"
_DEFAULT_CANDIDATE_DATASET = _EVALS_DIR / "llm_explanation_eval_cases_candidate_v2.json"

_BASELINE_PROMPT_NAME  = "recommendation_explanation"
_CANDIDATE_PROMPT_NAME = "recommendation_explanation_v2"

# Metrics where a LOWER value is the better outcome — every other numeric
# metric in compute_explanation_metrics()'s output is higher-is-better.
_LOWER_IS_BETTER = {"forbidden_claim_rate"}

# Minimum |delta| (percentage points) to call a change meaningful, rather
# than noise — chosen to match the metrics' own 0.1-point rounding.
_DELTA_THRESHOLD = 1.0


# ---------------------------------------------------------------------------
# Execution — reuses run_llm_evals._run_explanation_case() unchanged
# ---------------------------------------------------------------------------

def _run_dataset_with_prompt(dataset_path: Path, prompt_name: Optional[str]) -> list[dict]:
    """
    Run every case in dataset_path through the real, unmodified
    _run_explanation_case(). If prompt_name is given, agents.
    recommendation_explainer._SYSTEM_PROMPT is temporarily patched to that
    prompt's loaded text — restored automatically on exit via
    unittest.mock.patch.object, even if a case raises. If prompt_name is
    None, the module's current (production) prompt is left untouched.
    """
    dataset = _load_dataset(dataset_path)
    cases = dataset["cases"]

    if prompt_name is None:
        return [_run_explanation_case(case) for case in cases]

    prompt_text = load_prompt(prompt_name)
    with patch.object(explainer, "_SYSTEM_PROMPT", prompt_text):
        return [_run_explanation_case(case) for case in cases]


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------

def _status_for_delta(metric_name: str, delta: float) -> str:
    if abs(delta) < _DELTA_THRESHOLD:
        return "No meaningful change"
    higher_is_better = metric_name not in _LOWER_IS_BETTER
    improved = (delta > 0) if higher_is_better else (delta < 0)
    return "Improved" if improved else "Regressed"


def compare_explanation_metrics(baseline_metrics: dict, candidate_metrics: dict) -> list[dict]:
    """
    Compare every scalar rate metric compute_explanation_metrics() emits
    (skips the two non-scalar keys: overall_counts, outcome_distribution).
    Returns one row per metric: {metric, baseline, candidate, delta, status}.
    """
    rows: list[dict] = []
    scalar_keys = sorted(
        k for k in baseline_metrics
        if k not in ("overall_counts", "outcome_distribution")
        and isinstance(baseline_metrics[k], (int, float))
    )
    for key in scalar_keys:
        b = baseline_metrics[key]
        c = candidate_metrics.get(key, 0.0)
        delta = round(c - b, 1)
        rows.append({
            "metric":    key,
            "baseline":  b,
            "candidate": c,
            "delta":     delta,
            "status":    _status_for_delta(key, delta),
        })
    return rows


def _overall_recommendation(comparison_rows: list[dict]) -> str:
    """
    Deterministic, rule-based recommendation — never an LLM judgment call.
    Any regression rejects promotion outright, regardless of how many
    metrics improved; this mirrors the Phase 7 safety posture (a single
    forbidden-claim or evidence-coverage regression matters more than
    several unrelated improvements).
    """
    if any(r["status"] == "Regressed" for r in comparison_rows):
        return "Reject — at least one metric regressed"
    if any(r["status"] == "Improved" for r in comparison_rows):
        return "Promotable — improved with no regressions"
    return "No meaningful change — neither promote nor reject on this evidence"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _build_report(
    baseline_dataset_path: Path,
    candidate_dataset_path: Path,
    baseline_results: list[dict],
    candidate_results: list[dict],
    comparison_rows: list[dict],
    execution_time_ms: float,
) -> dict:
    baseline_prompt  = get_prompt_info(_BASELINE_PROMPT_NAME)
    candidate_prompt = get_prompt_info(_CANDIDATE_PROMPT_NAME)

    return {
        "schema_version": "1.0",
        "run_id":         str(uuid.uuid4()),
        "timestamp":      (datetime.now(timezone.utc)
                           .isoformat(timespec="seconds")
                           .replace("+00:00", "Z")),
        "baseline": {
            "prompt_name":    baseline_prompt.name,
            "prompt_version": baseline_prompt.version,
            "dataset":        str(baseline_dataset_path.name),
            "cases":          baseline_results,
            "metrics":        compute_explanation_metrics(baseline_results),
        },
        "candidate": {
            "prompt_name":    candidate_prompt.name,
            "prompt_version": candidate_prompt.version,
            "dataset":        str(candidate_dataset_path.name),
            "cases":          candidate_results,
            "metrics":        compute_explanation_metrics(candidate_results),
        },
        "comparison": comparison_rows,
        "recommendation": _overall_recommendation(comparison_rows),
        "execution_time_ms": execution_time_ms,
    }


def _write_report(report: dict, no_archive: bool) -> tuple[Path, Optional[Path]]:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    latest = _REPORTS_DIR / "latest_prompt_experiment_report.json"
    latest.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    archive: Optional[Path] = None
    if not no_archive:
        ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = _REPORTS_DIR / f"prompt_experiment_report_{ts}.json"
        archive.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    return latest, archive


# ---------------------------------------------------------------------------
# Terminal output
# ---------------------------------------------------------------------------

def format_console_summary(report: dict) -> str:
    width = 60
    lines = ["=" * width, "Prompt Experiment Summary", "=" * width, ""]

    b, c = report["baseline"], report["candidate"]
    lines.append(f"Baseline:  {b['prompt_name']} ({b['prompt_version']})  dataset={b['dataset']}")
    lines.append(f"Candidate: {c['prompt_name']} ({c['prompt_version']})  dataset={c['dataset']}")
    lines.append("")

    for row in report["comparison"]:
        lines.append(row["metric"])
        lines.append(f"  Baseline:  {row['baseline']}%")
        lines.append(f"  Candidate: {row['candidate']}%")
        sign = "+" if row["delta"] >= 0 else ""
        lines.append(f"  Delta:     {sign}{row['delta']}%")
        lines.append(f"  Status:    {row['status']}")
        lines.append("")

    lines.append(f"Recommendation: {report['recommendation']}")
    lines.append("")
    lines.append(f"Execution Time: {report['execution_time_ms']} ms")
    lines.append("")
    lines.append("=" * width)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run_prompt_experiments",
        description="Phase 8C offline prompt experimentation runner — CSULB Grad Center AI Assistant",
    )
    p.add_argument("--baseline-dataset", type=Path, default=_DEFAULT_BASELINE_DATASET)
    p.add_argument("--candidate-dataset", type=Path, default=_DEFAULT_CANDIDATE_DATASET)
    p.add_argument("--no-archive", action="store_true",
                   help="Write only latest_prompt_experiment_report.json, skip timestamped archive")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    t0 = time.perf_counter()

    baseline_results  = _run_dataset_with_prompt(args.baseline_dataset, None)
    candidate_results = _run_dataset_with_prompt(args.candidate_dataset, _CANDIDATE_PROMPT_NAME)

    execution_time_ms = round((time.perf_counter() - t0) * 1000, 1)

    baseline_metrics  = compute_explanation_metrics(baseline_results)
    candidate_metrics = compute_explanation_metrics(candidate_results)
    comparison_rows   = compare_explanation_metrics(baseline_metrics, candidate_metrics)

    report = _build_report(
        args.baseline_dataset, args.candidate_dataset,
        baseline_results, candidate_results, comparison_rows, execution_time_ms,
    )
    latest, archive = _write_report(report, args.no_archive)

    print(format_console_summary(report))
    print(f"Report: {latest}")
    if archive:
        print(f"        {archive}")

    if args.verbose:
        for label, results in (("Baseline", baseline_results), ("Candidate", candidate_results)):
            print()
            print(f"{label} case detail:")
            for r in results:
                print(f"  {r['status']:<6} {r['case_id']:<10} {r['actual_outcome']}")


if __name__ == "__main__":
    main()
