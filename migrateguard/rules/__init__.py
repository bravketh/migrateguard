"""Breaking-change detection rules.

Each rule module exposes RULE_ID (str) and check(changes, before, after) -> list[Finding].
`changes` is the list of parser.Change produced by parsing one migration file;
`before`/`after` are parser.Schema snapshots taken immediately before and after
that migration was applied.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Finding:
    rule: str
    table: str
    message: str
    column: Optional[str] = None
    severity: str = "breaking"
