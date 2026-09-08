"""Structural SQL migration parser.

Applies a sequence of DDL statements to an in-memory schema model and
records each structural change as a `Change`, so that detection rules
can reason about what a migration actually did rather than re-deriving
it from a before/after diff.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Optional

import sqlglot
from sqlglot import exp


@dataclass
class TypeInfo:
    name: str
    params: list[int] = field(default_factory=list)
    sql: str = ""


@dataclass
class Column:
    name: str
    type_info: TypeInfo
    nullable: bool = True
    has_default: bool = False


@dataclass
class Index:
    name: str
    table: str
    columns: list[str]
    unique: bool = False


@dataclass
class Table:
    name: str
    columns: dict[str, Column] = field(default_factory=dict)
    indexes: dict[str, Index] = field(default_factory=dict)


@dataclass
class Schema:
    tables: dict[str, Table] = field(default_factory=dict)

    def clone(self) -> "Schema":
        return copy.deepcopy(self)

    def get_table(self, name: str) -> Optional[Table]:
        return self.tables.get(name)


@dataclass
class Change:
    """One structural effect of a single migration statement."""

    op: str
    table: str
    details: dict[str, Any] = field(default_factory=dict)


class MigrationParseError(Exception):
    pass


def _type_info(dtype: Optional[exp.DataType], dialect: str) -> TypeInfo:
    if dtype is None:
        return TypeInfo(name="UNKNOWN")
    name = dtype.this.value if hasattr(dtype.this, "value") else str(dtype.this)
    params: list[int] = []
    for e in dtype.expressions:
        literal = e.this if isinstance(e, exp.DataTypeParam) else e
        try:
            params.append(int(literal.this))
        except (TypeError, ValueError, AttributeError):
            pass
    return TypeInfo(name=name.upper(), params=params, sql=dtype.sql(dialect=dialect))


def _column_from_def(coldef: exp.ColumnDef, dialect: str) -> Column:
    name = coldef.this.name
    type_info = _type_info(coldef.kind, dialect)
    nullable = True
    has_default = False
    for constraint in coldef.constraints or []:
        kind = constraint.kind
        if isinstance(kind, exp.NotNullColumnConstraint):
            nullable = False
        elif isinstance(kind, exp.PrimaryKeyColumnConstraint):
            nullable = False
        elif isinstance(kind, exp.DefaultColumnConstraint):
            has_default = True
    return Column(name=name, type_info=type_info, nullable=nullable, has_default=has_default)


def _index_columns(index_expr: exp.Index) -> list[str]:
    params = index_expr.args.get("params")
    if params is None:
        return []
    cols = []
    for c in params.args.get("columns") or []:
        cols.append(c.name)
    return cols


def _apply_create(schema: Schema, stmt: exp.Create, dialect: str, changes: list[Change]) -> None:
    kind = stmt.args.get("kind")
    if kind == "TABLE":
        schema_expr = stmt.this
        table_name = schema_expr.this.name
        table = Table(name=table_name)
        for e in schema_expr.expressions:
            if isinstance(e, exp.ColumnDef):
                col = _column_from_def(e, dialect)
                table.columns[col.name] = col
            elif isinstance(e, exp.PrimaryKey):
                for pk_col in e.expressions:
                    cname = pk_col.name
                    if cname in table.columns:
                        table.columns[cname].nullable = False
        schema.tables[table_name] = table
        changes.append(Change(op="create_table", table=table_name, details={"columns": list(table.columns)}))
        for col in table.columns.values():
            changes.append(Change(
                op="add_column", table=table_name,
                details={"column": col.name, "table_created": True, "nullable": col.nullable, "has_default": col.has_default},
            ))
    elif kind == "INDEX":
        index_expr = stmt.this
        index_name = index_expr.this.name
        table_ref = index_expr.args.get("table")
        table_name = table_ref.name if table_ref else None
        columns = _index_columns(index_expr)
        table = schema.tables.get(table_name)
        if table is not None:
            table.indexes[index_name] = Index(name=index_name, table=table_name, columns=columns, unique=bool(stmt.args.get("unique")))
        changes.append(Change(op="create_index", table=table_name or "", details={"index": index_name, "columns": columns, "unique": bool(stmt.args.get("unique"))}))


def _apply_drop(schema: Schema, stmt: exp.Drop, changes: list[Change]) -> None:
    kind = stmt.args.get("kind")
    targets = stmt.args.get("tables") or []
    for target in targets:
        name = target.name
        if kind == "TABLE":
            if name in schema.tables:
                del schema.tables[name]
            changes.append(Change(op="drop_table", table=name, details={}))
        elif kind == "INDEX":
            owning_table = None
            for t in schema.tables.values():
                if name in t.indexes:
                    owning_table = t
                    break
            if owning_table is not None:
                del owning_table.indexes[name]
            changes.append(Change(op="drop_index", table=owning_table.name if owning_table else "", details={"index": name}))
        elif kind == "CONSTRAINT":
            changes.append(Change(op="drop_constraint", table="", details={"constraint": name}))


def _apply_alter_action(schema: Schema, table: Optional[Table], table_name: str, action: exp.Expression, dialect: str, changes: list[Change]) -> None:
    if isinstance(action, exp.ColumnDef):
        col = _column_from_def(action, dialect)
        if table is not None:
            table.columns[col.name] = col
        changes.append(Change(
            op="add_column", table=table_name,
            details={"column": col.name, "table_created": False, "nullable": col.nullable, "has_default": col.has_default},
        ))
    elif isinstance(action, exp.Drop):
        drop_kind = action.args.get("kind")
        for target in action.args.get("tables") or []:
            name = target.name
            if drop_kind == "COLUMN":
                if table is not None:
                    table.columns.pop(name, None)
                changes.append(Change(op="drop_column", table=table_name, details={"column": name}))
            elif drop_kind == "CONSTRAINT":
                changes.append(Change(op="drop_constraint", table=table_name, details={"constraint": name}))
    elif isinstance(action, exp.RenameColumn):
        old_name = action.this.name
        new_name = action.args["to"].name
        if table is not None and old_name in table.columns:
            col = table.columns.pop(old_name)
            col.name = new_name
            table.columns[new_name] = col
        changes.append(Change(op="rename_column", table=table_name, details={"from": old_name, "to": new_name}))
    elif isinstance(action, exp.AlterRename):
        new_name = action.this.name
        if table is not None:
            del schema.tables[table_name]
            table.name = new_name
            schema.tables[new_name] = table
        changes.append(Change(op="rename_table", table=table_name, details={"from": table_name, "to": new_name}))
    elif isinstance(action, exp.AlterColumn):
        col_name = action.this.name
        col = table.columns.get(col_name) if table is not None else None
        if action.args.get("dtype") is not None:
            new_type = _type_info(action.args["dtype"], dialect)
            old_type = col.type_info if col is not None else TypeInfo(name="UNKNOWN")
            if col is not None:
                col.type_info = new_type
            changes.append(Change(
                op="alter_column_type", table=table_name,
                details={"column": col_name, "old_type": old_type, "new_type": new_type},
            ))
        elif "allow_null" in action.args:
            # SET NOT NULL -> drop=False, allow_null=False; DROP NOT NULL -> drop=True, allow_null=True
            nullable = bool(action.args.get("drop"))
            if col is not None:
                col.nullable = nullable
            changes.append(Change(op="alter_column_nullability", table=table_name, details={"column": col_name, "nullable": nullable}))
    elif isinstance(action, exp.AddConstraint):
        for constraint in action.expressions:
            constraint_name = constraint.this.name if isinstance(constraint, exp.Constraint) else None
            for sub in (constraint.expressions if isinstance(constraint, exp.Constraint) else [constraint]):
                if isinstance(sub, exp.UniqueColumnConstraint):
                    schema_expr = sub.this
                    cols = [c.name for c in (schema_expr.expressions if schema_expr is not None else [])]
                    if table is not None and constraint_name:
                        table.indexes[constraint_name] = Index(name=constraint_name, table=table_name, columns=cols, unique=True)
                    changes.append(Change(op="add_unique_constraint", table=table_name, details={"constraint": constraint_name, "columns": cols}))


def _apply_alter(schema: Schema, stmt: exp.Alter, dialect: str, changes: list[Change]) -> None:
    table_name = stmt.this.name
    table = schema.tables.get(table_name)
    for action in stmt.args.get("actions") or []:
        _apply_alter_action(schema, table, table_name, action, dialect, changes)
        table = schema.tables.get(table.name if table is not None else table_name, table)


def apply_migration(schema: Schema, sql: str, dialect: str = "postgres") -> list[Change]:
    """Apply a migration's SQL to `schema` in place, returning the structural changes."""
    changes: list[Change] = []
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except Exception as exc:  # sqlglot raises its own ParseError subclasses
        raise MigrationParseError(str(exc)) from exc

    for stmt in statements:
        if stmt is None:
            continue
        if isinstance(stmt, exp.Create):
            _apply_create(schema, stmt, dialect, changes)
        elif isinstance(stmt, exp.Drop):
            _apply_drop(schema, stmt, changes)
        elif isinstance(stmt, exp.Alter):
            _apply_alter(schema, stmt, dialect, changes)
        # Statements we don't model structurally (INSERT, comments, etc.) are ignored.
    return changes
