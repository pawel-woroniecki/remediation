#!/usr/bin/env python3
"""
Compare BigQuery table partitioning and clustering settings across GCP environments
(prod, test, dev-gke) and report discrepancies.

For each table found across the compared projects the script checks:
    time_partitioning  (type, field, expiration_ms, require_partition_filter)
    range_partitioning (field, range start / end / interval)
    clustering_fields  (sorted list of column names)

Two classes of discrepancy are reported:
    MISSING — table exists in prod but is absent from one or more lower envs
    DIFF    — table is present in all compared envs but settings differ

Results are written to BigQuery table devops_reports.bq_structure_drift
(primary output) and optionally to a CSV file (--output).

Usage:
    # Full report — all datasets, prod vs test vs dev-gke, write to BigQuery
    python compare_bq_structure.py

    # Only pl_energy dataset, also produce CSV
    python compare_bq_structure.py --dataset pl_energy --output report.csv

    # prod vs test only, skip BigQuery write
    python compare_bq_structure.py --envs prod,test --no-bq

Options:
    --envs LIST              Comma-separated environments to compare
                             (default: prod,test,dev-gke)
    --dataset DATASET_ID     Only compare this dataset. Repeatable.
                             (default: all datasets)
    --reporting-project ID   Project holding the devops_reports BQ dataset
                             (default: tefde-gcp-fastoss-dev)
    --output PATH            Also write results to a CSV file
    --no-bq                  Skip BigQuery write (terminal + optional CSV only)
    --workers N              Thread-pool size for parallel env fetching (default: 3)
"""

import argparse
import csv
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from google.cloud import bigquery

# ---------------------------------------------------------------------------
# Environment → project mapping (same as organize_tf_export_flat.py)
# ---------------------------------------------------------------------------

ENV_TO_PROJECT: dict[str, str] = {
    "prod":     "tefde-gcp-fastoss-prod",
    "prod-gke": "tefde-gcp-fastoss-prod-gke",
    "test":     "tefde-gcp-fastoss-test",
    "test-gke": "tefde-gcp-fastoss-test-gke",
    "dev":      "tefde-gcp-fastoss-dev",
    "dev-gke":  "tefde-gcp-fastoss-dev-gke",
}

REPORTING_PROJECT_DEFAULT = "tefde-gcp-fastoss-dev"
REPORTING_DATASET         = "devops_reports"
DRIFT_TABLE               = "bq_structure_drift"

# Attributes compared per table (in order they appear in the report)
ATTRIBUTES = [
    "tp_type",
    "tp_field",
    "tp_expiration_ms",
    "tp_require_filter",
    "rp_field",
    "rp_start",
    "rp_end",
    "rp_interval",
    "clustering",
]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TableMeta:
    exists:           bool            = False
    table_type:       str             = ""
    tp_type:          Optional[str]   = None
    tp_field:         Optional[str]   = None
    tp_expiration_ms: Optional[int]   = None
    tp_require_filter:Optional[bool]  = None
    rp_field:         Optional[str]   = None
    rp_start:         Optional[int]   = None
    rp_end:           Optional[int]   = None
    rp_interval:      Optional[int]   = None
    clustering:       Optional[str]   = None  # sorted comma-joined list

    def attr(self, name: str) -> str:
        """Return an attribute as a display string."""
        val = getattr(self, name)
        if val is None:
            return "<none>"
        return str(val).lower() if isinstance(val, bool) else str(val)


def meta_from_table(table: bigquery.Table) -> TableMeta:
    m = TableMeta(exists=True, table_type=table.table_type)

    if table.time_partitioning:
        tp = table.time_partitioning
        m.tp_type           = tp.type_
        m.tp_field          = tp.field
        m.tp_expiration_ms  = int(tp.expiration_ms) if tp.expiration_ms is not None else None
        m.tp_require_filter = tp.require_partition_filter

    if table.range_partitioning:
        rp    = table.range_partitioning
        m.rp_field    = rp.field
        m.rp_start    = rp.range_.start
        m.rp_end      = rp.range_.end
        m.rp_interval = rp.range_.interval

    if table.clustering_fields:
        m.clustering = ",".join(sorted(table.clustering_fields))

    return m


ABSENT = TableMeta(exists=False)


# ---------------------------------------------------------------------------
# Phase 1: fetch one environment
# ---------------------------------------------------------------------------

def fetch_env(
    env: str,
    project: str,
    only_datasets: list[str],
) -> dict[tuple[str, str], TableMeta]:
    """Return {(dataset_id, table_id): TableMeta} for one GCP project."""
    client = bigquery.Client(project=project)
    result: dict[tuple[str, str], TableMeta] = {}

    all_ds = list(client.list_datasets())
    if only_datasets:
        ds_set = set(only_datasets)
        all_ds = [d for d in all_ds if d.dataset_id in ds_set]

    for ds_item in all_ds:
        ds_id = ds_item.dataset_id
        try:
            tables = client.list_tables(ds_id)
        except Exception as exc:
            print(f"  [{env}] ERROR listing {ds_id}: {exc}", file=sys.stderr)
            continue
        for t_item in tables:
            if t_item.table_type == "SNAPSHOT":
                continue
            try:
                table = client.get_table(f"{project}.{ds_id}.{t_item.table_id}")
                result[(ds_id, table.table_id)] = meta_from_table(table)
            except Exception as exc:
                print(f"  [{env}] ERROR fetching {ds_id}.{t_item.table_id}: {exc}",
                      file=sys.stderr)
    return result


# ---------------------------------------------------------------------------
# Phase 2: compare across environments
# ---------------------------------------------------------------------------

def compare(
    envs: list[str],
    env_data: dict[str, dict[tuple[str, str], TableMeta]],
    prod_env: str,
) -> list[dict]:
    """Return list of discrepancy row dicts ready for BQ insert / CSV."""
    prod_tables = env_data.get(prod_env, {})
    all_keys: set[tuple[str, str]] = set()
    for data in env_data.values():
        all_keys.update(data.keys())

    rows: list[dict] = []

    for ds_id, t_id in sorted(all_keys):
        metas: dict[str, TableMeta] = {
            e: env_data[e].get((ds_id, t_id), ABSENT)
            for e in envs
        }
        prod_meta = metas.get(prod_env, ABSENT)
        table_type = next(
            (m.table_type for m in metas.values() if m.exists), "UNKNOWN"
        )

        # MISSING check: table exists in at least one env but not all
        any_present = any(m.exists for m in metas.values())
        all_present = all(m.exists for m in metas.values())
        if any_present and not all_present:
            row = _base_row(ds_id, t_id, table_type, "MISSING", "exists")
            for e in envs:
                _col(row, e, "EXISTS" if metas[e].exists else "ABSENT")
            rows.append(row)
            continue  # no point comparing attrs if table missing in some envs

        if not all_present:
            continue  # not in any env — shouldn't happen but skip

        # DIFF check: table present everywhere — compare attributes
        for attr in ATTRIBUTES:
            values = {e: metas[e].attr(attr) for e in envs}
            unique_vals = set(values.values())
            if len(unique_vals) > 1:
                row = _base_row(ds_id, t_id, table_type, "DIFF", attr)
                for e in envs:
                    _col(row, e, values[e])
                rows.append(row)

    return rows


def _base_row(ds_id, t_id, table_type, discrepancy, attribute) -> dict:
    return {
        "dataset_id":   ds_id,
        "table_id":     t_id,
        "table_type":   table_type,
        "discrepancy":  discrepancy,
        "attribute":    attribute,
    }


def _col(row: dict, env: str, value: str) -> None:
    key = env.replace("-", "_") + "_value"
    row[key] = value


# ---------------------------------------------------------------------------
# Phase 3: output
# ---------------------------------------------------------------------------

BQ_COLUMNS = [
    "run_id", "checked_at", "dataset_id", "table_id", "table_type",
    "discrepancy", "attribute",
]
CSV_COLUMNS = ["dataset_id", "table_id", "table_type", "discrepancy", "attribute"]


def write_bq(
    rows: list[dict],
    run_id: str,
    checked_at: datetime,
    envs: list[str],
    reporting_project: str,
) -> int:
    """Insert rows into devops_reports.bq_structure_drift. Returns row count."""
    if not rows:
        return 0

    client  = bigquery.Client(project=reporting_project)
    table_ref = f"{reporting_project}.{REPORTING_DATASET}.{DRIFT_TABLE}"

    bq_rows = []
    for r in rows:
        bq_row: dict = {
            "run_id":     run_id,
            "checked_at": checked_at.isoformat(),
            "dataset_id": r["dataset_id"],
            "table_id":   r["table_id"],
            "table_type": r.get("table_type", ""),
            "discrepancy":r["discrepancy"],
            "attribute":  r["attribute"],
        }
        for e in envs:
            col = e.replace("-", "_") + "_value"
            bq_row[col] = r.get(col, "")
        bq_rows.append(bq_row)

    errors = client.insert_rows_json(table_ref, bq_rows)
    if errors:
        print(f"  BigQuery insert errors: {errors}", file=sys.stderr)
        return 0
    return len(bq_rows)


def write_csv(
    rows: list[dict],
    envs: list[str],
    path: str,
) -> None:
    env_cols = [e.replace("-", "_") + "_value" for e in envs]
    fieldnames = CSV_COLUMNS + env_cols
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict], envs: list[str]) -> None:
    missing = [r for r in rows if r["discrepancy"] == "MISSING"]
    diffs   = [r for r in rows if r["discrepancy"] == "DIFF"]
    print(f"\n{'='*60}")
    print(f"  MISSING tables : {len(missing)}")
    print(f"  DIFF attributes: {len(diffs)}")
    print(f"{'='*60}")
    if rows:
        env_cols = [e.replace("-", "_") + "_value" for e in envs]
        header = f"{'DATASET':<20} {'TABLE':<40} {'TYPE':<6} {'DISCR':<8} {'ATTR':<22} " + \
                 "  ".join(f"{e:<20}" for e in envs)
        print(header)
        print("-" * len(header))
        for r in rows[:50]:  # cap terminal output at 50 rows
            vals = "  ".join(f"{r.get(c,''):<20}" for c in env_cols)
            print(f"{r['dataset_id']:<20} {r['table_id']:<40} "
                  f"{r.get('table_type',''):<6} {r['discrepancy']:<8} "
                  f"{r['attribute']:<22} {vals}")
        if len(rows) > 50:
            print(f"  ... {len(rows)-50} more rows (see CSV or BigQuery for full output)")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--envs", default="prod,test,dev-gke",
        help="Comma-separated environments to compare (default: prod,test,dev-gke)",
    )
    parser.add_argument(
        "--dataset", action="append", dest="datasets", metavar="DATASET_ID",
        help="Only compare this dataset. Repeatable. (default: all datasets)",
    )
    parser.add_argument(
        "--reporting-project", default=REPORTING_PROJECT_DEFAULT,
        help=f"Project holding devops_reports (default: {REPORTING_PROJECT_DEFAULT})",
    )
    parser.add_argument(
        "--output", default=None,
        help="Also write results to a CSV file at this path",
    )
    parser.add_argument(
        "--no-bq", action="store_true",
        help="Skip BigQuery write (terminal + optional CSV only)",
    )
    parser.add_argument(
        "--workers", type=int, default=3,
        help="Thread-pool size for parallel env fetching (default: 3)",
    )
    args = parser.parse_args()

    envs = [e.strip() for e in args.envs.split(",") if e.strip()]
    unknown = [e for e in envs if e not in ENV_TO_PROJECT]
    if unknown:
        print(f"ERROR: unknown env(s): {unknown}. Valid: {list(ENV_TO_PROJECT)}", file=sys.stderr)
        sys.exit(1)

    prod_env      = envs[0]   # first env is the reference (source of truth)
    only_datasets = args.datasets or []
    checked_at    = datetime.now(timezone.utc)
    run_id        = checked_at.strftime("%Y%m%dT%H%M%SZ")

    print(f"Comparing environments : {', '.join(envs)}")
    print(f"Reference env (prod)   : {prod_env} → {ENV_TO_PROJECT[prod_env]}")
    print(f"Datasets filter        : {', '.join(only_datasets) if only_datasets else 'all'}")
    print(f"Run ID                 : {run_id}")
    print()

    # Parallel fetch
    env_data: dict[str, dict[tuple[str, str], TableMeta]] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(fetch_env, e, ENV_TO_PROJECT[e], only_datasets): e
            for e in envs
        }
        for fut in as_completed(futures):
            e = futures[fut]
            try:
                result = fut.result()
                env_data[e] = result
                print(f"  [{e}] fetched {len(result)} table(s)")
            except Exception as exc:
                print(f"  [{e}] FAILED: {exc}", file=sys.stderr)
                env_data[e] = {}

    # Compare
    rows = compare(envs, env_data, prod_env)
    print_summary(rows, envs)

    if not rows:
        print("No discrepancies found.")
        return

    # Write to BigQuery
    if not args.no_bq:
        print(f"Writing {len(rows)} row(s) to "
              f"{args.reporting_project}.{REPORTING_DATASET}.{DRIFT_TABLE} ...", end=" ")
        written = write_bq(rows, run_id, checked_at, envs, args.reporting_project)
        print(f"{written} row(s) inserted.")

    # Write CSV
    if args.output:
        write_csv(rows, envs, args.output)
        print(f"CSV written to {args.output}")

    if args.no_bq and not args.output:
        print("(No output written — add --output FILE or remove --no-bq to persist results.)")


if __name__ == "__main__":
    main()
