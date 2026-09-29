#!/usr/bin/env python3
"""
Export BigQuery resources (datasets, tables, routines) from a GCP project to
Terraform HCL, supplementing the output of gcloud beta resource-config bulk-export.

gcloud bulk-export relies on Cloud Asset Inventory (CAI), which has indexing gaps
— some BigQuery tables are silently skipped because they are not indexed in CAI.
This script queries the BigQuery API directly so every resource is captured.

Output files use the same directory structure as gcloud bulk-export:

    {exports_dir}/{env}/projects/{project_id}/BigQueryDataset/{dataset_id}.tf
    {exports_dir}/{env}/projects/{project_id}/BigQueryTable/{table_id}.tf
    {exports_dir}/{env}/projects/{project_id}/BigQueryRoutine/{routine_id}.tf

organize_tf_export_flat.py can therefore process the combined output unchanged.

Default behaviour — supplement mode: skip .tf files that already exist so the
existing gcloud output is preserved.  Use --overwrite to regenerate all files.

Usage:
    python export_bq_to_tf.py --project tefde-gcp-fastoss-prod \\
        --exports-dir /home/nq10083194/gcp-exports --env prod

    # Only a specific dataset
    python export_bq_to_tf.py --project tefde-gcp-fastoss-prod \\
        --exports-dir /home/nq10083194/gcp-exports --env prod \\
        --dataset pl_energy

    # Dry run to preview what would be written
    python export_bq_to_tf.py --project tefde-gcp-fastoss-prod \\
        --exports-dir /home/nq10083194/gcp-exports --env prod \\
        --dry-run

Options:
    --project    ID          GCP project ID (required)
    --env        NAME        Environment name; used as the subdirectory under
                             --exports-dir (default: prod)
    --exports-dir PATH       Parent of per-env export folders
                             (default: /home/nq10083194/gcp-exports)
    --overwrite              Overwrite .tf files that already exist
                             (default: skip existing files)
    --dataset    DATASET_ID  Only export this dataset. Repeatable.
                             (default: all datasets in the project)
    --dry-run                Print planned writes without writing files
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from google.cloud import bigquery


# ---------------------------------------------------------------------------
# Terraform identifier and string helpers
# ---------------------------------------------------------------------------

def tf_label(name: str) -> str:
    """Convert a resource ID to a valid Terraform identifier."""
    label = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    if label and not label[0].isalpha():
        label = 'r_' + label
    return label


def safe_stem(name: str, max_len: int = 200) -> str:
    """Truncate a filename stem that exceeds filesystem limits, appending a hash for uniqueness."""
    if len(name) <= max_len:
        return name
    h = hashlib.md5(name.encode()).hexdigest()[:8]
    return name[:max_len - 9] + '_' + h


def hcl_str(s: str) -> str:
    """Escape a string for use inside HCL double quotes."""
    return (
        s.replace('\\', '\\\\')
         .replace('"',  '\\"')
         .replace('\n', '\\n')
         .replace('\r', '\\r')
         .replace('\t', '\\t')
    )


def _schema_to_json(fields) -> list:
    """Convert SchemaField objects to a JSON-serialisable list."""
    result = []
    for f in fields:
        entry: dict = {"name": f.name, "type": f.field_type, "mode": f.mode}
        if f.description is not None:          # fix: emit empty-string descriptions too
            entry["description"] = f.description
        if f.fields:
            entry["fields"] = _schema_to_json(f.fields)
        if f.policy_tags and f.policy_tags.names:  # fix: preserve column-level security
            entry["policyTags"] = {"names": list(f.policy_tags.names)}
        result.append(entry)
    return result


def _labels_block(labels: dict, indent: int = 2) -> list[str]:
    pad = " " * indent
    lines = [f"{pad}labels = {{"]
    for k, v in sorted(labels.items()):
        lines.append(f'{pad}  "{hcl_str(k)}" = "{hcl_str(v)}"')
    lines.append(f"{pad}}}")
    return lines


# ---------------------------------------------------------------------------
# HCL generators — one function per resource type
# ---------------------------------------------------------------------------

def dataset_hcl(project: str, ds: bigquery.Dataset) -> str:
    ds_id = ds.dataset_id
    label = tf_label(ds_id)
    lines = [
        f"# terraform import google_bigquery_dataset.{label}"
        f" projects/{project}/datasets/{ds_id}",
        "",
        f'resource "google_bigquery_dataset" "{label}" {{',
        f'  project    = "{project}"',
        f'  dataset_id = "{ds_id}"',
        f'  location   = "{ds.location}"',
    ]
    if ds.description:
        lines.append(f'  description = "{hcl_str(ds.description)}"')
    if ds.default_table_expiration_ms is not None:
        lines.append(f'  default_table_expiration_ms = {int(ds.default_table_expiration_ms)}')
    if ds.default_partition_expiration_ms is not None:
        lines.append(f'  default_partition_expiration_ms = {int(ds.default_partition_expiration_ms)}')
    if ds.labels:
        lines.append("")
        lines.extend(_labels_block(ds.labels))
    lines += ["}", ""]
    return "\n".join(lines)


def table_hcl(project: str, table: bigquery.Table) -> str:
    ds_id  = table.dataset_id
    t_id   = table.table_id
    label  = tf_label(f"{ds_id}_{t_id}")
    ttype  = table.table_type  # TABLE / VIEW / MATERIALIZED_VIEW / EXTERNAL / SNAPSHOT

    lines = [
        f"# terraform import google_bigquery_table.{label}"
        f" projects/{project}/datasets/{ds_id}/tables/{t_id}",
        "",
        f'resource "google_bigquery_table" "{label}" {{',
        f'  project             = "{project}"',
        f'  dataset_id          = "{ds_id}"',
        f'  table_id            = "{t_id}"',
        f'  deletion_protection = false',
    ]
    # require_partition_filter is a top-level attribute in the current provider version
    if table.time_partitioning is not None:
        rpf = table.time_partitioning.require_partition_filter
        rpf = rpf if rpf is not None else False
        lines.append(f'  require_partition_filter = {str(rpf).lower()}')
    if table.description:
        lines.append(f'  description = "{hcl_str(table.description)}"')

    # Schema — regular/external tables always; materialized views only when they
    # use field-based partitioning (BigQuery requires the schema upfront so it
    # can validate the partition column before the view is materialized).
    _mv_needs_schema = (
        ttype == "MATERIALIZED_VIEW"
        and table.schema
        and (
            (table.time_partitioning and table.time_partitioning.field)
            or table.range_partitioning
        )
    )
    if (ttype in ("TABLE", "EXTERNAL") or _mv_needs_schema) and table.schema:
        schema_json = json.dumps(_schema_to_json(table.schema), indent=4)
        lines += ["", "  schema = <<SCHEMA_EOF", schema_json, "SCHEMA_EOF"]

    # View definition
    if ttype == "VIEW" and table.view_query:
        use_legacy = str(bool(table.view_use_legacy_sql)).lower()
        lines += [
            "",
            "  view {",
            "    query          = <<SQL_EOF",
            table.view_query,
            "SQL_EOF",
            f"    use_legacy_sql = {use_legacy}",
            "  }",
        ]

    # Materialized view
    if ttype == "MATERIALIZED_VIEW":
        mv = getattr(table, 'materialized_view', None)
        if mv and mv.query:
            lines += ["", "  materialized_view {",
                      "    query = <<SQL_EOF", mv.query, "SQL_EOF"]
            if mv.enable_refresh is not None:
                lines.append(f"    enable_refresh = {str(mv.enable_refresh).lower()}")
            if mv.refresh_interval_ms is not None:
                lines.append(f"    refresh_interval_ms = {int(mv.refresh_interval_ms)}")
            lines.append("  }")

    # Time partitioning
    if table.time_partitioning:
        tp = table.time_partitioning
        lines += ["", "  time_partitioning {", f'    type = "{tp.type_}"']
        if tp.field:
            lines.append(f'    field = "{tp.field}"')
        if tp.expiration_ms is not None:
            lines.append(f"    expiration_ms = {int(tp.expiration_ms)}")
        lines.append("  }")

    # Range partitioning
    if table.range_partitioning:
        rp = table.range_partitioning
        r  = rp.range_
        lines += [
            "", "  range_partitioning {",
            f'    field = "{rp.field}"',
            "    range {",
            f"      start    = {r.start}",
            f"      end      = {r.end}",
            f"      interval = {r.interval}",
            "    }",
            "  }",
        ]

    # Clustering
    if table.clustering_fields:
        fields_str = ", ".join(f'"{f}"' for f in table.clustering_fields)
        lines += ["", f"  clustering = [{fields_str}]"]

    # Expiration (epoch milliseconds)
    if table.expires:
        lines += ["", f"  expiration_time = {int(table.expires.timestamp() * 1000)}"]

    # Labels
    if table.labels:
        lines.append("")
        lines.extend(_labels_block(table.labels))

    # Encryption (CMEK) — fix: omitting this block forces destroy+recreate on CMEK tables
    if table.encryption_configuration and table.encryption_configuration.kms_key_name:
        lines += [
            "",
            "  encryption_configuration {",
            f'    kms_key_name = "{table.encryption_configuration.kms_key_name}"',
            "  }",
        ]

    lines += ["}", ""]
    return "\n".join(lines)


def routine_hcl(project: str, routine: bigquery.Routine) -> str:
    ds_id = routine.dataset_id
    r_id  = routine.routine_id
    label = tf_label(f"{ds_id}_{r_id}")

    rtype = routine.type_.name   if hasattr(routine.type_,    'name') else str(routine.type_)
    lang  = routine.language.name if hasattr(routine.language, 'name') else str(routine.language)
    body  = routine.body or ""

    lines = [
        f"# terraform import google_bigquery_routine.{label}"
        f" projects/{project}/datasets/{ds_id}/routines/{r_id}",
        "",
        f'resource "google_bigquery_routine" "{label}" {{',
        f'  project         = "{project}"',
        f'  dataset_id      = "{ds_id}"',
        f'  routine_id      = "{r_id}"',
        f'  routine_type    = "{rtype}"',
        f'  language        = "{lang}"',
        "  definition_body = <<BODY_EOF",
        body,
        "BODY_EOF",
    ]
    # return_type — required for non-SQL routines (JavaScript etc.)
    props = getattr(routine, '_properties', {})
    rt = props.get('returnType')
    if rt:
        lines.append(f'  return_type = {json.dumps(json.dumps(rt))}')

    # arguments — one block per parameter
    for arg in props.get('arguments', []):
        lines += ["", "  arguments {"]
        if arg.get('name'):
            lines.append(f'    name          = "{hcl_str(arg["name"])}"')
        ak = arg.get('argumentKind', 'FIXED_TYPE')
        lines.append(f'    argument_kind = "{ak}"')
        if arg.get('mode'):
            lines.append(f'    mode          = "{arg["mode"]}"')
        dt = arg.get('dataType')
        if dt:
            lines.append(f'    data_type     = {json.dumps(json.dumps(dt))}')
        lines.append("  }")

    if routine.description:
        lines.append(f'  description = "{hcl_str(routine.description)}"')
    lines += ["}", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# File writer
# ---------------------------------------------------------------------------

def write_hcl(path: Path, content: str, overwrite: bool, dry_run: bool) -> str:
    """Write content to path.  Returns 'written', 'skipped', or 'dry-run'."""
    if path.exists() and not overwrite:
        return "skipped"
    if dry_run:
        return "dry-run"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return "written"


# ---------------------------------------------------------------------------
# Export orchestration
# ---------------------------------------------------------------------------

def export_project(
    project: str,
    env: str,
    exports_dir: Path,
    overwrite: bool,
    only_datasets: list[str],
    dry_run: bool,
) -> None:
    client = bigquery.Client(project=project)
    project_root = exports_dir / env / "projects" / project

    mode_label = "DRY-RUN" if dry_run else ("overwrite" if overwrite else "supplement")
    print(f"Project      : {project}")
    print(f"Output root  : {project_root}")
    print(f"Mode         : {mode_label}")
    print()

    all_datasets = list(client.list_datasets())
    if only_datasets:
        ds_set       = set(only_datasets)
        all_datasets = [d for d in all_datasets if d.dataset_id in ds_set]
        missing      = ds_set - {d.dataset_id for d in all_datasets}
        for m in sorted(missing):
            print(f"WARNING: dataset '{m}' not found in project {project}", file=sys.stderr)

    grand_written = grand_skipped = grand_errors = 0

    for ds_item in sorted(all_datasets, key=lambda d: d.dataset_id):
        ds_id = ds_item.dataset_id
        w = s = e = 0
        print(f"[{ds_id}]")

        # --- Dataset resource ---
        try:
            ds     = client.get_dataset(ds_id)
            p      = project_root / "BigQueryDataset" / f"{ds_id}.tf"
            status = write_hcl(p, dataset_hcl(project, ds), overwrite, dry_run)
            if   status == "written":  w += 1; print(f"  dataset  {ds_id}.tf  → written")
            elif status == "dry-run":         print(f"  [DRY-RUN] dataset/{ds_id}.tf")
            else:                      s += 1
        except Exception as exc:
            e += 1
            print(f"  ERROR (dataset {ds_id}): {exc}", file=sys.stderr)

        # --- Tables ---
        try:
            tables_list = sorted(client.list_tables(ds_id), key=lambda t: t.table_id)
        except Exception as exc:
            print(f"  ERROR listing tables for {ds_id}: {exc}", file=sys.stderr)
            tables_list = []

        for t_item in tables_list:
            try:
                table = client.get_table(f"{project}.{ds_id}.{t_item.table_id}")
                if table.table_type == "SNAPSHOT":
                    print(f"  SKIP (snapshot): {t_item.table_id}")
                    continue
                p      = project_root / "BigQueryTable" / f"{safe_stem(f'{ds_id}_{table.table_id}')}.tf"
                status = write_hcl(p, table_hcl(project, table), overwrite, dry_run)
                if   status == "written":
                    w += 1
                    print(f"  table    {table.table_id}.tf  [{table.table_type}] → written")
                elif status == "dry-run":
                    print(f"  [DRY-RUN] table/{table.table_id}.tf  [{table.table_type}]")
                else:
                    s += 1
            except Exception as exc:
                e += 1
                print(f"  ERROR (table {t_item.table_id}): {exc}", file=sys.stderr)

        # --- Routines ---
        try:
            routines_list = sorted(client.list_routines(ds_id), key=lambda r: r.routine_id)
        except Exception as exc:
            routines_list = []

        for r_item in routines_list:
            try:
                routine = client.get_routine(f"{project}.{ds_id}.{r_item.routine_id}")
                p       = project_root / "BigQueryRoutine" / f"{safe_stem(f'{ds_id}_{routine.routine_id}')}.tf"
                status  = write_hcl(p, routine_hcl(project, routine), overwrite, dry_run)
                if   status == "written":
                    w += 1
                    print(f"  routine  {routine.routine_id}.tf → written")
                elif status == "dry-run":
                    print(f"  [DRY-RUN] routine/{routine.routine_id}.tf")
                else:
                    s += 1
            except Exception as exc:
                e += 1
                print(f"  ERROR (routine {r_item.routine_id}): {exc}", file=sys.stderr)

        parts = []
        if w: parts.append(f"{w} written")
        if s: parts.append(f"{s} skipped")
        if e: parts.append(f"{e} error(s)")
        if parts:
            print(f"  → {', '.join(parts)}")

        grand_written  += w
        grand_skipped  += s
        grand_errors   += e

    print()
    prefix = "[DRY-RUN] " if dry_run else ""
    print(f"{prefix}Done. {grand_written} written, {grand_skipped} skipped, "
          f"{grand_errors} error(s).")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", required=True, help="GCP project ID")
    parser.add_argument(
        "--env", default="prod",
        help="Environment name; subdirectory under --exports-dir (default: prod)",
    )
    parser.add_argument(
        "--exports-dir", default="/home/nq10083194/gcp-exports",
        help="Parent of per-env export folders (default: /home/nq10083194/gcp-exports)",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite existing .tf files (default: skip existing files)",
    )
    parser.add_argument(
        "--dataset", action="append", dest="datasets", metavar="DATASET_ID",
        help="Only export this dataset. Repeatable. (default: all datasets)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print planned writes without writing files",
    )
    args = parser.parse_args()

    exports_dir = Path(args.exports_dir)
    if not exports_dir.exists():
        print(f"ERROR: exports-dir not found: {exports_dir}", file=sys.stderr)
        sys.exit(1)

    export_project(
        project=args.project,
        env=args.env,
        exports_dir=exports_dir,
        overwrite=args.overwrite,
        only_datasets=args.datasets or [],
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
