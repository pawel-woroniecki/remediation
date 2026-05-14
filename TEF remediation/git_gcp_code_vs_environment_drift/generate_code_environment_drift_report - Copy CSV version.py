#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import base64
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CURL = "curl"
TEXT_SUFFIXES = {".sql", ".yml", ".yaml", ".py", ".txt", ".md", ".json"}


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


def default_gcloud_path() -> str:
    """Build the default local gcloud path from the current user profile."""
    return "gcloud"


def default_gcs_temp_root() -> str:
    """Use a short path by default to avoid Windows path-length issues during GCS staging."""
    return "/tmp"


def default_output_dir() -> str:
    """Write generated report files into the repository-wide shared outputs folder by default."""
    return str(Path(__file__).resolve().parents[2] / "outputs")


def default_nexus_repository(project_name: str) -> str:
    """Build the default Nexus repository path for the selected data product."""
    return f"raw-snapshots_hosted/fastoss_b/ndl_core/{project_name}"


def run_command(args: list[str], *, cwd: str | None = None, check: bool = True) -> str:
    """Run a subprocess and return stdout, raising a detailed error on failure."""
    proc = subprocess.run(
        args,
        cwd=cwd,
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
    return sql.strip().lower()


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
    }
    return aliases.get(normalized, normalized)


def normalize_text_content(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n")


def export_git_ref(repo_path: Path, git_ref: str, destination: Path) -> None:
    """Export a clean repository snapshot without modifying the working tree."""
    archive_path = destination / "source.zip"
    run_command(["git", "-C", str(repo_path), "archive", "--format=zip", git_ref, "-o", str(archive_path)])
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


def extract_bq_target(sql: str) -> tuple[str | None, str | None, str]:
    patterns = [
        (r"create\s+(?:or\s+replace\s+)?materialized\s+view\s+`?(?:(?P<project>[\w\-]+)\.)?(?P<dataset>[\w\-]+)\.(?P<object>[\w\-]+)`?", "materialized_view"),
        (r"create\s+(?:or\s+replace\s+)?view\s+`?(?:(?P<project>[\w\-]+)\.)?(?P<dataset>[\w\-]+)\.(?P<object>[\w\-]+)`?", "view"),
        (r"create\s+(?:or\s+replace\s+)?table\s+`?(?:(?P<project>[\w\-]+)\.)?(?P<dataset>[\w\-]+)\.(?P<object>[\w\-]+)`?", "table"),
        (r"create\s+(?:or\s+replace\s+)?procedure\s+`?(?:(?P<project>[\w\-]+)\.)?(?P<dataset>[\w\-]+)\.(?P<object>[\w\-]+)`?", "procedure"),
        (r"create\s+(?:or\s+replace\s+)?function\s+`?(?:(?P<project>[\w\-]+)\.)?(?P<dataset>[\w\-]+)\.(?P<object>[\w\-]+)`?", "function"),
        (r"alter\s+table\s+`?(?:(?P<project>[\w\-]+)\.)?(?P<dataset>[\w\-]+)\.(?P<object>[\w\-]+)`?", "alter_table"),
    ]
    for pattern, object_type in patterns:
        match = re.search(pattern, sql, flags=re.IGNORECASE)
        if match:
            return match.group("dataset"), match.group("object"), object_type
    return None, None, "unknown"


def extract_columns_from_create_table(sql: str) -> dict[str, str]:
    match = re.search(
        r"create\s+(?:or\s+replace\s+)?table\s+`?(?:[\w\-]+\.)?[\w\-]+\.[\w\-]+`?\s*\((?P<body>.*?)\)\s*(?:options|partition|cluster|;)",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return {}
    body = match.group("body")
    columns: dict[str, str] = {}
    for raw_line in body.splitlines():
        line = raw_line.strip().rstrip(",")
        if not line or line.startswith("--"):
            continue
        column_match = re.match(r"`?(?P<name>[\w\-]+)`?\s+(?P<dtype>[A-Z0-9_<>,]+)", line, flags=re.IGNORECASE)
        if column_match:
            columns[column_match.group("name")] = column_match.group("dtype").upper()
    return columns


def extract_columns_from_alter(sql: str) -> dict[str, str]:
    columns: dict[str, str] = {}
    for match in re.finditer(
        r"add\s+column(?:\s+if\s+not\s+exists)?\s+`?(?P<name>[\w\-]+)`?\s+(?P<dtype>[A-Z0-9_<>,]+)",
        sql,
        flags=re.IGNORECASE,
    ):
        columns[match.group("name")] = match.group("dtype").upper()
    return columns


def build_source_bq_inventory(snapshot_dir: Path) -> dict[str, SourceBqObject]:
    """Build a normalized inventory of source-side BigQuery objects from BQ DDL."""
    inventory: dict[str, SourceBqObject] = {}
    bq_root = snapshot_dir / "bq"
    if not bq_root.exists():
        return inventory

    for sql_file in sorted(bq_root.rglob("*.sql")):
        sql = sql_file.read_text(encoding="utf-8", errors="replace")
        dataset, object_name, object_type = extract_bq_target(sql)
        if not object_name:
            object_name = sql_file.stem
        entry = inventory.setdefault(
            object_name,
            SourceBqObject(object_name=object_name, dataset=dataset, object_type=object_type),
        )
        entry.files.append(str(sql_file.relative_to(snapshot_dir)).replace("\\", "/"))
        entry.sql_fragments.append(sql)
        entry.multi_statement = len(entry.files) > 1
        if object_type in {"table", "alter_table"}:
            entry.columns.update(extract_columns_from_create_table(sql))
            entry.columns.update(extract_columns_from_alter(sql))
            if entry.object_type == "alter_table" and entry.columns:
                entry.object_type = "table"
        elif object_type != "unknown":
            entry.object_type = object_type
        if dataset and not entry.dataset:
            entry.dataset = dataset
    return inventory


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
        materialized = extract_materialization(content)
        inventory[sql_file.stem] = {
            "object_name": sql_file.stem,
            "relative_path": str(sql_file.relative_to(snapshot_dir)).replace("\\", "/"),
            "sql_hash": sha256_text(normalize_sql(content)),
            "source_kind": "dbt_model",
            "materialized": materialized,
        }
    return inventory


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


def gcloud_access_token(gcloud_path: str) -> str:
    return run_command([gcloud_path, "auth", "print-access-token"]).strip()


def curl_json(curl_path: str, token: str, url: str) -> dict[str, Any]:
    """Currently unused helper kept for future REST GET-based metadata lookups."""
    output = run_command(
        [
            curl_path,
            "-sS",
            "-H",
            f"Authorization: Bearer {token}",
            url,
        ]
    )
    return json.loads(output) if output.strip() else {}


def curl_json_post(curl_path: str, token: str, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    output = run_command(
        [
            curl_path,
            "-sS",
            "-H",
            f"Authorization: Bearer {token}",
            "-H",
            "Content-Type: application/json",
            "-d",
            json.dumps(payload, separators=(",", ":")),
            url,
        ]
    )
    return json.loads(output) if output.strip() else {}


def bigquery_query(curl_path: str, token: str, project_id: str, sql: str) -> list[dict[str, Any]]:
    """Run a BigQuery Standard SQL query through REST and return rows as dictionaries."""
    payload = {"query": sql, "useLegacySql": False}
    response = curl_json_post(
        curl_path,
        token,
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{project_id}/queries",
        payload,
    )
    fields = response.get("schema", {}).get("fields", [])
    rows = response.get("rows", [])
    parsed: list[dict[str, Any]] = []
    for row in rows:
        values = row.get("f", [])
        item: dict[str, Any] = {}
        for field, value in zip(fields, values):
            item[field["name"]] = value.get("v")
        parsed.append(item)
    return parsed


def fetch_bigquery_inventory(
    curl_path: str,
    gcloud_path: str,
    project_id: str,
    datasets: list[str],
) -> dict[str, dict[str, Any]]:
    """Fetch BigQuery metadata for the selected target project through INFORMATION_SCHEMA views."""
    token = gcloud_access_token(gcloud_path)
    inventory: dict[str, dict[str, Any]] = {}
    for dataset in datasets:
        table_rows = bigquery_query(
            curl_path,
            token,
            project_id,
            f"""
            SELECT table_name, table_type, ddl
            FROM `{project_id}`.{dataset}.INFORMATION_SCHEMA.TABLES
            """.strip(),
        )
        column_rows = bigquery_query(
            curl_path,
            token,
            project_id,
            f"""
            SELECT table_name, column_name, data_type
            FROM `{project_id}`.{dataset}.INFORMATION_SCHEMA.COLUMNS
            """.strip(),
        )
        routine_rows = bigquery_query(
            curl_path,
            token,
            project_id,
            f"""
            SELECT routine_name, routine_type, routine_definition
            FROM `{project_id}`.{dataset}.INFORMATION_SCHEMA.ROUTINES
            """.strip(),
        )
        view_rows = bigquery_query(
            curl_path,
            token,
            project_id,
            f"""
            SELECT table_name, view_definition
            FROM `{project_id}`.{dataset}.INFORMATION_SCHEMA.VIEWS
            """.strip(),
        )

        for row in table_rows:
            inventory[row["table_name"]] = {
                "object_name": row["table_name"],
                "dataset": dataset,
                "object_type": str(row.get("table_type", "unknown")).lower().replace(" ", "_"),
                "columns": {},
                "view_query": None,
                "ddl": row.get("ddl"),
            }

        for row in column_rows:
            table_name = row["table_name"]
            inventory.setdefault(
                table_name,
                {
                    "object_name": table_name,
                    "dataset": dataset,
                    "object_type": "unknown",
                    "columns": {},
                    "view_query": None,
                    "ddl": None,
                },
            )
            inventory[table_name]["columns"][row["column_name"]] = row.get("data_type", "")

        for row in view_rows:
            table_name = row["table_name"]
            inventory.setdefault(
                table_name,
                {
                    "object_name": table_name,
                    "dataset": dataset,
                    "object_type": "view",
                    "columns": {},
                    "view_query": None,
                    "ddl": None,
                },
            )
            inventory[table_name]["view_query"] = row.get("view_definition")

        for row in routine_rows:
            inventory[row["routine_name"]] = {
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
    for area in ("dbt", "python"):
        area_target = target_dir / area
        area_target.mkdir(parents=True, exist_ok=True)
        resolved_prefix = gcs_prefix.format(project_name=project_name)
        source_path = f"gs://{bucket}/{resolved_prefix}/{area}"
        try:
            run_command(
                [
                    gcloud_path,
                    "storage",
                    "cp",
                    "--recursive",
                    source_path,
                    str(area_target),
                ]
            )
        except RuntimeError as exc:
            message = str(exc)
            if "matched no objects or files" in message:
                warnings.append(f"GCS path missing: {source_path}")
                continue
            raise
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
) -> list[dict[str, Any]]:
    """Compare source-side BQ/dbt expectations with actual BigQuery objects in the selected target project."""
    findings: list[dict[str, Any]] = []
    deployable_dbt_names = {
        name for name, model in source_dbt.items() if model.get("materialized") != "ephemeral"
    }
    expected_names = set(source_bq) | deployable_dbt_names
    actual_names = set(actual_bq)

    for object_name in sorted(actual_names - expected_names):
        actual = actual_bq[object_name]
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

    for object_name in sorted(expected_names - actual_names):
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
        actual = actual_bq[object_name]
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

        if source.columns and actual.get("columns"):
            actual_columns = actual["columns"]
            missing_in_prod = sorted(set(source.columns) - set(actual_columns))
            extra_in_prod = sorted(set(actual_columns) - set(source.columns))
            type_mismatch = sorted(
                name
                for name in set(source.columns) & set(actual_columns)
                if source.columns[name].upper() != str(actual_columns[name]).upper()
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
            source_sql = normalize_sql(strip_redundant_project_qualifiers("\n".join(source.sql_fragments), project_id))
            actual_sql = normalize_sql(
                strip_redundant_project_qualifiers(actual.get("view_query") or actual.get("ddl") or "", project_id)
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
                        "details": (
                            "Source view definition and selected GCP view definition differ after normalization."
                        ),
                    }
                )
    return findings


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
            help="Allow execution to continue when no datasets are resolved. "
                 "BigQuery comparison will be skipped."
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
    return parser.parse_args()


def main() -> int:
    """Run the full discrepancy workflow for one data product."""
    execution_id = os.environ.get("EXECUTION_ID")
    args = parse_args()
    repo_path = Path(args.repo_path)
    ensure_exists(repo_path, "Repo path")
    ensure_exists(Path(args.gcloud_path), "gcloud path")
    if not args.nexus_repository:
        args.nexus_repository = default_nexus_repository(args.project_name)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_root = Path(args.output_dir) / f"{args.project_name}_{timestamp}"
    report_root.mkdir(parents=True, exist_ok=True)

    workdir_parent = args.temp_root if args.temp_root else None
    workdir_obj = tempfile.TemporaryDirectory(prefix=f"{args.project_name}_discrepancy_", dir=workdir_parent)
    workdir = Path(workdir_obj.name)
    try:
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
            if args.allow_empty_datasets:
                print(
                    "WARNING: No datasets resolved. "
                    "BigQuery comparison will be skipped."
                )
            else:
                raise ValueError(
                    "No datasets resolved. Pass --datasets explicitly or ensure "
                    "BQ_DATASET_NAMES is present in .gitlab-ci.yml, "
                    "or use --allow-empty-datasets."
                )

        apply_substitutions(
            snapshot_dir,
            {
                "{{ GCP_PROJECT }}": resolved_gcp_project,
                "{{ TARGET_ENV }}": resolved_target_env,
            },
        )

        source_bq = build_source_bq_inventory(snapshot_dir)
        source_dbt = build_source_dbt_inventory(snapshot_dir)
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
                args.curl_path,
                args.gcloud_path,
                args.gcp_project,
                resolved_datasets,
            )
            bq_findings = compare_bigquery(
                source_bq,
                source_dbt,
                actual_bq,
                args.gcp_project,
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
        write_markdown(report_root / "report.md", args, summary, bq_findings, gcs_findings, source_dags, source_bq, source_dbt)

        if args.keep_workdir:
            shutil.copytree(snapshot_dir, report_root / "rendered_source_snapshot", dirs_exist_ok=True)

        print(f"Report written to: {report_root}")
        print(json.dumps(summary, indent=2))
        return 0
    finally:
        workdir_obj.cleanup()


if __name__ == "__main__":
    sys.exit(main())
