"""
rag/masters_catalog_cli.py
Command-line entry point for the full-catalog build (Phase 8).

    python -m rag.masters_catalog_cli --scratch-dir DIR \
        [--depth 1] [--measure-embedding] [--report PATH] [--stats-json PATH]

Argument parsing and file writing only — build logic lives in
rag/masters_catalog.py, rendering in rag/masters_catalog_report.py.
`--measure-embedding` enables the benchmark-only embedding timing pass; it is
off by default and never part of a normal build.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from rag.masters_catalog import CatalogBuildConfig, build_full_catalog
from rag.masters_catalog_report import render_report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Full-catalog master's acquisition into an isolated store")
    ap.add_argument("--scratch-dir", required=True,
                    help="isolated store directory (never the production chroma_db)")
    ap.add_argument("--depth", type=int, default=1)
    ap.add_argument("--measure-embedding", action="store_true",
                    help="benchmark-only: time a separate embedding pass "
                         "(doubles embedding cost for the run)")
    ap.add_argument("--report", default="", help="write markdown report here")
    ap.add_argument("--stats-json", default="", help="write raw stats JSON here")
    args = ap.parse_args(argv)

    config = CatalogBuildConfig(
        depth=args.depth, measure_embedding=args.measure_embedding)
    _, stats = build_full_catalog(args.scratch_dir, config=config)

    report = render_report(stats)
    print(report)
    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
    if args.stats_json:
        Path(args.stats_json).write_text(stats.to_json(), encoding="utf-8")


if __name__ == "__main__":
    main()
