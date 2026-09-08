"""Flags removed indexes and unique constraints, which can silently degrade
query performance or drop uniqueness guarantees that live queries rely on."""
from migrateguard.rules import Finding

RULE_ID = "removed-index"


def check(changes, before, after) -> list[Finding]:
    findings: list[Finding] = []
    for change in changes:
        if change.op == "drop_index":
            findings.append(Finding(
                rule=RULE_ID, table=change.table, column=None,
                message=f"Index '{change.details['index']}' was dropped"
                        + (f" from table '{change.table}'." if change.table else "."),
            ))
        elif change.op == "drop_constraint":
            findings.append(Finding(
                rule=RULE_ID, table=change.table, column=None,
                message=f"Constraint '{change.details['constraint']}' was dropped"
                        + (f" from table '{change.table}'." if change.table else "")
                        + " (may have enforced a unique index).",
            ))
    return findings
