"""
ingestion/masters/persistence.py
File-per-program persistence for CanonicalProgram records.

One JSON file per program under <programs_dir>/<program_id>.json, enabling
incremental updates, focused diffs, and selective re-ingestion. The directory is
injectable so tests write to a temp path; production points at
data/masters/programs/. Nothing here touches Chroma or any vector store.
"""
from __future__ import annotations

import json
from pathlib import Path

from domain.programs.models import CanonicalProgram


def program_path(programs_dir: Path, program_id: str) -> Path:
    return Path(programs_dir) / f"{program_id}.json"


def persist_program(program: CanonicalProgram, programs_dir: Path) -> Path:
    programs_dir = Path(programs_dir)
    programs_dir.mkdir(parents=True, exist_ok=True)
    path = program_path(programs_dir, program.identity.program_id)
    payload = program.model_dump(mode="json")
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def load_program(path: Path) -> CanonicalProgram:
    return CanonicalProgram.model_validate(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )
