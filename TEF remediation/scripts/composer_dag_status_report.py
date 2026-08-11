#!/usr/bin/env python3
"""
One-off report: latest DAG run status for every DAG in every Composer environment
in a GCP project.

Outputs a CSV file and a terminal summary.
Each row includes a direct Airflow UI link so the reader can click through to the run.

Usage (from Cloud Shell, authenticated as a project member):
  python composer_dag_status_report.py

Override defaults:
  python composer_dag_status_report.py \
      --project tefde-gcp-fastoss-prod-gke \
      --output dag_report.csv
"""
import argparse
import csv
import subprocess
import sys

import requests
from google.cloud.orchestration.airflow.service_v1 import EnvironmentsClient

DEFAULT_PROJECT = "tefde-gcp-fastoss-prod-gke"
DEFAULT_OUTPUT  = "dag_status_report.csv"

STATUS_EMOJI = {
    "success":  "✅",
    "failed":   "❌",
    "running":  "🔄",
    "queued":   "⏳",
    "no_runs":  "—",
}


def get_identity_token() -> str:
    return subprocess.check_output(
        ["gcloud", "auth", "print-identity-token"], stderr=subprocess.DEVNULL
    ).decode().strip()


def airflow_get(airflow_url: str, path: str, headers: dict) -> dict:
    resp = requests.get(f"{airflow_url}{path}", headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--output",  default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    # ── 1. Discover Composer environments ─────────────────────────────────────
    client = EnvironmentsClient()
    envs = list(client.list_environments(
        parent=f"projects/{args.project}/locations/-"
    ))
    if not envs:
        print(f"No Composer environments found in {args.project}.")
        sys.exit(1)
    print(f"Found {len(envs)} environment(s) in {args.project}\n")

    # ── 2. Identity token for IAP-protected Airflow webserver ─────────────────
    token = get_identity_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # ── 3. Query each environment ─────────────────────────────────────────────
    rows: list[dict] = []
    for env in envs:
        env_name    = env.name.split("/")[-1]
        location    = env.name.split("/")[3]
        airflow_url = env.config.airflow_uri.rstrip("/")
        console_url = (
            f"https://console.cloud.google.com/composer/environments/detail"
            f"/{location}/{env_name}/dags?project={args.project}"
        )
        print(f"Environment : {env_name}  ({location})")
        print(f"  Airflow UI  : {airflow_url}")
        print(f"  Console     : {console_url}")

        try:
            dags_data = airflow_get(airflow_url, "/api/v1/dags?limit=500", headers)
        except requests.HTTPError as exc:
            print(f"  ⚠ Could not list DAGs: {exc}")
            continue

        dags = dags_data.get("dags", [])
        print(f"  {len(dags)} DAG(s)\n")

        for dag in dags:
            dag_id    = dag["dag_id"]
            is_paused = dag.get("is_paused", False)

            try:
                runs_data = airflow_get(
                    airflow_url,
                    f"/api/v1/dags/{dag_id}/dagRuns?limit=1&order_by=-execution_date",
                    headers,
                )
                run = (runs_data.get("dag_runs") or [None])[0]
            except requests.HTTPError:
                run = None

            if run:
                state          = run.get("state", "unknown")
                execution_date = run.get("execution_date", "")[:19].replace("T", " ")
                run_id         = run.get("dag_run_id", "")
                run_link       = f"{airflow_url}/dags/{dag_id}/grid?dag_run_id={run_id}"
            else:
                state          = "no_runs"
                execution_date = ""
                run_id         = ""
                run_link       = f"{airflow_url}/dags/{dag_id}/grid"

            icon        = STATUS_EMOJI.get(state, "❓")
            paused_note = " [paused]" if is_paused else ""
            print(f"  {icon}  {dag_id}{paused_note}  →  {state}  {execution_date}")

            rows.append({
                "environment":      env_name,
                "location":         location,
                "dag_id":           dag_id,
                "is_paused":        is_paused,
                "latest_run_state": state,
                "execution_date":   execution_date,
                "run_id":           run_id,
                "airflow_ui_link":  run_link,
                "console_link":     console_url,
            })

    if not rows:
        print("No DAG data collected.")
        sys.exit(1)

    # ── 4. Write CSV ───────────────────────────────────────────────────────────
    fieldnames = [
        "environment", "location", "dag_id", "is_paused",
        "latest_run_state", "execution_date", "run_id",
        "airflow_ui_link", "console_link",
    ]
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # ── 5. Terminal summary ────────────────────────────────────────────────────
    total   = len(rows)
    success = sum(1 for r in rows if r["latest_run_state"] == "success")
    failed  = sum(1 for r in rows if r["latest_run_state"] == "failed")
    running = sum(1 for r in rows if r["latest_run_state"] == "running")
    other   = total - success - failed - running

    print(f"\n{'─' * 60}")
    print(f"Total DAGs : {total}")
    print(f"  ✅ success  : {success}")
    print(f"  ❌ failed   : {failed}")
    print(f"  🔄 running  : {running}")
    print(f"  —  other   : {other}")
    print(f"\nReport saved to: {args.output}")
    print("Open in Google Sheets (File → Import) for clickable links.")


if __name__ == "__main__":
    main()
