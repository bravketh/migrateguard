"""Flags dropped or renamed tables/columns.

A rename looks like a delete to any code still selecting the old name, so it
is treated as breaking in the same way a drop is.
"""
from migrateguard.rules import Finding

RULE_ID = "dropped-column"


def check(changes, before, after) -> list[Finding]:
    findings: list[Finding] = []
    for change in changes:
        if change.op == "drop_table":
            findings.append(Finding(
                rule=RULE_ID, table=change.table,
                message=f"Table '{change.table}' was dropped.",
            ))
        elif change.op == "rename_table":
            findings.append(Finding(
                rule=RULE_ID, table=change.details["from"],
                message=f"Table '{change.details['from']}' was renamed to "
                        f"'{change.details['to']}'.",
            ))
        elif change.op == "drop_column":
            findings.append(Finding(
                rule=RULE_ID, table=change.table, column=change.details["column"],
                message=f"Column '{change.details['column']}' was dropped from "
                        f"table '{change.table}'.",
            ))
        elif change.op == "rename_column":
            findings.append(Finding(
                rule=RULE_ID, table=change.table, column=change.details["from"],
                message=f"Column '{change.details['from']}' on table '{change.table}' "
                        f"was renamed to '{change.details['to']}'.",
            ))
    return findings
