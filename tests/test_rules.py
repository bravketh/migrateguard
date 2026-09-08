from pathlib import Path

import pytest

from migrateguard import parser as mg_parser
from migrateguard.cli import run_check
from migrateguard.rules import dropped_column, not_null_no_default, removed_index, type_narrowing

FIXTURES = Path(__file__).parent / "fixtures"


def _apply(schema, sql):
    return mg_parser.apply_migration(schema, sql)


def test_clean_migrations_produce_no_findings():
    results = run_check(FIXTURES / "clean")
    assert all(not r.error for r in results)
    assert all(not r.findings for r in results)


def test_breaking_fixture_flags_every_rule():
    results = run_check(FIXTURES / "breaking")
    rules_seen = {f.rule for r in results for f in r.findings}
    assert rules_seen == {
        dropped_column.RULE_ID,
        type_narrowing.RULE_ID,
        removed_index.RULE_ID,
        not_null_no_default.RULE_ID,
    }


def test_dropped_column():
    schema = mg_parser.Schema()
    _apply(schema, "CREATE TABLE t (id INT, name VARCHAR(50));")
    before = schema.clone()
    changes = _apply(schema, "ALTER TABLE t DROP COLUMN name;")
    findings = dropped_column.check(changes, before, schema)
    assert len(findings) == 1
    assert findings[0].column == "name"


def test_dropped_table():
    schema = mg_parser.Schema()
    _apply(schema, "CREATE TABLE t (id INT);")
    before = schema.clone()
    changes = _apply(schema, "DROP TABLE t;")
    findings = dropped_column.check(changes, before, schema)
    assert len(findings) == 1
    assert findings[0].table == "t"


def test_renamed_column_is_flagged():
    schema = mg_parser.Schema()
    _apply(schema, "CREATE TABLE t (id INT, old_name VARCHAR(50));")
    before = schema.clone()
    changes = _apply(schema, "ALTER TABLE t RENAME COLUMN old_name TO new_name;")
    findings = dropped_column.check(changes, before, schema)
    assert len(findings) == 1
    assert findings[0].column == "old_name"


@pytest.mark.parametrize("before_type,after_type,narrowing", [
    ("VARCHAR(255)", "VARCHAR(50)", True),
    ("VARCHAR(50)", "VARCHAR(255)", False),
    ("BIGINT", "INT", True),
    ("INT", "BIGINT", False),
    ("NUMERIC(10,2)", "NUMERIC(5,2)", True),
])
def test_type_narrowing(before_type, after_type, narrowing):
    schema = mg_parser.Schema()
    _apply(schema, f"CREATE TABLE t (id INT, val {before_type});")
    before = schema.clone()
    changes = _apply(schema, f"ALTER TABLE t ALTER COLUMN val TYPE {after_type};")
    findings = type_narrowing.check(changes, before, schema)
    assert (len(findings) == 1) is narrowing


def test_removed_index():
    schema = mg_parser.Schema()
    _apply(schema, "CREATE TABLE t (id INT, email VARCHAR(255));")
    _apply(schema, "CREATE UNIQUE INDEX idx_email ON t (email);")
    before = schema.clone()
    changes = _apply(schema, "DROP INDEX idx_email;")
    findings = removed_index.check(changes, before, schema)
    assert len(findings) == 1
    assert "idx_email" in findings[0].message


def test_not_null_no_default_on_existing_table():
    schema = mg_parser.Schema()
    _apply(schema, "CREATE TABLE t (id INT);")
    before = schema.clone()
    changes = _apply(schema, "ALTER TABLE t ADD COLUMN age INT NOT NULL;")
    findings = not_null_no_default.check(changes, before, schema)
    assert len(findings) == 1
    assert findings[0].column == "age"


def test_not_null_with_default_is_safe():
    schema = mg_parser.Schema()
    _apply(schema, "CREATE TABLE t (id INT);")
    before = schema.clone()
    changes = _apply(schema, "ALTER TABLE t ADD COLUMN age INT NOT NULL DEFAULT 0;")
    findings = not_null_no_default.check(changes, before, schema)
    assert findings == []


def test_not_null_on_new_table_is_safe():
    schema = mg_parser.Schema()
    before = schema.clone()
    changes = _apply(schema, "CREATE TABLE t (id INT NOT NULL);")
    findings = not_null_no_default.check(changes, before, schema)
    assert findings == []


def test_set_not_null_without_default_on_existing_column():
    schema = mg_parser.Schema()
    _apply(schema, "CREATE TABLE t (id INT, email VARCHAR(255));")
    before = schema.clone()
    changes = _apply(schema, "ALTER TABLE t ALTER COLUMN email SET NOT NULL;")
    findings = not_null_no_default.check(changes, before, schema)
    assert len(findings) == 1
