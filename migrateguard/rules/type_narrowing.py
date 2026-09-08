"""Flags column type changes that can silently truncate or reject existing data."""
from migrateguard.rules import Finding

RULE_ID = "type-narrowing"

# Wider value first. Types not listed are compared only by their length/precision params.
_INT_RANK = ["SMALLINT", "INT", "INTEGER", "BIGINT"]
_UNBOUNDED_TEXT = {"TEXT"}
_BOUNDED_TEXT = {"VARCHAR", "CHAR", "CHARACTER", "VARYING"}


def _is_narrowing(old, new) -> bool:
    old_name, new_name = old.name, new.name

    if old_name in _INT_RANK and new_name in _INT_RANK:
        return _INT_RANK.index(new_name) < _INT_RANK.index(old_name)

    if old_name in _UNBOUNDED_TEXT and new_name in _BOUNDED_TEXT:
        return True

    if old_name in _BOUNDED_TEXT and new_name in _BOUNDED_TEXT:
        if old.params and new.params:
            return new.params[0] < old.params[0]
        return False

    if old_name in ("DECIMAL", "NUMERIC") and new_name in ("DECIMAL", "NUMERIC"):
        if old.params and new.params:
            return new.params[0] < old.params[0]
        return False

    if old_name == "DOUBLE" and new_name == "FLOAT":
        return True

    return False


def check(changes, before, after) -> list[Finding]:
    findings: list[Finding] = []
    for change in changes:
        if change.op != "alter_column_type":
            continue
        old_type = change.details["old_type"]
        new_type = change.details["new_type"]
        if _is_narrowing(old_type, new_type):
            findings.append(Finding(
                rule=RULE_ID, table=change.table, column=change.details["column"],
                message=f"Column '{change.details['column']}' on table '{change.table}' "
                        f"narrowed from {old_type.sql or old_type.name} to "
                        f"{new_type.sql or new_type.name}; existing values may not fit.",
            ))
    return findings
