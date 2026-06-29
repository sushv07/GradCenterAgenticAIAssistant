"""
evals/metrics_recommendation.py
Phase 2C — derived metrics over a Phase 2B recommendation-eval run.

Pure post-processing over the per-case results already produced by
run_recommendation_evals.py. Reads `actual` (what the system produced) for
the behavior/confidence/program-frequency distributions, and the dataset's
`known_gap` flag plus `status` for the pass/known-gap/fail breakdowns.

No recommendation logic, scoring, weights, taxonomy, or LLM/embedding/
LangGraph usage of any kind — this module only counts and divides numbers
that run_recommendation_evals.py already computed.
"""
from __future__ import annotations

_BEHAVIORS   = ("recommend", "multi_recommend", "clarify", "redirect", "partial_match_with_caveat")
_CONFIDENCES = ("high", "medium", "low", "none")
_CATEGORIES  = ("clear_match", "multi_match", "ambiguous", "edge_case")

PROGRAM_LABELS: dict[str, str] = {
    "dpt-physical-therapy":               "DPT",
    "dnp-nursing":                         "DNP",
    "drph-public-health":                 "DrPH",
    "edd-educational-leadership-p12":      "EdD P12",
    "edd-educational-leadership-cc":       "EdD CC",
    "phd-engineering-computational-math":  "Engineering PhD",
}


def _pct(count: int, total: int) -> float:
    return round(count / total * 100, 1) if total else 0.0


def _distribution(values: list, buckets: tuple[str, ...], total: int) -> dict:
    counts = {b: 0 for b in buckets}
    for v in values:
        if v in counts:
            counts[v] += 1
    return {b: {"count": counts[b], "pct": _pct(counts[b], total)} for b in buckets}


def compute_metrics(cases: list[dict]) -> dict:
    """Compute the Phase 2C metric set from a list of run_recommendation_evals.py case results."""
    total = len(cases)

    # ── 1. Overall counts ───────────────────────────────────────────────────
    overall_counts = {
        "total_cases": total,
        "pass":        sum(1 for c in cases if c["status"] == "PASS"),
        "known_gap":   sum(1 for c in cases if c["status"] == "KNOWN_GAP"),
        "fail":        sum(1 for c in cases if c["status"] == "FAIL"),
    }

    actual_behaviors   = [(c.get("actual") or {}).get("behavior") for c in cases]
    actual_confidences = [(c.get("actual") or {}).get("confidence") for c in cases]

    # ── 2/3. Behavior / confidence distribution (count + pct) ──────────────
    behavior_distribution   = _distribution(actual_behaviors, _BEHAVIORS, total)
    confidence_distribution = _distribution(actual_confidences, _CONFIDENCES, total)

    # ── 4. Category breakdown ───────────────────────────────────────────────
    category_breakdown = {}
    for cat in _CATEGORIES:
        cat_cases = [c for c in cases if c.get("category") == cat]
        category_breakdown[cat] = {
            "total":     len(cat_cases),
            "pass":      sum(1 for c in cat_cases if c["status"] == "PASS"),
            "known_gap": sum(1 for c in cat_cases if c["status"] == "KNOWN_GAP"),
            "fail":      sum(1 for c in cat_cases if c["status"] == "FAIL"),
        }

    # ── 5. Program recommendation frequency (actual recommended_programs) ──
    program_frequency = {pid: 0 for pid in PROGRAM_LABELS}
    for c in cases:
        for pid in (c.get("actual") or {}).get("recommended_programs", []) or []:
            program_frequency[pid] = program_frequency.get(pid, 0) + 1

    # ── 6-10. Rates ──────────────────────────────────────────────────────────
    clarify_count        = behavior_distribution["clarify"]["count"]
    redirect_count       = behavior_distribution["redirect"]["count"]
    recommend_like_count = (
        behavior_distribution["recommend"]["count"]
        + behavior_distribution["multi_recommend"]["count"]
        + behavior_distribution["partial_match_with_caveat"]["count"]
    )
    # known_gap_rate uses the dataset's known_gap flag (architectural-limitation
    # count), not the KNOWN_GAP status, so the rate stays meaningful even if a
    # known-gap case later FAILs (drifts from its documented limitation).
    known_gap_dataset_count = sum(1 for c in cases if c.get("known_gap"))
    fail_count = overall_counts["fail"]

    clarification_rate      = round(clarify_count / total, 4) if total else 0.0
    redirect_rate            = round(redirect_count / total, 4) if total else 0.0
    recommendation_rate      = round(recommend_like_count / total, 4) if total else 0.0
    known_gap_rate           = round(known_gap_dataset_count / total, 4) if total else 0.0
    unexpected_failure_rate  = round(fail_count / total, 4) if total else 0.0

    return {
        "overall_counts":                   overall_counts,
        "behavior_distribution":             behavior_distribution,
        "confidence_distribution":           confidence_distribution,
        "category_breakdown":                category_breakdown,
        "program_recommendation_frequency":  program_frequency,
        "clarification_rate":                clarification_rate,
        "redirect_rate":                     redirect_rate,
        "recommendation_rate":               recommendation_rate,
        "known_gap_rate":                    known_gap_rate,
        "unexpected_failure_rate":           unexpected_failure_rate,
    }


def _label(behavior: str) -> str:
    return behavior.replace("_", " ").title()


def format_console_summary(metrics: dict) -> str:
    """Render the Phase 2C metrics as a readable console block."""
    width = 50
    lines: list[str] = []
    lines.append("=" * width)
    lines.append("Recommendation Evaluation Summary")
    lines.append("=" * width)
    lines.append("")

    oc = metrics["overall_counts"]
    lines.append("Cases")
    lines.append(f"  Total: {oc['total_cases']}")
    lines.append(f"  Pass: {oc['pass']}")
    lines.append(f"  Known Gap: {oc['known_gap']}")
    lines.append(f"  Unexpected Failure: {oc['fail']}")
    lines.append("")

    lines.append("Behavior")
    for b in _BEHAVIORS:
        d = metrics["behavior_distribution"][b]
        lines.append(f"  {_label(b)}: {d['count']} ({d['pct']}%)")
    lines.append("")

    lines.append("Confidence")
    for cf in _CONFIDENCES:
        d = metrics["confidence_distribution"][cf]
        lines.append(f"  {cf.capitalize()}: {d['count']} ({d['pct']}%)")
    lines.append("")

    lines.append("Category Breakdown")
    for cat in _CATEGORIES:
        cb = metrics["category_breakdown"][cat]
        lines.append(
            f"  {cat}: total={cb['total']} pass={cb['pass']} "
            f"known_gap={cb['known_gap']} fail={cb['fail']}"
        )
    lines.append("")

    lines.append("Programs")
    for pid, label in PROGRAM_LABELS.items():
        count = metrics["program_recommendation_frequency"].get(pid, 0)
        dots = "." * max(1, 18 - len(label))
        lines.append(f"  {label} {dots} {count}")
    lines.append("")

    lines.append("Rates")
    lines.append(f"  Clarification: {metrics['clarification_rate'] * 100:.1f}%")
    lines.append(f"  Redirect: {metrics['redirect_rate'] * 100:.1f}%")
    lines.append(f"  Recommendation: {metrics['recommendation_rate'] * 100:.1f}%")
    lines.append(f"  Known Gap: {metrics['known_gap_rate'] * 100:.1f}%")
    lines.append(f"  Unexpected Failure: {metrics['unexpected_failure_rate'] * 100:.1f}%")
    lines.append("")
    lines.append("=" * width)
    return "\n".join(lines)
