"""Regression tests for Alembic migration metadata."""

from __future__ import annotations

import ast
from pathlib import Path

MIGRATION_VERSION_MAX_LENGTH = 32
MIGRATION_VERSION_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _constant_assignment(module_ast: ast.Module, name: str) -> str | None:
    """Return a string module-level assignment without importing the migration."""

    for node in module_ast.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
        if isinstance(node.value, ast.Constant) and node.value.value is None:
            return None
    raise AssertionError(f"Migration is missing {name!r}.")


def test_migration_revision_ids_fit_postgresql_alembic_version_column() -> None:
    """Alembic stores revision IDs in a varchar(32) column on PostgreSQL."""

    revisions: dict[str, str] = {}
    down_revisions: dict[str, str | None] = {}
    for migration_path in sorted(MIGRATION_VERSION_DIR.glob("*.py")):
        module_ast = ast.parse(migration_path.read_text(encoding="utf-8"), filename=str(migration_path))
        revision = _constant_assignment(module_ast, "revision")
        down_revision = _constant_assignment(module_ast, "down_revision")
        assert revision is not None
        assert len(revision) <= MIGRATION_VERSION_MAX_LENGTH, migration_path.name
        revisions[revision] = migration_path.name
        down_revisions[revision] = down_revision

    for revision, down_revision in down_revisions.items():
        if down_revision is None:
            continue
        assert down_revision in revisions, f"{revision} points at missing down_revision {down_revision}"
