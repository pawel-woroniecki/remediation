#!/usr/bin/env python3
from __future__ import annotations
from google.api_core.exceptions import Forbidden, NotFound, PermissionDenied
from google.cloud import bigquery, storage
from concurrent.futures import ThreadPoolExecutor, as_completed

import argparse
import yaml
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
import base64
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CURL = "curl"
TEXT_SUFFIXES = {".sql", ".yml", ".yaml", ".py", ".txt", ".md", ".json"}

REPORTS_GCS_BUCKET_DEFAULT = "to-be-added-later"


def log(severity: str, message: str, **extra) -> None:
    print(json.dumps({"severity": severity, "message": message, **extra}, default=str), flush=True)


@dataclass
class SourceBqObject:
    """Normalized representation of one source-side BQ object assembled from DDL files."""
    object_name: str
    dataset: str | None = None
    object_type: str = "unknown"
    source_kind: str = "bq"
    files: list[str] = field(default_factory=list)
    sql_fragments: list[str] = field(default_factory=list)
    columns: dict[str, str] = field(default_factory=dict)
    multi_statement: bool = False
    drop_cols: list[str] = field(default_factory=list)
    rename_pairs: list[tuple[str, str]] = field(default_factory=list)
    type_changes: dict[str, str] = field(default_factory=dict)
    is_ctas: bool = False
    # Ordered ADD/DROP column operations from ALTER TABLE files.
    # Each entry is ('add', col_name, data_type) or ('drop', col_name).
    # Stored in file-processing order so that a v1 DROP followed by a v2 ADD
    # of the same column is replayed correctly (v1 drop is a no-op on the base
    # columns, v2 add then adds the column).
    alter_col_ops: list[tuple] = field(default_factory=list)


def default_gcloud_path() -> str:
    """Build the default local gcloud path from the current user profile."""
    return "gcloud"


def default_gcs_temp_root() -> str:
    """Use a short path by default to avoid Windows path-length issues during GCS staging."""
    return "/tmp"


def default_output_dir() -> str:
    if os.environ.get("OUTPUT_DIR"):
        return os.environ["OUTPUT_DIR"]
    path = Path(__file__).resolve()
    return str(path.parents[2] / "outputs") if len(path.parents) > 2 else str(path.parent / "outputs")


def default_nexus_repository(project_name: str) -> str:
    """Build the default Nexus repository path for the selected data product."""
    return f"raw-snapshots_hosted/fastoss_b/ndl_core/{project_name}"


def run_command(args: list[str], *, cwd: str | None = None, check: bool = True, env: dict | None = None) -> str:
    """Run a subprocess and return stdout, raising a detailed error on failure."""
    proc = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(args)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout


def ensure_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")


class BranchNotFoundError(Exception):
    """Raised when the requested git ref does not exist on the repo's remote."""


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def md5_base64_bytes(content: bytes) -> str:
    return base64.b64encode(hashlib.md5(content).digest()).decode("ascii")


def normalize_sql(sql: str) -> str:
    """Normalize SQL for semantic comparison by removing formatting-only differences."""
    sql = sql.replace("\r\n", "\n")
    sql = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    sql = sql.replace("`", "")
    sql = re.sub(r"\s+", " ", sql)
    return sql.strip().lower().rstrip(";").strip()


def _strip_outer_parens(sql: str) -> str:
    """Strip one layer of outer parentheses if the entire body is wrapped in ( … ).

    BQ INFORMATION_SCHEMA returns view bodies without the outer parens that some DDL
    files add: CREATE VIEW … AS (SELECT …). Only strips when the opening paren pairs
    with the very last character, so inner parens in subqueries are never touched.
    """
    if not (sql.startswith("(") and sql.endswith(")")):
        return sql
    depth = 0
    for i, ch in enumerate(sql):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth == 0 and i < len(sql) - 1:
            return sql  # outer paren closes before the end — not a simple wrapper
    return sql[1:-1].strip()


def strip_create_as_header(sql: str) -> str:
    """Remove CREATE [OR REPLACE] [MATERIALIZED] VIEW|TABLE ... AS header, leaving the body."""
    body = _CREATE_AS_HEADER_RE.sub("", sql, count=1).strip()
    return _strip_outer_parens(body)


def strip_redundant_project_qualifiers(sql: str, project_id: str) -> str:
    """Drop current-project qualifiers BigQuery may inject when returning canonical DDL."""
    if not sql:
        return sql
    escaped = re.escape(project_id)
    patterns = [
        rf"`{escaped}\.([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)`",
        rf"\b{escaped}\.([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)\b",
    ]
    result = sql
    for pattern in patterns:
        result = re.sub(pattern, r"\1", result)
    return result


_BQ_TYPE_ALIASES: dict[str, str] = {
    # Integer family — BigQuery stores all as INT64
    "INTEGER": "INT64", "INT": "INT64", "SMALLINT": "INT64",
    "TINYINT": "INT64", "BYTEINT": "INT64", "BIGINT": "INT64",
    # Float family
    "FLOAT": "FLOAT64",
    # Boolean family
    "BOOLEAN": "BOOL",
    # Numeric family
    "DECIMAL": "NUMERIC", "BIGDECIMAL": "BIGNUMERIC",
    # STRUCT family — INFORMATION_SCHEMA returns "RECORD" for STRUCT columns
    "STRUCT": "RECORD",
}


def canonical_bq_data_type(dtype: str) -> str:
    """Resolve BigQuery column type aliases to their canonical names.

    INFORMATION_SCHEMA always returns canonical names (INT64, BOOL, …) while DDL
    files may use the accepted aliases (INTEGER, BOOLEAN, …).  Normalise both
    sides before comparing so aliases never produce false type_mismatch findings.

    STRUCT<...> parameters are stripped before lookup so that a DDL type like
    "STRUCT<topic STRING, partition INT64>" normalises to "RECORD" (the form
    INFORMATION_SCHEMA returns), preventing false schema_mismatch findings.
    """
    key = dtype.split("<")[0].upper().strip()
    return _BQ_TYPE_ALIASES.get(key, key)


def canonical_object_type(value: str | None) -> str:
    """Map equivalent BigQuery type labels to one canonical comparison value."""
    normalized = (value or "").strip().lower().replace(" ", "_")
    aliases = {
        "table": "table",
        "base_table": "table",
        "view": "view",
        "materialized_view": "materialized_view",
        "procedure": "procedure",
        "stored_procedure": "procedure",
        "function": "function",
        "scalar_function": "function",
        "table_function": "function",
        "external": "external",
    }
    return aliases.get(normalized, normalized)


def normalize_text_content(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n")


def export_git_ref(repo_path: Path, git_ref: str, destination: Path) -> None:
    """Export a clean repository snapshot without modifying the working tree."""
    # Use the remote-tracking ref, not a bare branch name: clone_fastoss_b.py only
    # checks out a local branch for whatever GitLab reports as the repo's default
    # branch. For any other branch (e.g. "production" on a repo whose default
    # branch is "main"), only origin/<branch> exists locally — a bare branch name
    # would fail with "not a valid object name".
    remote_ref = f"origin/{git_ref}"

    # Some repos (e.g. staging/demo projects) never had this branch at all — that's
    # an expected state, not a script bug. Check upfront so the caller can record a
    # clean "skipped" outcome instead of an unhandled git failure.
    exists = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "--verify", "--quiet", remote_ref],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0
    if not exists:
        raise BranchNotFoundError(f"{remote_ref} does not exist in {repo_path}")

    archive_path = destination / "source.zip"
    run_command(["git", "-C", str(repo_path), "archive", "--format=zip", remote_ref, "-o", str(archive_path)])
    with zipfile.ZipFile(archive_path, "r") as zip_handle:
        zip_handle.extractall(destination / "snapshot")


def download_nexus_zip(
    curl_path: str,
    output_file: Path,
    url: str,
    username: str,
    password: str,
) -> None:
    run_command(
        [
            curl_path,
            "-f",
            "-sS",
            "-u",
            f"{username}:{password}",
            "-o",
            str(output_file),
            url,
        ]
    )


def stage_source_snapshot(args: argparse.Namespace, workdir: Path) -> Path:
    """Prepare the rendered source snapshot from either Git or Nexus release archives."""
    if args.source_mode == "branch":
        export_git_ref(Path(args.repo_path), args.git_ref, workdir)
        return workdir / "snapshot"

    if not args.nexus_version:
        raise ValueError("--nexus-version is required when --source-mode nexus is used")
    if not args.nexus_user or not args.nexus_password:
        raise ValueError("Nexus mode requires --nexus-user and --nexus-password")

    snapshot_dir = workdir / "snapshot"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    suffixes = ("bq", "dbt", "python")
    for suffix in suffixes:
        zip_name = f"{args.project_name}_{args.nexus_version}_{suffix}.zip"
        url = f"{args.nexus_base_url.rstrip('/')}/repository/{args.nexus_repository.strip('/')}/{args.nexus_env}/{zip_name}"
        zip_path = workdir / zip_name
        download_nexus_zip(args.curl_path, zip_path, url, args.nexus_user, args.nexus_password)
        with zipfile.ZipFile(zip_path, "r") as zip_handle:
            zip_handle.extractall(snapshot_dir)
    return snapshot_dir


def extract_yaml_like_block(text: str, block_name: str, indent: int = 0) -> str:
    pattern = re.compile(
        rf"(?ms)^{' ' * indent}{re.escape(block_name)}:\s*\n(?P<body>(?:^(?:{' ' * (indent + 2)}).*\n?)*)"
    )
    match = pattern.search(text)
    return match.group("body") if match else ""


def parse_simple_variables(block_text: str, indent: int) -> dict[str, str]:
    variables: dict[str, str] = {}
    for raw_line in block_text.splitlines():
        if not raw_line.startswith(" " * indent):
            continue
        stripped = raw_line[indent:]
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        variables[key.strip()] = value.strip().strip('"')
    return variables


def load_prod_gitlab_settings(snapshot_dir: Path) -> dict[str, str]:
    """Extract production deployment settings from the product's GitLab CI file."""
    ci_path = snapshot_dir / ".gitlab-ci.yml"
    if not ci_path.exists():
        return {}
    text = ci_path.read_text(encoding="utf-8", errors="replace")
    top_variables = parse_simple_variables(extract_yaml_like_block(text, "variables", indent=0), indent=2)
    merged = dict(top_variables)
    for job_name in ("deploy_to_prod_bq", "deploy_to_prod_dbt", "deploy_to_prod_python"):
        prod_job = extract_yaml_like_block(text, job_name, indent=0)
        if not prod_job:
            continue
        job_variables = parse_simple_variables(extract_yaml_like_block(prod_job, "variables", indent=2), indent=4)
        merged.update(job_variables)
    return merged


def apply_substitutions(snapshot_dir: Path, replacements: dict[str, str]) -> None:
    """Apply CI/CD-style token replacement across bq, dbt, and python source trees."""
    for root_name in ("bq", "dbt", "python"):
        root = snapshot_dir / root_name
        if not root.exists():
            continue
        for file_path in root.rglob("*"):
            if not file_path.is_file() or file_path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            content = file_path.read_text(encoding="utf-8", errors="replace")
            original = content
            for token, value in replacements.items():
                content = content.replace(token, value)
            if content != original:
                file_path.write_text(content, encoding="utf-8")


# Strips the full CREATE [OR REPLACE] [MATERIALIZED] VIEW|TABLE … AS header,
# including optional column-description blocks, OPTIONS clauses, and IF NOT EXISTS.
# The lookahead also allows ( to handle bodies wrapped in parentheses:
#   CREATE VIEW … AS (SELECT …)  — BQ INFORMATION_SCHEMA returns the body without parens.
_CREATE_AS_HEADER_RE = re.compile(
    r"^\s*create\s+(?:or\s+replace\s+)?(?:materialized\s+)?(?:view|table)\s+.*?\bas\s+(?=\(|select\b|with\b|--)",
    re.IGNORECASE | re.DOTALL,
)

# Detects CTAS tables (CREATE TABLE … AS SELECT/WITH) — these have no column definitions.
_CTAS_RE = re.compile(
    r"create\s+(?:or\s+replace\s+)?table\s+.*?\bas\s+(?:select|with)\b",
    re.IGNORECASE | re.DOTALL,
)

# Matches RENAME TO in ALTER TABLE statements — used to skip "old name" from inventory.
# Skips optional project. and dataset. qualifiers so the captured new_name is always
# just the table identifier, regardless of how many qualifiers precede it.
_RENAME_TO_RE = re.compile(
    r"\brename\s+to\s+(?:`?[\w\-]+`?\.)*`?(?P<new_name>[\w\-]+)`?",
    re.IGNORECASE,
)

# ALTER TABLE pattern reused in build_source_bq_inventory.
_ALTER_TABLE_RE = re.compile(
    r"alter\s+table\s+`?(?:(?:[\w\-]+)\.)?(?P<dataset>[\w\-]+)\.(?P<object>[\w\-]+)`?",
    re.IGNORECASE,
)

# DROP TABLE — used to exclude transient tables (created and dropped in the same file,
# e.g. inside a stored-procedure body) from the persistent inventory.
_DROP_TABLE_RE = re.compile(
    r"\bdrop\s+table\s+(?:if\s+exists\s*)?`?(?:(?:[\w\-]+)`?\.`?)*(?P<obj>[\w\-]+)`?",
    re.IGNORECASE,
)

# Matches a bare SELECT * FROM <table> view body (no WHERE/JOIN/GROUP BY etc.).
# GCP sometimes stores the expanded column list for a view defined with SELECT *,
# making the string comparison fail even though the definitions are semantically
# equivalent. We suppress definition_mismatch for this pattern.
_SELECT_STAR_VIEW_RE = re.compile(
    r"^select\s+\*\s+from\s+[\w.\-`]+(\s+(?:as\s+)?[\w`]+)?\s*$",
    re.IGNORECASE,
)


def extract_all_bq_targets(sql: str) -> list[tuple[str | None, str, str]]:
    """Return every CREATE DDL target found in sql as (dataset, object_name, object_type).

    ALTER TABLE is intentionally excluded — it is processed separately in
    build_source_bq_inventory so that it can update an existing entry's columns
    without being treated as a standalone object definition.
    Files with no CREATE DDL (MERGE, INSERT, DROP scripts) return an empty list
    and are skipped by the caller.
    """
    patterns = [
        (r"create\s+(?:or\s+replace\s+)?materialized\s+view\s+(?:if\s+not\s+exists\s+)?`?(?:(?:[\w\-]+)\.)?(?P<ds>[\w\-]+)\.(?P<obj>[\w\-]+)`?", "materialized_view"),
        (r"create\s+(?:or\s+replace\s+)?view\s+(?:if\s+not\s+exists\s+)?`?(?:(?:[\w\-]+)\.)?(?P<ds>[\w\-]+)\.(?P<obj>[\w\-]+)`?", "view"),
        (r"create\s+external\s+table\s+(?:if\s+not\s+exists\s*)?`?(?:(?:[\w\-]+)\.)?(?P<ds>[\w\-]+)\.(?P<obj>[\w\-]+)`?", "external"),
        (r"create\s+(?:or\s+replace\s+)?table\s+(?:if\s+not\s+exists\s*)?`?(?:(?:[\w\-]+)\.)?(?P<ds>[\w\-]+)\.(?P<obj>[\w\-]+)`?", "table"),
        (r"create\s+(?:or\s+replace\s+)?procedure\s+(?:if\s+not\s+exists\s*)?`?(?:(?:[\w\-]+)\.)?(?P<ds>[\w\-]+)\.(?P<obj>[\w\-]+)`?", "procedure"),
        (r"create\s+(?:or\s+replace\s+)?function\s+(?:if\s+not\s+exists\s*)?`?(?:(?:[\w\-]+)\.)?(?P<ds>[\w\-]+)\.(?P<obj>[\w\-]+)`?", "function"),
    ]
    seen: set[tuple[str | None, str]] = set()
    results: list[tuple[str | None, str, str]] = []
    for pattern, otype in patterns:
        for m in re.finditer(pattern, sql, re.IGNORECASE):
            ds, obj = m.group("ds"), m.group("obj")
            if (ds, obj) not in seen:
                seen.add((ds, obj))
                results.append((ds, obj, otype))
    # Exclude objects that are also explicitly dropped in the same file.
    # Tables created and dropped in one script are transient (e.g. inside a
    # stored-procedure body) and should not appear as persistent inventory objects.
    dropped_names = {m.group("obj") for m in _DROP_TABLE_RE.finditer(sql)}
    if dropped_names:
        results = [(ds, obj, otype) for ds, obj, otype in results if obj not in dropped_names]
    return results


_CREATE_TABLE_BODY_RE = re.compile(
    r"create\s+(?:or\s+replace\s+)?table\s+(?:if\s+not\s+exists\s*)?`?(?:[\w\-]+\.)?[\w\-]+\.[\w\-]+`?\s*\((?P<body>.*?)\)\s*(?:options|partition|cluster|;)",
    re.IGNORECASE | re.DOTALL,
)


def extract_columns_from_create_table(sql: str) -> dict[str, str]:
    # Use finditer so that files with multiple CREATE TABLE statements (e.g. a
    # first statement with the old schema followed by a CREATE TABLE IF NOT EXISTS
    # with the updated schema) are handled correctly — later definitions override
    # earlier ones for the same column name.
    columns: dict[str, str] = {}
    for match in _CREATE_TABLE_BODY_RE.finditer(sql):
        body = match.group("body")
        for raw_line in body.splitlines():
            line = raw_line.strip().rstrip(",")
            if not line or line.startswith("--"):
                continue
            column_match = re.match(r"`?(?P<name>[\w\-]+)`?\s+(?P<dtype>[A-Z0-9_<>,]+)", line, flags=re.IGNORECASE)
            if column_match:
                columns[column_match.group("name")] = column_match.group("dtype").upper()
    return columns


def extract_alter_operations(
    sql: str,
) -> tuple[dict[str, str], list[str], list[tuple[str, str]], dict[str, str]]:
    """Parse ALTER TABLE DDL and return (add_columns, drop_columns, rename_pairs, type_changes)."""
    add_cols: dict[str, str] = {}
    drop_cols: list[str] = []
    rename_pairs: list[tuple[str, str]] = []
    type_changes: dict[str, str] = {}

    for m in re.finditer(
        r"add\s+column(?:\s+if\s+not\s+exists)?\s+`?(?P<name>[\w\-]+)`?\s+(?P<dtype>[A-Z0-9_<>,]+)",
        sql, re.IGNORECASE,
    ):
        add_cols[m.group("name")] = m.group("dtype").upper().rstrip(",")

    for m in re.finditer(
        r"drop\s+column(?:\s+if\s+exists)?\s+`?(?P<name>[\w\-]+)`?",
        sql, re.IGNORECASE,
    ):
        drop_cols.append(m.group("name"))

    for m in re.finditer(
        r"rename\s+column\s+`?(?P<old>[\w\-]+)`?\s+to\s+`?(?P<new>[\w\-]+)`?",
        sql, re.IGNORECASE,
    ):
        rename_pairs.append((m.group("old"), m.group("new")))

    for m in re.finditer(
        r"alter\s+column\s+`?(?P<name>[\w\-]+)`?\s+set\s+data\s+type\s+(?P<dtype>[A-Z0-9_<>,\s]+?)(?:\s+using\b|\s*;|\s*$)",
        sql, re.IGNORECASE | re.MULTILINE,
    ):
        type_changes[m.group("name")] = m.group("dtype").strip().upper()

    return add_cols, drop_cols, rename_pairs, type_changes


def _sql_version_key(path: Path) -> tuple:
    """Sort key for DDL SQL files: (parent_dir, version_number, filename).

    Base files with no _vN suffix get version 0 and always sort before versioned
    files.  Versioned files sort in ascending numeric order (1, 2, 3 … 10, 11 …)
    rather than lexicographically.  This neutralises filename typos that shift a
    _vN file into an unexpected lexicographic position (e.g. celll…_v3.sql
    sorting before cellstatus…_v2.sql because 'l' < 's'), which would otherwise
    cause the base file to incorrectly supersede a later versioned DDL.
    """
    m = re.search(r"_v(\d+)\.sql$", path.name, re.IGNORECASE)
    return (path.parent, int(m.group(1)) if m else 0, path.name)


def build_source_bq_inventory(snapshot_dir: Path) -> tuple[dict[str, SourceBqObject], set[str]]:
    """Build a normalized inventory of source-side BigQuery objects from BQ DDL."""
    inventory: dict[str, SourceBqObject] = {}
    table_renames: list[tuple[str, str]] = []  # (old_name, new_name)
    bq_root = snapshot_dir / "bq"
    if not bq_root.exists():
        return inventory, set()

    for sql_file in sorted(
        (f for f in bq_root.rglob("*") if f.suffix.lower() == ".sql"),
        key=_sql_version_key,
    ):
        # Skip temporary processing scripts (tmp_*) — they create and drop objects
        # within a single run and never leave a permanent object in GCP.
        if sql_file.stem.lower().startswith("tmp_"):
            continue

        sql = sql_file.read_text(encoding="utf-8", errors="replace")
        rel_path = str(sql_file.relative_to(snapshot_dir)).replace("\\", "/")

        targets = extract_all_bq_targets(sql)
        alter_match = _ALTER_TABLE_RE.search(sql)

        # Skip pure DML / MERGE / script files — no DDL of any kind.
        if not targets and not alter_match:
            continue

        # Register every CREATE DDL object found in this file (handles multi-table files).
        is_replace = bool(re.search(
            r"\bcreate\s+(?:or\s+replace\s+)?(?:table|view)(?:\s+if\s+not\s+exists)?\s+",
            sql, re.IGNORECASE,
        ))
        for dataset, object_name, object_type in targets:
            entry = inventory.setdefault(
                object_name,
                SourceBqObject(object_name=object_name, dataset=dataset, object_type=object_type),
            )
            if rel_path not in entry.files:
                entry.files.append(rel_path)
            # A full DDL statement in a later versioned file (e.g. _v2.sql with
            # CREATE TABLE IF NOT EXISTS, or _v1.sql with CREATE OR REPLACE) supersedes
            # the original DDL entirely — replace sql_fragments rather than accumulating.
            if is_replace and len(entry.files) > 1:
                entry.sql_fragments = [sql]
                if object_type == "table":
                    new_cols = extract_columns_from_create_table(sql)
                    entry.columns = new_cols
                    # ALTER TABLE type-changes that predate this CREATE TABLE are superseded;
                    # remove them so the post-processing loop doesn't overwrite the new types.
                    for col in new_cols:
                        entry.type_changes.pop(col, None)
                    entry.is_ctas = bool(_CTAS_RE.search(sql))
            else:
                entry.sql_fragments.append(sql)
                if object_type == "table":
                    entry.columns.update(extract_columns_from_create_table(sql))
                    if _CTAS_RE.search(sql):
                        entry.is_ctas = True
            entry.multi_statement = len(entry.files) > 1
            if dataset and not entry.dataset:
                entry.dataset = dataset
            if entry.object_type == "unknown":
                entry.object_type = object_type

        # Process ALTER TABLE if present.
        if alter_match:
            # RENAME TO: collect the mapping and skip ALTER TABLE processing for
            # the old name. The rename is applied to inventory after all files
            # are processed, so the old entry is replaced by the new name.
            rename_match = _RENAME_TO_RE.search(sql)
            if rename_match:
                table_renames.append((alter_match.group("object"), rename_match.group("new_name")))
                continue
            ds = alter_match.group("dataset")
            obj = alter_match.group("object")
            entry = inventory.setdefault(
                obj,
                SourceBqObject(object_name=obj, dataset=ds, object_type="table"),
            )
            if rel_path not in entry.files:
                entry.files.append(rel_path)
            entry.sql_fragments.append(sql)
            entry.multi_statement = len(entry.files) > 1
            add_cols, drop_cols, rename_pairs, type_changes = extract_alter_operations(sql)
            entry.alter_col_ops.extend(('add', c, t) for c, t in add_cols.items())
            entry.alter_col_ops.extend(('drop', c) for c in drop_cols)
            entry.rename_pairs.extend(rename_pairs)
            entry.type_changes.update(type_changes)
            if ds and not entry.dataset:
                entry.dataset = ds
            if entry.object_type in ("unknown", "alter_table"):
                entry.object_type = "table"

    # Apply TABLE-level renames from ALTER TABLE ... RENAME TO statements.
    # Runs before column-operation transforms so any pending ALTER COLUMN changes
    # on the renamed entry are applied under the correct new key.
    # renamed_away_names tracks the original names so compare_bigquery can suppress
    # false-positive only_in_source findings for dbt models that were renamed away.
    renamed_away_names: set[str] = set()
    for old_name, new_name in table_renames:
        renamed_away_names.add(old_name)
        if old_name in inventory:
            entry = inventory.pop(old_name)
            entry.object_name = new_name
            inventory[new_name] = entry

    # Apply column transforms from ALTER TABLE files in the correct order:
    # 1. RENAME COLUMN first — subsequent ops reference the new name.
    # 2. ALTER col ops (ADD / DROP) replayed in file-processing order — preserves
    #    the sequence "v1 drops column X, v2 re-adds column X" correctly.
    # 3. SET DATA TYPE last — operates on the final post-add/drop column set.
    for entry in inventory.values():
        for old, new in entry.rename_pairs:
            if old in entry.columns:
                entry.columns[new] = entry.columns.pop(old)
        for op in entry.alter_col_ops:
            if op[0] == 'add':
                entry.columns[op[1]] = op[2]
            else:  # 'drop'
                entry.columns.pop(op[1], None)
        for col, new_type in entry.type_changes.items():
            if col in entry.columns:
                entry.columns[col] = new_type

    return inventory, renamed_away_names


def build_source_dbt_inventory(snapshot_dir: Path) -> dict[str, dict[str, Any]]:
    """Inventory dbt model files that can plausibly create BigQuery objects."""
    inventory: dict[str, dict[str, Any]] = {}
    root = snapshot_dir / "dbt"
    if not root.exists():
        return inventory

    def extract_materialization(content: str) -> str | None:
        inline_match = re.search(
            r"config\s*\((?P<body>.*?)\)",
            content,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not inline_match:
            return None
        body = inline_match.group("body")
        materialized_match = re.search(
            r"materialized\s*=\s*['\"](?P<value>[^'\"]+)['\"]",
            body,
            flags=re.IGNORECASE,
        )
        if materialized_match:
            return materialized_match.group("value").strip().lower()
        return None

    for sql_file in sorted(root.rglob("*.sql")):
        if "target" in sql_file.parts:
            continue
        if "models" not in sql_file.parts:
            continue
        content = sql_file.read_text(encoding="utf-8", errors="replace")
        stem_lower = sql_file.stem.lower()
        materialized = extract_materialization(content)
        # Skip tmp_* models unless they explicitly declare materialized='table'.
        # Without an explicit 'table' declaration, project-level dbt_project.yml
        # overrides may make them ephemeral at runtime.
        if stem_lower.startswith("tmp_") and materialized != "table":
            continue
        # A real dbt model always contains Jinja syntax ({{ config(, {{ ref(, {{ source(,
        # or {%...%} control blocks).  Files without any Jinja are plain SQL scripts that
        # happened to land in models/; if they contain top-level DML (UPDATE, INSERT, etc.)
        # they are not deployable SELECT models and must be skipped.
        # Note: files that DO have Jinja (including {{ config( with pre/post hook DML) are
        # real dbt models and are never skipped here — see compare_bigquery for the
        # merge_* materialization guard that handles that category.
        has_jinja = bool(re.search(r"\{\{|\{%", content))
        if not has_jinja and re.search(
            r"\b(?:merge|update|insert|delete|drop)\b", content, re.IGNORECASE
        ):
            continue
        is_dbt_model = bool(re.search(r"\{\{\s*config\s*\(", content, re.IGNORECASE))
        inventory[sql_file.stem] = {
            "object_name": sql_file.stem,
            "relative_path": str(sql_file.relative_to(snapshot_dir)).replace("\\", "/"),
            "sql_hash": sha256_text(normalize_sql(content)),
            "source_kind": "dbt_model",
            "materialized": materialized,
        }
    return inventory


def build_dbt_snapshot_names(snapshot_dir: Path) -> set[str]:
    """Return BQ table names declared as dbt snapshots.

    Searches all *.yml files anywhere under dbt/ whose path contains a
    'snapshots' directory component (e.g. dbt/pl/snapshots/history_link/
    history_link.yml). dbt snapshot objects have no .sql DDL — dbt manages
    the BQ table at runtime — so including them in expected_names suppresses
    spurious only_in_bq findings.
    """
    names: set[str] = set()
    dbt_root = snapshot_dir / "dbt"
    if not dbt_root.exists():
        return names
    for yml_file in sorted(dbt_root.rglob("*.yml")):
        if "snapshots" not in yml_file.parts:
            continue
        try:
            data = yaml.safe_load(yml_file.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        for entry in data.get("snapshots", []):
            name = entry.get("name")
            if name:
                names.add(str(name).lower())
    return names


def build_source_dag_inventory(snapshot_dir: Path) -> dict[str, dict[str, Any]]:
    """Collect DAG ids defined in Python so the report captures generator coverage."""
    inventory: dict[str, dict[str, Any]] = {}
    root = snapshot_dir / "python"
    if not root.exists():
        return inventory
    dag_patterns = [
        re.compile(r'globals\(\)\["(?P<dag_id>[^"]+)"\]'),
        re.compile(r"dag_id\s*=\s*['\"](?P<dag_id>[^'\"]+)['\"]"),
    ]
    for py_file in sorted(root.rglob("*.py")):
        content = py_file.read_text(encoding="utf-8", errors="replace")
        dag_ids: set[str] = set()
        for pattern in dag_patterns:
            dag_ids.update(match.group("dag_id") for match in pattern.finditer(content))
        if dag_ids:
            inventory[str(py_file.relative_to(snapshot_dir)).replace("\\", "/")] = {
                "relative_path": str(py_file.relative_to(snapshot_dir)).replace("\\", "/"),
                "dag_ids": sorted(dag_ids),
            }
    return inventory


def collect_source_files(snapshot_dir: Path) -> dict[str, dict[str, Any]]:
    """Collect rendered dbt/python files for artifact-to-GCS comparison."""
    files: dict[str, dict[str, Any]] = {}
    for top_level in ("dbt", "python"):
        root = snapshot_dir / top_level
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.name == ".gitkeep":
                continue
            relative_path = str(path.relative_to(snapshot_dir)).replace("\\", "/")
            content = path.read_bytes()
            is_text = path.suffix.lower() in TEXT_SUFFIXES
            normalized_hash = (
                sha256_text(normalize_text_content(content.decode("utf-8", errors="replace")))
                if is_text
                else sha256_bytes(content)
            )
            files[relative_path] = {
                "relative_path": relative_path,
                "sha256": sha256_bytes(content),
                "md5_base64": md5_base64_bytes(content),
                "size_bytes": len(content),
                "compare_hash": normalized_hash,
                "is_text": is_text,
            }
    return files


def fetch_bigquery_inventory(
    project_id: str,
    datasets: list[str],
) -> dict[str, dict[str, Any]]:
    """Fetch BigQuery metadata for the selected target project via INFORMATION_SCHEMA views."""
    # location must match where the datasets live; omitting it defaults to US and
    # causes "not found in location US" for EU datasets.
    bq = bigquery.Client(project=project_id, location="europe-west3")
    inventory: dict[str, dict[str, Any]] = {}

    def _q(sql: str) -> list[dict[str, Any]]:
        return [dict(row) for row in bq.query(sql).result()]

    def _q_with_retry(sql: str, max_attempts: int = 10) -> list[dict[str, Any]]:
        for attempt in range(1, max_attempts + 1):
            try:
                return _q(sql)
            except google.api_core.exceptions.BadRequest as exc:
                if "resourcesExceeded" not in str(exc) or attempt == max_attempts:
                    raise
                log("WARNING", "BigQuery resourcesExceeded — retrying after 30s",
                    attempt=attempt, max_attempts=max_attempts)
                time.sleep(30)
        return []  # unreachable

    # Validate each dataset actually exists before querying INFORMATION_SCHEMA.
    # The Dataset API reflects true state faster than the INFORMATION_SCHEMA metadata
    # cache, which can lag after a dataset is deleted and return ghost rows that
    # produce spurious only_in_bq findings.
    live_datasets: list[str] = []
    for ds in datasets:
        try:
            bq.get_dataset(ds)
            live_datasets.append(ds)
        except NotFound:
            log("WARNING",
                "Dataset not found via Dataset API — excluding from INFORMATION_SCHEMA scan",
                project=project_id, dataset=ds)
    datasets = live_datasets

    # Use region-level INFORMATION_SCHEMA so all datasets are covered by 4 queries
    # total instead of 4×N per-dataset queries. Run in parallel (4 workers); each
    # query retries up to 10× on transient resourcesExceeded errors.
    if not datasets:
        return inventory
    ds_filter = ", ".join(f"'{ds}'" for ds in datasets)
    r = f"`{project_id}`.`region-europe-west3`.INFORMATION_SCHEMA"
    region_queries = {
        "tables":   f"SELECT table_schema AS ds, table_name, table_type, ddl FROM {r}.TABLES WHERE table_schema IN ({ds_filter})",
        "columns":  f"SELECT table_schema AS ds, table_name, column_name, data_type FROM {r}.COLUMNS WHERE table_schema IN ({ds_filter})",
        "routines": f"SELECT routine_schema AS ds, routine_name, routine_type, routine_definition FROM {r}.ROUTINES WHERE routine_schema IN ({ds_filter})",
        "views":    f"SELECT table_schema AS ds, table_name, view_definition FROM {r}.VIEWS WHERE table_schema IN ({ds_filter})",
    }

    kind_rows: dict[str, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        future_map = {pool.submit(_q_with_retry, sql): kind for kind, sql in region_queries.items()}
        for future in as_completed(future_map):
            kind = future_map[future]
            try:
                kind_rows[kind] = future.result()
            except (Forbidden, PermissionDenied) as exc:
                raise RuntimeError(
                    f"Permission denied reading {project_id} INFORMATION_SCHEMA. "
                    f"Grant roles/bigquery.metadataViewer and roles/bigquery.jobUser "
                    f"to the runner service account on project {project_id}. "
                    f"Original error: {exc}"
                ) from exc

    # Group rows by dataset so the downstream loop can work dataset-by-dataset.
    by_ds: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for kind, rows in kind_rows.items():
        for row in rows:
            by_ds[row["ds"]][kind].append(row)

    # Datasets with no rows in TABLES are absent from BigQuery (not found or empty).
    not_found_datasets = set(datasets) - set(by_ds.keys())
    for ds in not_found_datasets:
        log("WARNING", "Dataset not found in BigQuery — treating as absent (drift)",
            project=project_id, dataset=ds)

    for dataset in datasets:
        if dataset in not_found_datasets:
            continue
        ds_data      = by_ds[dataset]
        table_rows   = ds_data.get("tables",   [])
        column_rows  = ds_data.get("columns",  [])
        routine_rows = ds_data.get("routines", [])
        view_rows    = ds_data.get("views",    [])

        for row in table_rows:
            key = f"{dataset}.{row['table_name']}"
            inventory[key] = {
                "object_name": row["table_name"],
                "dataset": dataset,
                "object_type": str(row.get("table_type", "unknown")).lower().replace(" ", "_"),
                "columns": {},
                "view_query": None,
                "ddl": row.get("ddl"),
            }

        for row in column_rows:
            table_name = row["table_name"]
            key = f"{dataset}.{table_name}"
            inventory.setdefault(
                key,
                {
                    "object_name": table_name,
                    "dataset": dataset,
                    "object_type": "unknown",
                    "columns": {},
                    "view_query": None,
                    "ddl": None,
                },
            )
            inventory[key]["columns"][row["column_name"]] = row.get("data_type", "")

        for row in view_rows:
            table_name = row["table_name"]
            key = f"{dataset}.{table_name}"
            inventory.setdefault(
                key,
                {
                    "object_name": table_name,
                    "dataset": dataset,
                    "object_type": "view",
                    "columns": {},
                    "view_query": None,
                    "ddl": None,
                },
            )
            inventory[key]["view_query"] = row.get("view_definition")

        for row in routine_rows:
            key = f"{dataset}.{row['routine_name']}"
            inventory[key] = {
                "object_name": row["routine_name"],
                "dataset": dataset,
                "object_type": str(row.get("routine_type", "routine")).lower(),
                "definition_body": row.get("routine_definition"),
                "columns": {},
            }
    return inventory


def stage_gcs_snapshot(
    gcloud_path: str,
    bucket: str,
    project_name: str,
    gcs_prefix: str,
    gcs_temp_root: Path,
) -> tuple[Path, list[str]]:
    """Download deployed dbt/python artifacts from GCS to a short local path for diffing."""
    target_dir = gcs_temp_root / f"{project_name}_gcs_snapshot"
    warnings: list[str] = []
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    # Give each repo its own gcloud config dir so parallel subprocesses don't race
    # over the shared /workspace/.config/gcloud/ and corrupt the active account state.
    gcloud_config_dir = target_dir / ".gcloud"
    gcloud_config_dir.mkdir(parents=True, exist_ok=True)
    gcloud_env = {**os.environ, "CLOUDSDK_CONFIG": str(gcloud_config_dir)}
    resolved_prefix = gcs_prefix.format(project_name=project_name)

    def _download(area: str) -> list[str]:
        area_warns: list[str] = []
        area_target = target_dir / area
        area_target.mkdir(parents=True, exist_ok=True)
        # Each parallel download gets its own gcloud config dir so concurrent
        # token-refresh writes don't race and corrupt each other's state.
        area_config_dir = target_dir / f".gcloud_{area}"
        area_config_dir.mkdir(parents=True, exist_ok=True)
        area_env = {**os.environ, "CLOUDSDK_CONFIG": str(area_config_dir)}
        source_path = f"gs://{bucket}/{resolved_prefix}/{area}"
        try:
            run_command(
                [gcloud_path, "storage", "cp", "--recursive", source_path, str(area_target)],
                env=area_env,
            )
        except RuntimeError as exc:
            if "matched no objects or files" in str(exc):
                area_warns.append(f"GCS path missing: {source_path}")
            else:
                raise
        return area_warns

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_download, area) for area in ("dbt", "python")]
        for f in futures:
            warnings.extend(f.result())

    return target_dir, warnings


def build_gcs_inventory(gcs_snapshot_dir: Path) -> dict[str, dict[str, Any]]:
    """Build a normalized inventory of deployed dbt/python artifacts from local GCS staging."""
    inventory: dict[str, dict[str, Any]] = {}
    for path in sorted(gcs_snapshot_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name == ".gitkeep":
            continue
        relative_path = str(path.relative_to(gcs_snapshot_dir)).replace("\\", "/")
        if relative_path.startswith("dbt/dbt/"):
            relative_path = relative_path[len("dbt/") :]
        if relative_path.startswith("python/python/"):
            relative_path = relative_path[len("python/") :]
        if not (relative_path.startswith("dbt/") or relative_path.startswith("python/")):
            continue
        content = path.read_bytes()
        is_text = path.suffix.lower() in TEXT_SUFFIXES
        compare_hash = (
            sha256_text(normalize_text_content(content.decode("utf-8", errors="replace")))
            if is_text
            else sha256_bytes(content)
        )
        inventory[relative_path] = {
            "relative_path": relative_path,
            "sha256": sha256_bytes(content),
            "md5_base64": md5_base64_bytes(content),
            "size_bytes": len(content),
            "compare_hash": compare_hash,
            "is_text": is_text,
        }
    return inventory


def compare_gcs(source_files: dict[str, dict[str, Any]], gcs_files: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare rendered source artifacts with deployed GCS artifacts."""
    findings: list[dict[str, Any]] = []
    interesting_paths = {
        path for path in set(source_files) | set(gcs_files) if path.startswith("dbt/") or path.startswith("python/")
    }
    for path in sorted(interesting_paths):
        source = source_files.get(path)
        deployed = gcs_files.get(path)
        source_technology = "dbt" if path.startswith("dbt/") else "python" if path.startswith("python/") else "unknown"
        if source and not deployed:
            findings.append(
                {
                    "area": "gcs",
                    "path": path,
                    "status": "only_in_source",
                    "severity": "medium",
                    "source_technology": source_technology,
                    "details": "File exists in rendered source snapshot but not in deployed GCS bucket.",
                }
            )
        elif deployed and not source:
            findings.append(
                {
                    "area": "gcs",
                    "path": path,
                    "status": "only_in_gcs",
                    "severity": "high",
                    "source_technology": source_technology,
                    "details": "File exists in deployed GCS bucket but not in rendered source snapshot.",
                }
            )
        elif source and deployed and source["compare_hash"] != deployed["compare_hash"]:
            findings.append(
                {
                    "area": "gcs",
                    "path": path,
                    "status": "content_mismatch",
                    "severity": "high",
                    "source_technology": source_technology,
                    "details": "File exists in both places but content hash differs.",
                }
            )
    return findings


def compare_bigquery(
    source_bq: dict[str, SourceBqObject],
    source_dbt: dict[str, dict[str, Any]],
    actual_bq: dict[str, dict[str, Any]],
    project_id: str,
    renamed_away_names: set[str] | None = None,
    dbt_snapshot_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Compare source-side BQ/dbt expectations with actual BigQuery objects in the selected target project."""
    renamed_away_names = renamed_away_names or set()
    findings: list[dict[str, Any]] = []

    # actual_bq is keyed by "dataset.table_name" to prevent cross-dataset collisions
    # when multiple datasets share the same table name.  Build unqualified-name helpers
    # for set operations and a name→[entry, …] index for single-entry fallback.
    actual_names: set[str] = set()
    actual_bq_by_name: dict[str, list[dict]] = defaultdict(list)
    for _qk, _entry in actual_bq.items():
        _uname = _qk.split(".", 1)[1] if "." in _qk else _qk
        actual_names.add(_uname)
        actual_bq_by_name[_uname].append(_entry)

    deployable_dbt_names = {
        name for name, model in source_dbt.items()
        if model.get("materialized") != "ephemeral"
        # merge_* dbt models with no explicit materialization use pre/post hooks to
        # write into a *_tgt table; the model itself may or may not create a permanent
        # BQ object depending on project-level dbt_project.yml config.  Only treat
        # them as deployable (and therefore expected in BQ) when BQ actually has them.
        # The materialized value in the file (None, 'table', etc.) is irrelevant —
        # project-level overrides can make even explicit materialized='table' ephemeral
        # at runtime (seen with merge_mw_equipment, merge_mw_links).
        and not (
            name.lower().startswith("merge_")
            and name not in actual_names
        )
    }
    expected_names = set(source_bq) | deployable_dbt_names | (dbt_snapshot_names or set())

    for object_name in sorted((actual_names - expected_names) - renamed_away_names):
        if object_name.lower().startswith("merge_"):
            continue
        actual = actual_bq_by_name[object_name][0]
        findings.append(
            {
                "area": "bigquery",
                "object_name": object_name,
                "dataset": actual.get("dataset"),
                "status": "only_in_bq",
                "severity": "high",
                "source_technology": "unknown",
                "details": (
                    f"Selected GCP environment contains {actual.get('object_type')} "
                    f"with no matching DDL or dbt model in the selected source snapshot."
                ),
            }
        )

    for object_name in sorted((expected_names - actual_names) - renamed_away_names):
        if object_name.lower().startswith("merge_"):
            continue
        # Tables renamed to a "deprecated" name are given an expiration date by convention.
        # After BQ auto-drops them the DDL snapshot is intentionally stale — suppress.
        if "deprecated" in object_name.lower():
            continue
        source_kind = "bq" if object_name in source_bq else "dbt_model"
        details = "Object exists in the selected source snapshot but not in the selected GCP dataset inventory."
        findings.append(
            {
                "area": "bigquery",
                "object_name": object_name,
                "dataset": source_bq.get(object_name).dataset if object_name in source_bq else None,
                "status": "only_in_source",
                "severity": "medium",
                "source_technology": source_kind,
                "details": f"{details} source_kind={source_kind}",
            }
        )

    for object_name in sorted(set(source_bq) & actual_names):
        source = source_bq[object_name]
        # Prefer the dataset the source file declares; fall back to first match.
        if source.dataset:
            actual = actual_bq.get(f"{source.dataset}.{object_name}") or actual_bq_by_name[object_name][0]
        else:
            actual = actual_bq_by_name[object_name][0]
        source_type = canonical_object_type(source.object_type)
        actual_type = canonical_object_type(str(actual.get("object_type", "")))
        if source_type not in {"unknown", "", actual_type}:
            findings.append(
                {
                    "area": "bigquery",
                    "object_name": object_name,
                    "dataset": actual.get("dataset"),
                    "status": "type_mismatch",
                    "severity": "high",
                    "source_technology": source.source_kind,
                    "details": (
                        f"Source type={source.object_type}, "
                        f"selected GCP object type={actual.get('object_type')}."
                    ),
                }
            )

        # CTAS tables have no explicit column definitions in source DDL — skip schema
        # comparison and fall through to body comparison below.
        if source.columns and actual.get("columns") and not source.is_ctas:
            actual_columns = actual["columns"]
            missing_in_prod = sorted(set(source.columns) - set(actual_columns))
            extra_in_prod = sorted(set(actual_columns) - set(source.columns))
            type_mismatch = sorted(
                name
                for name in set(source.columns) & set(actual_columns)
                if canonical_bq_data_type(source.columns[name]) != canonical_bq_data_type(str(actual_columns[name]))
            )
            if missing_in_prod or extra_in_prod or type_mismatch:
                findings.append(
                    {
                        "area": "bigquery",
                        "object_name": object_name,
                        "dataset": actual.get("dataset"),
                        "status": "schema_mismatch",
                        "severity": "high",
                        "source_technology": source.source_kind,
                        "details": (
                            f"missing_in_prod={missing_in_prod}; extra_in_prod={extra_in_prod}; "
                            f"type_mismatch={type_mismatch}"
                        ),
                    }
                )

        if source.object_type in {"view", "materialized_view"}:
            # For plain views, BQ returns the SELECT body only via view_definition.
            # For views with column-level OPTIONS (inline descriptions), BQ returns the
            # full CREATE VIEW ... AS header. Strip the header from both sides to normalize.
            source_sql = normalize_sql(
                strip_create_as_header(
                    strip_redundant_project_qualifiers("\n".join(source.sql_fragments), project_id)
                )
            )
            actual_sql = normalize_sql(
                strip_create_as_header(
                    strip_redundant_project_qualifiers(actual.get("view_query") or actual.get("ddl") or "", project_id)
                )
            )
            if actual_sql and source_sql and source_sql != actual_sql:
                # For objects defined across multiple source files (e.g. a base file and
                # a FM_DTM_1h_v1.sql supersession), also check each fragment individually.
                # If any single fragment matches GCP the latest deployed version is already
                # in source — the joined sql_fragments just produced a non-matching string.
                frag_normalized = [
                    normalize_sql(
                        strip_create_as_header(
                            strip_redundant_project_qualifiers(frag, project_id)
                        )
                    )
                    for frag in source.sql_fragments
                ]
                fragment_match = source.multi_statement and any(
                    fn == actual_sql for fn in frag_normalized
                )
                # Suppress when source is a bare SELECT * FROM <table> — GCP may store
                # the expanded column list, making string comparison fail even though
                # the definitions are semantically equivalent.
                select_star_match = bool(_SELECT_STAR_VIEW_RE.match(source_sql.strip()))
                if not fragment_match and not select_star_match:
                    findings.append(
                        {
                            "area": "bigquery",
                            "object_name": object_name,
                            "dataset": actual.get("dataset"),
                            "status": "definition_mismatch",
                            "severity": "high",
                            "source_technology": source.source_kind,
                            "details": (
                                "Source view definition and selected GCP view definition differ after normalization."
                            ),
                        }
                    )

        if source.object_type == "table" and source.is_ctas:
            # GCP INFORMATION_SCHEMA.TABLES.ddl includes the full CTAS DDL with header.
            # Strip the header from both sides so comparison is body-only.
            source_sql = normalize_sql(
                strip_create_as_header(
                    strip_redundant_project_qualifiers("\n".join(source.sql_fragments), project_id)
                )
            )
            actual_sql = normalize_sql(
                strip_create_as_header(
                    strip_redundant_project_qualifiers(actual.get("ddl") or "", project_id)
                )
            )
            if actual_sql and source_sql and source_sql != actual_sql:
                findings.append(
                    {
                        "area": "bigquery",
                        "object_name": object_name,
                        "dataset": actual.get("dataset"),
                        "status": "definition_mismatch",
                        "severity": "high",
                        "source_technology": source.source_kind,
                        "details": "Source CTAS body and GCP CTAS body differ after normalization.",
                    }
                )
    return findings


def upload_to_gcs(
    bucket_name: str,
    gcs_prefix: str,
    execution_id: str,
    local_dir: Path,
) -> None:
    if bucket_name == REPORTS_GCS_BUCKET_DEFAULT:
        raise ValueError("--reports-gcs-bucket is required; no GCS upload target configured.")
    gcs_client = storage.Client()
    bucket = gcs_client.bucket(bucket_name)
    for local_file in sorted(local_dir.iterdir()):
        if not local_file.is_file():
            continue
        blob_name = f"{gcs_prefix}/{execution_id}/{local_dir.name}/{local_file.name}"
        bucket.blob(blob_name).upload_from_filename(str(local_file))
        log("INFO", "File uploaded to GCS", uri=f"gs://{bucket_name}/{blob_name}")


def write_to_bigquery(
    client: bigquery.Client,
    table_id: str,
    rows: list[dict[str, Any]],
) -> None:
    if not rows:
        return

    errors = client.insert_rows_json(table_id, rows)
    if errors:
        raise RuntimeError(f"BigQuery insert errors: {errors}")


def execution_id_exists(client: bigquery.Client, table_id: str, eid: str) -> bool:
    """Return True if this execution_id is already present — signals a Cloud Run retry."""
    rows = list(client.query(
        f"SELECT 1 FROM `{table_id}` WHERE execution_id = @eid AND execution_ts >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 DAY) LIMIT 1",
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("eid", "STRING", eid)]
        ),
    ).result())
    return len(rows) > 0


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_markdown(
    path: Path,
    args: argparse.Namespace,
    summary: dict[str, Any],
    bq_findings: list[dict[str, Any]],
    gcs_findings: list[dict[str, Any]],
    dag_inventory: dict[str, dict[str, Any]],
    source_bq: dict[str, SourceBqObject],
    source_dbt: dict[str, dict[str, Any]],
) -> None:
    """Write a concise human-readable report alongside the CSV and JSON outputs."""
    def format_bq_source_path(finding: dict[str, Any]) -> str | None:
        object_name = finding.get("object_name")
        technology = finding.get("source_technology")

        if technology == "bq" and object_name in source_bq:
            files = source_bq[object_name].files
            if files:
                return ", ".join(files)

        if technology == "dbt_model" and object_name in source_dbt:
            relative_path = source_dbt[object_name].get("relative_path")
            if relative_path:
                return str(relative_path)

        return None

    lines: list[str] = []
    finding_index = 1
    lines.append(f"# Discrepancy Report: {args.project_name}")
    lines.append("")
    lines.append(f"- Generated UTC: {summary['generated_utc']}")
    lines.append(f"- Source mode: {args.source_mode}")
    lines.append(f"- Git ref: {args.git_ref if args.source_mode == 'branch' else 'n/a'}")
    lines.append(f"- BigQuery project: {args.gcp_project}")
    lines.append(f"- Datasets: {', '.join(summary.get('datasets', []))}")
    lines.append(f"- GCS bucket: {args.gcs_bucket}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- BigQuery findings: {len(bq_findings)}")
    lines.append(f"- GCS findings: {len(gcs_findings)}")
    for warning in summary.get("warnings", []):
        lines.append(f"- Warning: {warning}")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append(f"- Datasets scanned: {', '.join(summary.get('datasets', []))}")
    lines.append(f"- Source BigQuery object candidates: {summary.get('source_bq_objects', 0)}")
    lines.append(f"- Source dbt models: {summary.get('source_dbt_models', 0)}")
    lines.append(f"- Source files compared against GCS: {summary.get('source_files', 0)}")
    lines.append(f"- Actual BigQuery objects found: {summary.get('actual_bq_objects', 0)}")
    lines.append(f"- Actual GCS objects found: {summary.get('actual_gcs_objects', 0)}")
    for warning in summary.get("warnings", []):
        lines.append(f"- Note: {warning}")
    lines.append("")

    for title, findings in (("BigQuery", bq_findings), ("GCS", gcs_findings)):
        lines.append(f"## {title} Findings")
        lines.append("")
        if not findings:
            lines.append("No findings.")
            lines.append("")
            continue
        for finding in findings:
            technology = finding.get("source_technology", "unknown")
            line = (
                f"{finding_index}. `{finding.get('status')}` `{finding.get('object_name', finding.get('path', 'n/a'))}` "
                f"[source={technology}]"
            )
            if title == "BigQuery":
                source_path = format_bq_source_path(finding)
                if source_path:
                    line += f" [source_path={source_path}]"
            line += f": {finding.get('details')}"
            lines.append(line)
            finding_index += 1
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate discrepancy report for one FastOSS data product.")
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--repo-path", required=True)
    parser.add_argument("--git-ref", default="production")
    parser.add_argument("--source-mode", choices=("branch", "nexus"), default="branch")
    parser.add_argument("--nexus-base-url", default="https://dot-portal.de.pri.o2.com/nexus")
    parser.add_argument("--nexus-repository")
    parser.add_argument("--nexus-env", default="prod")
    parser.add_argument("--nexus-version")
    parser.add_argument("--nexus-user", default=os.environ.get("NEXUS_USER"))
    parser.add_argument("--nexus-password", default=os.environ.get("NEXUS_PASSWORD"))
    parser.add_argument("--gcp-project", default="tefde-gcp-fastoss-prod")
    parser.add_argument("--datasets", nargs="+")
    parser.add_argument("--gcs-bucket", default="fastoss-prod-composer-3")
    parser.add_argument("--target-env", default="prod")
    parser.add_argument("--gcp-project-for-substitution", default="tefde-gcp-fastoss-prod")
    parser.add_argument("--output-dir", default=default_output_dir())
    parser.add_argument("--gcloud-path", default=default_gcloud_path())
    parser.add_argument("--curl-path", default=DEFAULT_CURL)
    parser.add_argument("--temp-root")
    parser.add_argument("--gcs-temp-root", default=default_gcs_temp_root())
    parser.add_argument("--keep-workdir", action="store_true")
    parser.add_argument(
        "--allow-empty-datasets",
        action="store_true",
        help="No-op, kept for backward compatibility. "
             "No-dataset repos always skip BQ comparison."
    )
    parser.add_argument(
        "--gcs-prefix",
        default="dags/{project_name}",
        help=(
            "GCS prefix under the bucket where artifacts are deployed. "
            "Supports {project_name} substitution. "
            "Default matches Composer layout: dags/{project_name}"
        ),
    )
    parser.add_argument(
        "--reporting-project",
        default=None,
        help=(
            "GCP project where BigQuery reporting tables exist. "
            "Defaults to --gcp-project if not set."
        ),
    )
    parser.add_argument(
        "--reports-gcs-bucket",
        default=REPORTS_GCS_BUCKET_DEFAULT,
        help="GCS bucket where report output files are uploaded.",
    )
    parser.add_argument(
        "--reports-gcs-prefix",
        default="env-drift",
        help="GCS key prefix for report uploads. Default: env-drift",
    )
    return parser.parse_args()


def main() -> int:
    """Run the full discrepancy workflow for one data product."""
    status = "success"
    bq_client = None
    gcs_path: str | None = None
    execution_id = os.environ.get("EXECUTION_ID")
    if not execution_id:
        raise ValueError("EXECUTION_ID environment variable must be set")
    triggered_by = os.environ.get("TRIGGERED_BY", "manual")
    start_time = time.monotonic()
    args = parse_args()
    # Resolve before try so the except handler can always reference it.
    reporting_project = args.reporting_project or args.gcp_project
    workdir_obj = None

    def _record_execution(exec_status: str) -> None:
        if bq_client is None:
            return
        try:
            write_to_bigquery(
                bq_client,
                f"{reporting_project}.devops_reports.executions",
                [{
                    "execution_id":     execution_id,
                    "report_type":      "env_drift",
                    "project_name":     args.project_name,
                    "execution_ts":     datetime.now(timezone.utc).isoformat(),
                    "environment":      args.target_env,
                    "git_ref":          args.git_ref if args.source_mode == "branch" else None,
                    "source_mode":      args.source_mode,
                    "triggered_by":     triggered_by,
                    "status":           exec_status,
                    "duration_seconds": int(time.monotonic() - start_time),
                    "gcs_path":         gcs_path,
                }],
            )
        except Exception as write_err:
            log("ERROR", "Failed to write execution record to BigQuery",
                intended_status=exec_status, error=str(write_err))

    try:
        repo_path = Path(args.repo_path)
        ensure_exists(repo_path, "Repo path")
        # gcloud path check removed: gcloud is on PATH inside the Docker image.
        if not args.nexus_repository:
            args.nexus_repository = default_nexus_repository(args.project_name)
        bq_client = bigquery.Client(project=reporting_project)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        report_root = Path(args.output_dir) / f"{args.project_name}_{timestamp}"
        report_root.mkdir(parents=True, exist_ok=True)

        workdir_parent = args.temp_root if args.temp_root else None
        workdir_obj = tempfile.TemporaryDirectory(
            prefix=f"{args.project_name}_discrepancy_", dir=workdir_parent
        )
        workdir = Path(workdir_obj.name)

        snapshot_dir = stage_source_snapshot(args, workdir)
        prod_settings = load_prod_gitlab_settings(snapshot_dir)
        resolved_gcp_project = prod_settings.get("BQ_PROJECT", args.gcp_project_for_substitution)
        resolved_target_env = prod_settings.get("ENV", args.target_env)
        resolved_bucket = prod_settings.get("GCP_BUCKET", args.gcs_bucket)
        resolved_datasets = list(args.datasets) if args.datasets else []
        dataset_names = prod_settings.get("BQ_DATASET_NAMES")
        if dataset_names and not resolved_datasets:
            resolved_datasets = [item.strip() for item in dataset_names.split(",") if item.strip()]
        if not resolved_datasets:
            print(
                "WARNING: No datasets resolved. "
                "BigQuery comparison will be skipped."
            )

        apply_substitutions(
            snapshot_dir,
            {
                "{{ GCP_PROJECT }}": resolved_gcp_project,
                "{{ TARGET_ENV }}": resolved_target_env,
            },
        )

        source_bq, renamed_away_names = build_source_bq_inventory(snapshot_dir)
        source_dbt = build_source_dbt_inventory(snapshot_dir)
        dbt_snapshot_names = build_dbt_snapshot_names(snapshot_dir)
        source_dags = build_source_dag_inventory(snapshot_dir)
        source_files = collect_source_files(snapshot_dir)

        gcs_snapshot_dir, gcs_warnings = stage_gcs_snapshot(
            args.gcloud_path,
            resolved_bucket,
            args.project_name,
            args.gcs_prefix,
            Path(args.gcs_temp_root),
        )
        actual_gcs = build_gcs_inventory(gcs_snapshot_dir)

        gcs_findings = compare_gcs(source_files, actual_gcs)
        if resolved_datasets:
            actual_bq = fetch_bigquery_inventory(
                args.gcp_project,
                resolved_datasets,
            )
            bq_findings = compare_bigquery(
                source_bq,
                source_dbt,
                actual_bq,
                args.gcp_project,
                renamed_away_names,
                dbt_snapshot_names,
            )
        else:
            actual_bq = {}
            bq_findings = []

        summary = {
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "project_name": args.project_name,
            "source_mode": args.source_mode,
            "git_ref": args.git_ref,
            "datasets": resolved_datasets,
            "resolved_prod_settings": {
                "BQ_PROJECT": resolved_gcp_project,
                "ENV": resolved_target_env,
                "GCP_BUCKET": resolved_bucket,
            },
            "bigquery_findings": len(bq_findings),
            "gcs_findings": len(gcs_findings),
            "source_bq_objects": len(source_bq),
            "source_dbt_models": len(source_dbt),
            "source_files": len(source_files),
            "actual_bq_objects": len(actual_bq),
            "actual_gcs_objects": len(actual_gcs),
            "warnings": gcs_warnings,
            "execution_id": execution_id,
            "reporting_project": reporting_project,
        }

        write_csv(report_root / "bigquery_findings.csv", bq_findings)
        write_csv(report_root / "gcs_findings.csv", gcs_findings)
        write_json(
            report_root / "inventory_snapshot.json",
            {
                "summary": summary,
                "source_bq": {name: vars(obj) for name, obj in source_bq.items()},
                "source_dbt": source_dbt,
                "source_dags": source_dags,
                "source_files": source_files,
                "actual_bq": actual_bq,
                "actual_gcs": actual_gcs,
                "execution_id": execution_id,
            },
        )
        write_markdown(
            report_root / "report.md", args, summary,
            bq_findings, gcs_findings, source_dags, source_bq, source_dbt,
        )

        upload_to_gcs(args.reports_gcs_bucket, args.reports_gcs_prefix, execution_id, report_root)
        gcs_path = f"gs://{args.reports_gcs_bucket}/{args.reports_gcs_prefix}/{execution_id}/"
        # Authenticated HTTPS URL for the per-product report — captured here so it
        # uses the same timestamp as the GCS folder name, not the later execution_ts.
        gcs_report_url = (
            f"https://storage.cloud.google.com/{args.reports_gcs_bucket}"
            f"/{args.reports_gcs_prefix}/{execution_id}/{report_root.name}/report.md"
        )

        # Dedup guard — skips BQ writes if this execution_id is already present.
        # Defense-in-depth against accidental duplicate runs with the same ID.
        if execution_id_exists(bq_client, f"{reporting_project}.devops_reports.executions", execution_id):
            log("WARNING", "Execution already recorded — skipping BQ writes", execution_id=execution_id)
            return 0

        # Write BQ after GCS so every row has a gcs_path and any BQ failure
        # is captured as status=failed in the except block.
        write_to_bigquery(
            bq_client,
            f"{reporting_project}.devops_reports.env_drift_findings",
            [
                {
                    "execution_id": execution_id,
                    "product": args.project_name,
                    "component_type": "bigquery",
                    "object_type": finding.get("source_technology"),
                    "object_name": finding.get("object_name"),
                    "drift_category": finding.get("status"),
                    "source_hash": None,
                    "env_hash": None,
                    "severity": finding.get("severity"),
                    "gcs_report_path": gcs_report_url,
                }
                for finding in bq_findings
            ],
        )
        write_to_bigquery(
            bq_client,
            f"{reporting_project}.devops_reports.env_drift_findings",
            [
                {
                    "execution_id": execution_id,
                    "product": args.project_name,
                    "component_type": "gcs",
                    "object_type": finding.get("source_technology"),
                    "object_name": finding.get("path"),
                    "drift_category": finding.get("status"),
                    "source_hash": None,
                    "env_hash": None,
                    "severity": finding.get("severity"),
                    "gcs_report_path": gcs_report_url,
                }
                for finding in gcs_findings
            ],
        )
        _record_execution("success")

        if args.keep_workdir:
            shutil.copytree(snapshot_dir, report_root / "rendered_source_snapshot", dirs_exist_ok=True)

        log("INFO", "Report complete", path=str(report_root), **summary)
        return 0

    except BranchNotFoundError as exc:
        # Expected for repos that never had this branch (e.g. staging/demo
        # projects) — record it distinctly so it doesn't read as a failure.
        status = "skipped"
        log("WARNING", "Skipped — branch not found", execution_id=execution_id, reason=str(exc))
        _record_execution("skipped")
        return 0

    except Exception:
        status = "failed"
        _record_execution("failed")
        raise

    finally:
        # Guard against workdir_obj being None when the failure occurs before
        # the temporary directory is created.
        if workdir_obj is not None:
            workdir_obj.cleanup()


if __name__ == "__main__":
    sys.exit(main())
