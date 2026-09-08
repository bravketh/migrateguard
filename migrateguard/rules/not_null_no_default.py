"""Flags NOT NULL constraints added to an existing (assumed non-empty) table
without a default — the classic "migration fails on the existing rows" bug.

Columns added by a CREATE TABLE are exempt: a table being created has no
existing rows to violate the constraint.
"""
from migrateguard.rules import Finding

RULE_ID = "not-null-no-default"


def check(changes, before, after) -> list[Finding]:
    findings: list[Finding] = []
    for change in changes:
        if change.op == "add_column" and not change.details["table_created"]:
            if not change.details["nullable"] and not change.details["has_default"]:
                findings.append(Finding(
                    rule=RULE_ID, table=change.table, column=change.details["column"],
                    message=f"Column '{change.details['column']}' was added to existing "
                            f"table '{change.table}' as NOT NULL with no DEFAULT; this "
                            f"will fail if the table has any rows.",
                ))
        elif change.op == "alter_column_nullability" and not change.details["nullable"]:
            before_table = before.get_table(change.table)
            before_col = before_table.columns.get(change.details["column"]) if before_table else None
            has_default = before_col.has_default if before_col else False
            if not has_default:
                findings.append(Finding(
                    rule=RULE_ID, table=change.table, column=change.details["column"],
                    message=f"Column '{change.details['column']}' on table '{change.table}' "
                            f"was changed to NOT NULL with no DEFAULT; this will fail if any "
                            f"existing rows have a NULL value.",
                ))
    return findings
