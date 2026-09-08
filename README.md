# MigrateGuard

A CI-integrated static analysis tool that catches backward-incompatible SQL
migrations before they ship.

Most teams only discover a breaking schema change — a dropped column, a
narrowed type, a removed index a live query depends on — when it causes an
outage in production. MigrateGuard parses your migration files, builds the
schema they produce, and flags risky changes on every pull request.

## What it catches (MVP: PostgreSQL)

- Dropped or renamed columns/tables
- Type narrowing (e.g. `VARCHAR(255)` → `VARCHAR(50)`, `BIGINT` → `INT`)
- Removed indexes or unique constraints
- New `NOT NULL` columns without a default on an existing table

## How it works

MigrateGuard reads every `.sql` file in a migrations directory in order and
replays it against an in-memory schema model (using [sqlglot](https://github.com/tobymao/sqlglot)
to parse the DDL). Each migration is checked against the schema state
immediately before it ran, so a rule sees exactly what that one file
changed — not just a diff of the final state.

## Install

```bash
pip install -e .
```

## CLI usage

```bash
migrateguard check path/to/migrations/
```

Exits `0` with no breaking changes found, `1` otherwise. Add `--json` for
machine-readable output, or `--dialect` to target a different SQL dialect
(currently only `postgres` is exercised by the rule set).

```
$ migrateguard check migrations/
⚠ 0005_drop_legacy_column.sql
    [dropped-column] users.legacy_id: Column 'legacy_id' was dropped from table 'users'.
```

## Migration file conventions

MigrateGuard looks for `*.sql` files in the given directory, sorted
lexicographically (so numeric/timestamp-prefixed filenames apply in the
right order — the style Django, Rails, Alembic, and Flyway generators all
produce). Files ending in `.down.sql` (rollback migrations, golang-migrate
style) are skipped since only the forward direction affects the resulting
schema.

## CI integration

[`.github/workflows/migrateguard.yml`](.github/workflows/migrateguard.yml)
runs on every pull request that touches a `migrations/` folder, posts a
summary comment on the PR, and fails the check — unless the PR carries the
`migration-override` label.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Roadmap

- Dependency graph: scan raw SQL queries and ORM model files for references
  to a flagged column/table, so a finding also shows what downstream code
  breaks.
- Additional dialects (MySQL, SQLite).
