#!/usr/bin/env python3
"""
evals/weight_validation.py
Phase 2E — deterministic heuristic-weight validation for the doctoral
recommendation engine.

Answers "which weights actually matter" using evidence from the gold
dataset, WITHOUT touching production code or production weights. This is
NOT a tuning tool: it never searches for "better" weights, never uses ML/
LLM/embeddings, and recommendation_engine.py is read-only input.

How it isolates the scoring layer
----------------------------------
For each of the 50 gold cases, this script:
  1. Replays the case's turns through the REAL agents.journey_agent.
     handle_discovery() to get the real, unmodified final JourneyState
     (signal extraction and gap detection are 100% production code,
     completely untouched by weight experiments).
  2. Recomputes the final turn's gaps via the REAL detect_gaps() (pure
     function, no side effects) so the Phase D decision tree sees exactly
     what production would have seen.
  3. Calls experimental_select_recommendation(state, gaps, taxonomy, W) for
     a weight config W — a clone of Phase D's decision logic
     (evals/experimental_scoring.py) parameterized by weights instead of
     literal constants.

The "baseline" for every comparison is experimental_select_recommendation()
run with DEFAULT_WEIGHTS (i.e. production's actual constants, expressed as
data). A fidelity check at the top of every run verifies this baseline is
byte-identical to calling the REAL recommendation_engine.select_recommend
ation() on the same state+gaps, for all 50 cases — proving the clone hasn't
drifted. Every experiment below is then: same state+gaps, same algorithm,
different weight dict.

This deliberately does NOT compare against the gold dataset's expected_*
values (that is Phase 2B/2C/2D's job). Phase 2E only asks: "if Phase D used
different weights, what would change relative to what it does today?"

Usage (from project root):
    python evals/weight_validation.py
    python -m evals.weight_validation [--dataset PATH] [--no-archive]
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.journey_agent import (  # noqa: E402
    handle_discovery, extract_signals, detect_gaps,
)
from state.context_manager import clear_context  # noqa: E402
from agents.recommendation_engine import (  # noqa: E402
    select_recommendation as production_select_recommendation,
)
from evals.experimental_scoring import (  # noqa: E402
    DEFAULT_WEIGHTS, experimental_score_all, experimental_select_recommendation,
    load_taxonomy,
)
from evals.metrics_recommendation import PROGRAM_LABELS, _distribution  # noqa: E402

_EVALS_DIR       = Path(__file__).parent
_REPORTS_DIR     = _EVALS_DIR / "reports"
_DEFAULT_DATASET = _EVALS_DIR / "recommendation_eval_cases.json"

# Uniform perturbation used by the per-weight sensitivity sweep (requirement
# 6): every weight is independently scaled by this factor, one at a time,
# so cross-weight comparisons ("which weight matters most") are apples-to-
# apples. Easy to change — it's the only knob for the sweep.
_SENSITIVITY_SCALE = 0.5

# The four named, hand-picked scenario experiments (requirement 4). Exact
# values don't matter per the spec; these are illustrative deltas chosen to
# be large enough to surface real behavior differences.
NAMED_EXPERIMENTS: list[dict] = [
    {
        "name": "career_weight_reduced",
        "description": "Reduce career_unique weight 0.85 -> 0.70",
        "weights": {**DEFAULT_WEIGHTS, "career_unique": 0.70},
    },
    {
        "name": "background_weight_reduced",
        "description": "Reduce background_1 weight 0.10 -> 0.05",
        "weights": {**DEFAULT_WEIGHTS, "background_1": 0.05},
    },
    {
        "name": "orientation_penalty_increased",
        "description": "Increase orientation_mismatch penalty -0.10 -> -0.30",
        "weights": {**DEFAULT_WEIGHTS, "orientation_mismatch": -0.30},
    },
    {
        "name": "career_gap_multiplier_disabled",
        "description": "Disable career_gap_multiplier 0.50 -> 1.00 (no penalty)",
        "weights": {**DEFAULT_WEIGHTS, "career_gap_multiplier": 1.00},
    },
]


# ── Case state extraction (real production pipeline, read-only) ───────────

def _final_state_and_gaps(case: dict) -> dict:
    """Replay a case's turns through the REAL handle_discovery() and recompute
    the final turn's gaps via the REAL detect_gaps(). Both are pure/production
    functions — nothing here is weight-experiment code."""
    sid = f"weightval_{case['case_id']}"
    clear_context(sid)

    state = None
    last_query = case["turns"][-1]
    for turn in case["turns"]:
        _response, state = handle_discovery(turn, sid)
    clear_context(sid)

    last_bundle = extract_signals(last_query)
    gaps = detect_gaps(state, last_bundle)
    return {"state": state, "gaps": gaps}


# ── Fidelity check ──────────────────────────────────────────────────────────

def run_fidelity_check(cases: list[dict], taxonomy: list[dict]) -> dict:
    """Verify experimental_select_recommendation(DEFAULT_WEIGHTS) is
    byte-identical to the REAL recommendation_engine.select_recommendation()
    for every case, proving the clone hasn't drifted from production."""
    mismatches: list[dict] = []
    for case in cases:
        ctx = _final_state_and_gaps(case)
        real_result = production_select_recommendation(ctx["state"], ctx["gaps"], taxonomy)
        clone_result = experimental_select_recommendation(
            ctx["state"], ctx["gaps"], taxonomy, DEFAULT_WEIGHTS,
        )
        if (
            real_result.behavior != clone_result.behavior
            or real_result.confidence != clone_result.confidence
            or real_result.recommended_programs != clone_result.recommended_programs
        ):
            mismatches.append({
                "case_id": case["case_id"],
                "real":   {"behavior": real_result.behavior, "confidence": real_result.confidence,
                           "recommended_programs": real_result.recommended_programs},
                "clone":  {"behavior": clone_result.behavior, "confidence": clone_result.confidence,
                           "recommended_programs": clone_result.recommended_programs},
            })
    return {"total_cases": len(cases), "mismatches": mismatches, "fidelity_ok": not mismatches}


# ── Single-case comparison ──────────────────────────────────────────────────

def _result_snapshot(result) -> dict:
    return {
        "behavior":             result.behavior,
        "confidence":            result.confidence,
        "recommended_programs": result.recommended_programs,
    }


def _diff_snapshots(baseline: dict, experimental: dict) -> list[dict]:
    diffs = []
    for field in ("behavior", "confidence", "recommended_programs"):
        if baseline[field] != experimental[field]:
            diffs.append({"field": field, "baseline": baseline[field], "experimental": experimental[field]})
    return diffs


# ── Named experiment runner ──────────────────────────────────────────────────

def run_experiment(
    name: str,
    weights: dict[str, float],
    case_contexts: list[dict],
    taxonomy: list[dict],
) -> dict:
    """Compare experimental_select_recommendation(DEFAULT_WEIGHTS) against
    experimental_select_recommendation(weights) for every case. Both runs use
    the SAME real production state+gaps captured once in case_contexts."""
    baseline_results:     list[dict] = []
    experimental_results: list[dict] = []
    changed_cases:        list[dict] = []

    top1_changed = top2_changed = clarify_changes = redirect_changes = 0
    known_gap_changes = 0
    behavior_changed = confidence_changed = programs_changed = 0
    largest_score_delta = 0.0

    for ctx in case_contexts:
        case  = ctx["case"]
        state = ctx["state"]
        gaps  = ctx["gaps"]

        baseline_scores     = experimental_score_all(state, taxonomy, DEFAULT_WEIGHTS)
        experimental_scores = experimental_score_all(state, taxonomy, weights)

        baseline_top1     = baseline_scores[0].program_id if baseline_scores else None
        experimental_top1 = experimental_scores[0].program_id if experimental_scores else None
        baseline_top2     = baseline_scores[1].program_id if len(baseline_scores) > 1 else None
        experimental_top2 = experimental_scores[1].program_id if len(experimental_scores) > 1 else None

        by_id_baseline     = {s.program_id: s.raw_score for s in baseline_scores}
        by_id_experimental = {s.program_id: s.raw_score for s in experimental_scores}
        for pid, base_score in by_id_baseline.items():
            delta = abs(by_id_experimental.get(pid, 0.0) - base_score)
            largest_score_delta = max(largest_score_delta, delta)

        baseline_result     = experimental_select_recommendation(state, gaps, taxonomy, DEFAULT_WEIGHTS)
        experimental_result = experimental_select_recommendation(state, gaps, taxonomy, weights)

        baseline_snap     = _result_snapshot(baseline_result)
        experimental_snap = _result_snapshot(experimental_result)
        baseline_results.append({**baseline_snap, "category": case.get("category"), "known_gap": case["known_gap"]})
        experimental_results.append({**experimental_snap, "category": case.get("category"), "known_gap": case["known_gap"]})

        diffs = _diff_snapshots(baseline_snap, experimental_snap)

        if baseline_top1 != experimental_top1:
            top1_changed += 1
        if baseline_top2 != experimental_top2:
            top2_changed += 1
        if (baseline_snap["behavior"] == "clarify") != (experimental_snap["behavior"] == "clarify"):
            clarify_changes += 1
        if (baseline_snap["behavior"] == "redirect") != (experimental_snap["behavior"] == "redirect"):
            redirect_changes += 1
        if case["known_gap"] and diffs:
            known_gap_changes += 1

        if any(d["field"] == "behavior" for d in diffs):
            behavior_changed += 1
        if any(d["field"] == "confidence" for d in diffs):
            confidence_changed += 1
        if any(d["field"] == "recommended_programs" for d in diffs):
            programs_changed += 1

        if diffs:
            changed_cases.append({
                "case_id":      case["case_id"],
                "category":     case.get("category"),
                "known_gap":    case["known_gap"],
                "baseline":     baseline_snap,
                "experimental": experimental_snap,
                "differences":  diffs,
            })

    cases_changed = len(changed_cases)

    metrics_before = {
        "behavior_distribution":  _distribution([r["behavior"] for r in baseline_results],
                                                 ("recommend", "multi_recommend", "clarify",
                                                  "redirect", "partial_match_with_caveat"),
                                                 len(baseline_results)),
        "confidence_distribution": _distribution([r["confidence"] for r in baseline_results],
                                                  ("high", "medium", "low", "none"),
                                                  len(baseline_results)),
        "program_recommendation_frequency": _program_frequency(baseline_results),
    }
    metrics_after = {
        "behavior_distribution":  _distribution([r["behavior"] for r in experimental_results],
                                                 ("recommend", "multi_recommend", "clarify",
                                                  "redirect", "partial_match_with_caveat"),
                                                 len(experimental_results)),
        "confidence_distribution": _distribution([r["confidence"] for r in experimental_results],
                                                  ("high", "medium", "low", "none"),
                                                  len(experimental_results)),
        "program_recommendation_frequency": _program_frequency(experimental_results),
    }

    weight_changes = {
        k: {"before": DEFAULT_WEIGHTS[k], "after": v}
        for k, v in weights.items() if DEFAULT_WEIGHTS[k] != v
    }

    return {
        "experiment":     name,
        "weight_changes": weight_changes,
        "summary": {
            "cases_changed":        cases_changed,
            "programs_changed":     programs_changed,
            "confidence_changed":   confidence_changed,
            "behavior_changed":     behavior_changed,
            "top1_changed":         top1_changed,
            "top2_changed":         top2_changed,
            "clarify_changes":      clarify_changes,
            "redirect_changes":     redirect_changes,
            "known_gap_changes":    known_gap_changes,
            "largest_score_delta":  round(largest_score_delta, 4),
            "metrics_before":       metrics_before,
            "metrics_after":        metrics_after,
        },
        "changed_cases": changed_cases,
    }


def _program_frequency(results: list[dict]) -> dict:
    freq = {pid: 0 for pid in PROGRAM_LABELS}
    for r in results:
        for pid in r.get("recommended_programs") or []:
            freq[pid] = freq.get(pid, 0) + 1
    return freq


# ── Per-weight sensitivity sweep (requirement 6) ────────────────────────────

def run_sensitivity_sweep(case_contexts: list[dict], taxonomy: list[dict]) -> dict:
    """For every weight, perturb it alone (scale by _SENSITIVITY_SCALE) and
    measure how many cases' scores shift at all, which program(s) shift the
    most, and the single largest per-program score delta observed."""
    sweep: dict[str, dict] = {}

    for weight_name, base_value in DEFAULT_WEIGHTS.items():
        perturbed_weights = {**DEFAULT_WEIGHTS, weight_name: base_value * _SENSITIVITY_SCALE}

        cases_affected = 0
        largest_delta  = 0.0
        program_delta_totals: dict[str, float] = {}

        for ctx in case_contexts:
            state = ctx["state"]
            baseline_scores    = experimental_score_all(state, taxonomy, DEFAULT_WEIGHTS)
            perturbed_scores   = experimental_score_all(state, taxonomy, perturbed_weights)
            by_id_perturbed    = {s.program_id: s.raw_score for s in perturbed_scores}

            case_affected = False
            for s in baseline_scores:
                delta = abs(by_id_perturbed.get(s.program_id, 0.0) - s.raw_score)
                if delta > 1e-9:
                    case_affected = True
                    largest_delta = max(largest_delta, delta)
                    program_delta_totals[s.program_id] = program_delta_totals.get(s.program_id, 0.0) + delta

            if case_affected:
                cases_affected += 1

        programs_affected_most = sorted(
            program_delta_totals, key=lambda pid: program_delta_totals[pid], reverse=True,
        )[:3]

        sweep[weight_name] = {
            "perturbation":            f"{base_value} -> {round(base_value * _SENSITIVITY_SCALE, 4)}",
            "cases_affected":          cases_affected,
            "pct_affected":            round(cases_affected / len(case_contexts) * 100, 1) if case_contexts else 0.0,
            "programs_affected_most":  [PROGRAM_LABELS.get(p, p) for p in programs_affected_most],
            "largest_score_change":    round(largest_delta, 4),
        }

    return sweep


# ── Report ───────────────────────────────────────────────────────────────────

def _build_report(fidelity: dict, experiments: list[dict], sensitivity: dict) -> dict:
    return {
        "schema_version": "1.0",
        "run_id":         str(uuid.uuid4()),
        "timestamp":      (datetime.now(timezone.utc)
                           .isoformat(timespec="seconds")
                           .replace("+00:00", "Z")),
        "fidelity_check": fidelity,
        "experiments":    experiments,
        "weight_sensitivity": sensitivity,
    }


def _write_report(report: dict, no_archive: bool) -> tuple[Path, Optional[Path]]:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    latest = _REPORTS_DIR / "latest_weight_validation_report.json"
    latest.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    archive: Optional[Path] = None
    if not no_archive:
        ts      = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = _REPORTS_DIR / f"weight_validation_report_{ts}.json"
        archive.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    return latest, archive


# ── Console output ───────────────────────────────────────────────────────────

def _print_fidelity(fidelity: dict) -> None:
    print("=" * 50)
    print("Weight Validation — Fidelity Check")
    print("=" * 50)
    status = "OK" if fidelity["fidelity_ok"] else "MISMATCH"
    print(f"Clone vs production (DEFAULT_WEIGHTS): {status}  "
          f"({fidelity['total_cases'] - len(fidelity['mismatches'])}/{fidelity['total_cases']} match)")
    for m in fidelity["mismatches"][:5]:
        print(f"  ! {m['case_id']}: real={m['real']} clone={m['clone']}")
    print()


def _print_experiment(exp: dict) -> None:
    s = exp["summary"]
    print("Experiment")
    print(f"{exp['experiment']}")
    for k, v in exp["weight_changes"].items():
        print(f"  {k} = {v['before']} -> {v['after']}")
    print("-" * 24)
    print(f"Cases changed: {s['cases_changed']}")
    print(f"Top-1 changed: {s['top1_changed']}")
    print(f"Top-2 changed: {s['top2_changed']}")
    print(f"Programs changed: {s['programs_changed']}")
    print(f"Confidence changed: {s['confidence_changed']}")
    print(f"Behavior changed: {s['behavior_changed']}")
    print(f"Clarify changes: {s['clarify_changes']}")
    print(f"Redirect changes: {s['redirect_changes']}")
    print(f"Known-gap changes: {s['known_gap_changes']}")
    print()
    print(f"Largest score delta: {s['largest_score_delta']}")
    print()


def _print_sensitivity(sensitivity: dict) -> None:
    print("=" * 50)
    print("Weight Sensitivity Sweep")
    print(f"(uniform {_SENSITIVITY_SCALE}x scale, one weight at a time)")
    print("=" * 50)
    for weight_name, row in sensitivity.items():
        print(
            f"  {weight_name:<22} affected={row['cases_affected']:>2} "
            f"({row['pct_affected']:>5.1f}%)  max_delta={row['largest_score_change']:.4f}  "
            f"top_programs={', '.join(row['programs_affected_most']) or 'none'}"
        )
    print()


# ── CLI ──────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="weight_validation",
        description="Phase 2E heuristic weight validation — CSULB Grad Center AI Assistant",
    )
    p.add_argument("--dataset", default=str(_DEFAULT_DATASET),
                    help="Path to the recommendation eval gold dataset")
    p.add_argument("--no-archive", action="store_true",
                    help="Write only latest_weight_validation_report.json, skip timestamped archive")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"[weight_validation] ERROR: dataset not found: {dataset_path}", file=sys.stderr)
        sys.exit(1)

    with dataset_path.open(encoding="utf-8") as fh:
        dataset = json.load(fh)
    cases = dataset.get("cases", [])
    if not cases:
        print(f"[weight_validation] ERROR: no cases in {dataset_path}", file=sys.stderr)
        sys.exit(1)

    taxonomy = load_taxonomy()

    # Capture real production state+gaps ONCE per case — every experiment and
    # the sensitivity sweep reuse this same context, so all comparisons are
    # apples-to-apples and the (slow) journey replay only happens once.
    case_contexts = []
    for case in cases:
        ctx = _final_state_and_gaps(case)
        case_contexts.append({"case": case, "state": ctx["state"], "gaps": ctx["gaps"]})

    fidelity = run_fidelity_check(cases, taxonomy)
    _print_fidelity(fidelity)

    experiments = []
    for exp_def in NAMED_EXPERIMENTS:
        result = run_experiment(exp_def["name"], exp_def["weights"], case_contexts, taxonomy)
        experiments.append(result)
        _print_experiment(result)

    sensitivity = run_sensitivity_sweep(case_contexts, taxonomy)
    _print_sensitivity(sensitivity)

    report = _build_report(fidelity, experiments, sensitivity)
    latest, archive = _write_report(report, args.no_archive)
    print(f"Report: {latest}")
    if archive:
        print(f"        {archive}")

    if not fidelity["fidelity_ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
