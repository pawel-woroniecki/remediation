#!/usr/bin/env python3
"""
One-off backfill: set gcs_report_path in env_drift_findings for executions where it is
currently NULL by listing GCS objects and reconstructing the HTTPS report URL.

Run once from a shell authenticated to GCP (e.g., after `gcloud auth application-default login`):

  python backfill_env_drift_report_links.py \
      --bucket <reports_gcs_bucket> \
      --prefix env-drift \
      --reporting-project tefde-gcp-fastoss-dev
"""
import argparse

from google.cloud import bigquery, storage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True, help="GCS bucket that holds report files")
    parser.add_argument("--prefix", default="env-drift", help="GCS prefix (default: env-drift)")
    parser.add_argument("--reporting-project", required=True, help="GCP project that owns the BQ dataset")
    args = parser.parse_args()

    # 1. List every report.md blob and build execution_id → HTTPS URL mapping.
    #    Expected path structure: <prefix>/<execution_id>/<project_name>_<timestamp>/report.md
    print(f"Listing blobs in gs://{args.bucket}/{args.prefix}/ …")
    gcs = storage.Client()
    url_by_execution: dict[str, str] = {}
    skipped = 0
    for blob in gcs.list_blobs(args.bucket, prefix=args.prefix.rstrip("/") + "/"):
        parts = blob.name.split("/")
        if len(parts) != 4 or parts[-1] != "report.md":
            skipped += 1
            continue
        execution_id = parts[1]
        url = f"https://storage.cloud.google.com/{args.bucket}/{blob.name}"
        # If multiple timestamped folders exist for the same execution_id (e.g. retries),
        # keep the lexicographically latest folder — timestamps sort correctly as strings.
        if execution_id not in url_by_execution or blob.name > url_by_execution[execution_id]:
            url_by_execution[execution_id] = url

    print(f"  {len(url_by_execution)} execution(s) with report.md found  ({skipped} non-report blobs skipped)")

    if not url_by_execution:
        print("Nothing to backfill.")
        return

    # 2. Only process execution_ids where env_drift_findings rows have NULL gcs_report_path.
    bq = bigquery.Client(project=args.reporting_project)
    table = f"`{args.reporting_project}.devops_reports.env_drift_findings`"

    id_list = ", ".join(f"'{eid}'" for eid in url_by_execution)
    check_sql = f"""
        SELECT DISTINCT execution_id
        FROM {table}
        WHERE gcs_report_path IS NULL
          AND execution_id IN ({id_list})
    """
    needs_update = {row["execution_id"] for row in bq.query(check_sql).result()}
    print(f"  {len(needs_update)} execution(s) have findings rows with NULL gcs_report_path")

    if not needs_update:
        print("All matching findings rows already have gcs_report_path set. Nothing to do.")
        return

    # 3. MERGE: update only rows where gcs_report_path IS NULL for matched execution_ids.
    values = ",\n      ".join(
        f"('{eid}', '{url_by_execution[eid]}')"
        for eid in needs_update
    )
    merge_sql = f"""
    MERGE {table} AS t
    USING (
      SELECT execution_id, url
      FROM UNNEST([
        STRUCT<execution_id STRING, url STRING>
        {values}
      ])
    ) AS s
    ON t.execution_id = s.execution_id
    AND t.gcs_report_path IS NULL
    WHEN MATCHED THEN
      UPDATE SET gcs_report_path = s.url
    """

    print("Running BQ MERGE …")
    job = bq.query(merge_sql)
    job.result()
    print(f"Done. Rows updated: {job.num_dml_affected_rows}")
    print()
    print("Refresh the Looker Studio dashboard to see the backfilled report links.")


if __name__ == "__main__":
    main()
