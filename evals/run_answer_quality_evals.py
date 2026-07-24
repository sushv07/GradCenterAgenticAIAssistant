"""
evals/run_answer_quality_evals.py
Phase 10 — answer-quality evaluation runner.

Scores the baseline (v1-style) and candidate (v2-style) answer for every golden
case in answer_quality_eval_cases.json using the deterministic metrics in
evals/metrics_answer_quality.py, then renders a before/after report. Fully
offline and deterministic — no LLM, no network, no embeddings (see that module's
docstring and PHASE10_ANSWER_QUALITY_REVIEW.md for why this is fixture-based
rather than a live-model A/B).

Usage:
    python -m evals.run_answer_quality_evals            # print report
    python -m evals.run_answer_quality_evals --report evals/ANSWER_QUALITY_REPORT.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.metrics_answer_quality import aggregate, evaluate_case

CASES_PATH = Path(__file__).parent / "answer_quality_eval_cases.json"
REPORT_PATH = Path(__file__).parent / "ANSWER_QUALITY_REPORT.md"


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    data = json.loads(Path(path).read_text("utf-8"))
    cases = data["cases"]
    seen = set()
    for c in cases:
        for key in ("case_id", "category", "query",
                    "baseline_answer", "candidate_answer"):
            if key not in c:
                raise ValueError(f"case missing {key!r}: {c.get('case_id')}")
        if c["case_id"] in seen:
            raise ValueError(f"duplicate case_id {c['case_id']}")
        seen.add(c["case_id"])
    return cases


def run(cases: list[dict]) -> dict:
    baseline = [evaluate_case(c, "baseline") for c in cases]
    candidate = [evaluate_case(c, "candidate") for c in cases]
    return {
        "baseline": baseline,
        "candidate": candidate,
        "baseline_summary": aggregate(baseline),
        "candidate_summary": aggregate(candidate),
    }


def render_report(outcome: dict, cases: list[dict]) -> str:
    b, c = outcome["baseline_summary"], outcome["candidate_summary"]
    L = ["# Answer-Quality Evaluation — v1 baseline vs v2 candidate (Phase 10)", "",
         "Deterministic property scoring over the answer-quality golden set "
         "(`evals/answer_quality_eval_cases.json`). No LLM, no embeddings, no "
         "network. `expect` thresholds are checked against the candidate answer.",
         "", "## Summary", "",
         "| metric | v1 baseline | v2 candidate |",
         "| --- | --- | --- |",
         f"| cases | {b['cases']} | {c['cases']} |",
         f"| expectations passed | {b['passed']}/{b['cases']} | "
         f"**{c['passed']}/{c['cases']}** |",
         f"| mean grounding rate | {b['mean_grounding']} | {c['mean_grounding']} |",
         f"| citation fidelity rate | {b['citation_fidelity_rate']} | "
         f"{c['citation_fidelity_rate']} |",
         f"| hallucinated URLs (total) | {b['hallucinated_url_total']} | "
         f"{c['hallucinated_url_total']} |",
         f"| mean length (chars) | {b['mean_chars']} | {c['mean_chars']} |",
         f"| mean repetition rate | {b['mean_repetition']} | {c['mean_repetition']} |",
         "", "## Per-case (candidate)", "",
         "| case | category | grounding | fidelity | chars | repetition | passed |",
         "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in outcome["candidate"]:
        s = r["scores"]
        L.append(f"| {r['case_id']} | {r['category']} | {s['grounding_rate']} | "
                 f"{'ok' if s['citation_fidelity_ok'] else 'FAB'} | {s['chars']} | "
                 f"{s['repetition_rate']} | {'yes' if r['passed'] else 'NO'} |")
    # any candidate failures, with reasons
    fails = [r for r in outcome["candidate"] if not r["passed"]]
    L += ["", "## Candidate expectation failures", ""]
    L.append("(none)" if not fails else "")
    for r in fails:
        L.append(f"- {r['case_id']}: {'; '.join(r['failures'])}")

    by_id = {c["case_id"]: c for c in cases}
    L += ["", "## Before/after examples", ""]
    for r in outcome["candidate"][:3]:
        case = by_id[r["case_id"]]
        bscore = next(x for x in outcome["baseline"] if x["case_id"] == r["case_id"])
        L += [f"### {r['case_id']} — {r['category']}: {case['query']}", "",
              f"**v1 baseline** (grounding {bscore['scores']['grounding_rate']}, "
              f"{bscore['scores']['chars']} chars, repetition "
              f"{bscore['scores']['repetition_rate']}):", "",
              f"> {case['baseline_answer'][:400].replace(chr(10), ' ')}", "",
              f"**v2 candidate** (grounding {r['scores']['grounding_rate']}, "
              f"{r['scores']['chars']} chars, repetition "
              f"{r['scores']['repetition_rate']}):", "",
              f"> {case['candidate_answer'][:400].replace(chr(10), ' ')}", ""]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 10 answer-quality eval")
    ap.add_argument("--report", default="", help="write markdown report here")
    args = ap.parse_args()
    cases = load_cases()
    outcome = run(cases)
    report = render_report(outcome, cases)
    print(report)
    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
