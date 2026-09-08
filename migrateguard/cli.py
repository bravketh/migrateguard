"""migrateguard CLI: `migrateguard check path/to/migrations/`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from migrateguard import parser as mg_parser
from migrateguard.rules import dropped_column, not_null_no_default, removed_index, type_narrowing

RULES = [dropped_column, type_narrowing, removed_index, not_null_no_default]


def discover_migrations(path: Path) -> list[Path]:
    """Sorted list of forward migration files.

    Skips `*.down.sql` (golang-migrate/Flyway-undo style rollback files) since
    only the forward direction matters for the resulting schema shape. Plain
    `*.sql` files (Flyway `V1__x.sql` style) and `*.up.sql` files are both
    treated as forward migrations.
    """
    files = [p for p in path.glob("*.sql") if not p.name.endswith(".down.sql")]
    return sorted(files, key=lambda p: p.name)


class FileResult:
    def __init__(self, path: Path, findings=None, error: str | None = None):
        self.path = path
        self.findings = findings or []
        self.error = error


def run_check(path: Path, dialect: str = "postgres") -> list[FileResult]:
    schema = mg_parser.Schema()
    results: list[FileResult] = []
    for file in discover_migrations(path):
        sql = file.read_text()
        before = schema.clone()
        try:
            changes = mg_parser.apply_migration(schema, sql, dialect=dialect)
        except mg_parser.MigrationParseError as exc:
            results.append(FileResult(file, error=str(exc)))
            continue
        after = schema
        findings = []
        for rule in RULES:
            findings.extend(rule.check(changes, before, after))
        results.append(FileResult(file, findings=findings))
    return results


def _relative(file: Path, base: Path) -> str:
    try:
        return str(file.relative_to(base))
    except ValueError:
        return str(file)


def format_report(results: list[FileResult], base_path: Path) -> tuple[str, int]:
    lines: list[str] = []
    total = 0
    for result in results:
        rel = _relative(result.path, base_path)
        if result.error:
            lines.append(f"✖ {rel}: failed to parse ({result.error})")
            continue
        if not result.findings:
            continue
        lines.append(f"⚠ {rel}")
        for finding in result.findings:
            total += 1
            location = f"{finding.table}.{finding.column}" if finding.column else finding.table
            lines.append(f"    [{finding.rule}] {location}: {finding.message}")
    if total == 0 and not any(r.error for r in results):
        lines.insert(0, "No breaking changes detected.")
    return "\n".join(lines), total


def to_json(results: list[FileResult], base_path: Path) -> str:
    payload = []
    for result in results:
        payload.append({
            "file": _relative(result.path, base_path),
            "error": result.error,
            "findings": [
                {
                    "rule": f.rule,
                    "table": f.table,
                    "column": f.column,
                    "severity": f.severity,
                    "message": f.message,
                }
                for f in result.findings
            ],
        })
    return json.dumps(payload, indent=2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="migrateguard")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="Check migrations for breaking changes")
    check_parser.add_argument("path", type=Path, help="Path to a directory of migration files")
    check_parser.add_argument("--dialect", default="postgres", help="SQL dialect (default: postgres)")
    check_parser.add_argument("--json", action="store_true", dest="as_json", help="Emit machine-readable JSON")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "check":
        if not args.path.is_dir():
            print(f"error: {args.path} is not a directory", file=sys.stderr)
            return 2

        results = run_check(args.path, dialect=args.dialect)
        has_issues = any(r.findings or r.error for r in results)

        if args.as_json:
            print(to_json(results, args.path))
        else:
            report, _ = format_report(results, args.path)
            print(report)

        return 1 if has_issues else 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
