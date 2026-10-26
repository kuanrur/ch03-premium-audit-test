"""Run the class-code assistant on one or more employer files.

Reads the classification guide and the employer files from the audit team's Drive
folder at the start of every run (or from a local copy given with --source-dir),
then writes, per employer:

    deliverables/codes/<employer>.csv
    deliverables/audit-report.md      (the employer's section)
    deliverables/audit-questions.md   (the employer's section)
    runs/<employer>.json              (run record: sources read, allocation, questions)

Examples:
    python3 skills/class-code-assistant/scripts/run_audit.py --employer harbor-point-legal
    python3 skills/class-code-assistant/scripts/run_audit.py --all
    python3 skills/class-code-assistant/scripts/run_audit.py --employer-dir ~/Downloads/new-employer
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
REPO = SKILL_DIR.parent.parent

from allocate import allocate  # noqa: E402
from employer import EmployerFileError, load_employer  # noqa: E402
from fetch_drive import FetchError, fetch_folder  # noqa: E402
from guide import GuideError, load_guide  # noqa: E402
from render import QUESTIONS_TITLE, REPORT_TITLE, codes_csv, merge_sections, questions_section, report_section, run_record  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Suggest class codes, allocate payroll and draft audit questions.")
    pick = ap.add_mutually_exclusive_group(required=True)
    pick.add_argument("--employer", action="append", metavar="SLUG", help="employer folder name, for example harbor-point-legal (repeatable)")
    pick.add_argument("--all", action="store_true", help="every employer folder in the source")
    pick.add_argument("--employer-dir", type=Path, help="a local employer folder that is not in the Drive folder")
    ap.add_argument("--source-dir", type=Path, help="use a local copy of the audit folder instead of reading Drive")
    ap.add_argument("--cache-dir", type=Path, default=REPO / ".cache" / "drive", help="where the Drive folder is downloaded")
    ap.add_argument("--out", type=Path, default=REPO, help="repository root to write deliverables/ and runs/ into")
    args = ap.parse_args(argv)

    config = json.loads((SKILL_DIR / "sources.json").read_text(encoding="utf-8"))
    sources = {"guide_file": config["guide_file"], "employers_folder": config["employers_folder"]}
    try:
        if args.source_dir:
            root = args.source_dir.expanduser().resolve()
            sources["read_from"] = f"local copy {root}"
        else:
            root = args.cache_dir.resolve()
            if root.exists():
                shutil.rmtree(root)
            fetch_folder(config["drive_folder_id"], root)
            sources["read_from"] = f"Google Drive folder '{config['drive_folder_name']}' ({config['drive_folder_id']})"
        sources["read_at_utc"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        guide_path = root / config["guide_file"]
        if not guide_path.exists():
            raise GuideError(f"classification guide {config['guide_file']} not found in {root}")
        guide = load_guide(guide_path)
    except (FetchError, GuideError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    employers_root = root / config["employers_folder"]
    if args.employer_dir:
        folders = [args.employer_dir.expanduser().resolve()]
    else:
        available = sorted(p.name for p in employers_root.iterdir() if p.is_dir()) if employers_root.is_dir() else []
        wanted = available if args.all else args.employer
        missing = [s for s in wanted if s not in available]
        if missing:
            print(f"error: no employer folder named {', '.join(missing)}; available: {', '.join(available) or 'none'}", file=sys.stderr)
            return 1
        folders = [employers_root / s for s in wanted]

    out = args.out.resolve()
    (out / "deliverables" / "codes").mkdir(parents=True, exist_ok=True)
    (out / "runs").mkdir(parents=True, exist_ok=True)
    order = config.get("report_order", [])
    failed = 0
    for folder in folders:
        try:
            emp = load_employer(folder)
            result = allocate(emp, guide)
        except (EmployerFileError, GuideError, ValueError) as exc:
            failed += 1
            print(f"error: {folder.name}: {exc}", file=sys.stderr)
            continue
        (out / "deliverables" / "codes" / f"{emp.slug}.csv").write_text(codes_csv(result), encoding="utf-8")
        merge_sections(out / "deliverables" / "audit-report.md", REPORT_TITLE, emp.slug, report_section(result), order)
        merge_sections(out / "deliverables" / "audit-questions.md", QUESTIONS_TITLE, emp.slug, questions_section(result), order)
        files = {p.name: sha256(p) for p in sorted(folder.iterdir()) if p.is_file()}
        record = run_record(result, {**sources, "guide_sha256": sha256(guide_path), "employer_files_sha256": files})
        (out / "runs" / f"{emp.slug}.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        verdict = "accepted" if result.accepted else "not accepted"
        codes = ", ".join(f"{c} {a:.2f}" for c, a, _ in result.lines())
        print(f"{emp.slug}: employer split {verdict}; {codes}; {len(result.adjustments)} adjustments, {len(result.questions)} questions")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
