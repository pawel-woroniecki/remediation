#!/usr/bin/env python3
"""
One-off report: latest DAG run status for every DAG in a Cloud Composer environment.

Outputs a CSV file and a terminal summary.
Each row includes a direct Airflow UI link so the reader can click through to the run.

Uses `gcloud composer environments run` to execute Airflow CLI commands inside
the environment — no IAP authentication required.

Usage (from Cloud Shell, authenticated as a project member with roles/composer.user):
  python composer_dag_status_report.py

Override defaults:
  python composer_dag_status_report.py \
      --project     tefde-gcp-fastoss-prod-gke \
      --location    europe-west3 \
      --environment fastoss-prod-composer-3 \
      --output      dag_report.csv
"""
import argparse
import csv
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_PROJECT = "tefde-gcp-fastoss-prod-gke"
DEFAULT_OUTPUT  = "dag_status_report.csv"

STATUS_EMOJI = {
    "success":  "✅",
    "failed":   "❌",
    "running":  "🔄",
    "queued":   "⏳",
    "no_runs":  "—",
}


def get_composer_environment(project: str, location: str, environment: str) -> dict:
    """Fetch a single Composer environment via REST API (no IAP needed)."""
    import google.auth
    import google.auth.transport.requests

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    session = google.auth.transport.requests.AuthorizedSession(credentials)
    url = (
        f"https://composer.googleapis.com/v1/projects/{project}"
        f"/locations/{location}/environments/{environment}"
    )
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def run_airflow_cmd(
    project: str,
    location: str,
    env_name: str,
    airflow_cmd: list[str],
    extra_args: list[str] | None = None,
) -> list[dict]:
    """Execute an Airflow CLI command inside Composer and return parsed JSON.

    gcloud composer environments run echoes the command as:
      Executing the command: [ airflow ... ]...
    We look for "[" only at the START of a line (re.MULTILINE) so the bracket
    in that echo is ignored and we match the actual JSON array output.
    """
    cmd = (
        ["gcloud", "composer", "environments", "run", env_name,
         f"--location={location}", f"--project={project}"]
        + airflow_cmd
        + ["--", "--output", "json"] + (extra_args or [])
    )
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    for text in (result.stdout, result.stderr):
        for match in re.finditer(r"^\[", text, re.MULTILINE):
            start = match.start()
            end = text.rfind("]", start)
            if end < start:
                continue
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    return []


def get_latest_run_for_dag(
    project: str,
    location: str,
    env_name: str,
    dag_id: str,
) -> tuple[str, dict | None]:
    """Fetch the most recent DAG run for a single DAG. Returns (dag_id, run_dict or None)."""
    runs = run_airflow_cmd(
        project, location, env_name,
        ["dags", "list-runs"], ["--dag-id", dag_id]
    )
    # list-runs returns runs ordered execution_date desc; first entry is the latest
    return dag_id, (runs[0] if runs else None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project",     default=DEFAULT_PROJECT)
    parser.add_argument("--location",    default="europe-west3",
                        help="GCP region the Composer environment lives in")
    parser.add_argument("--environment", default="fastoss-prod-composer-3",
                        help="Composer environment name")
    parser.add_argument("--output",      default=DEFAULT_OUTPUT)
    parser.add_argument("--workers",     type=int, default=10,
                        help="Parallel workers for per-DAG run queries (default: 10)")
    parser.add_argument("--dag-limit",   type=int, default=0,
                        help="Cap number of DAGs queried (0 = all); use for testing")
    args = parser.parse_args()

    # ── 1. Fetch environment metadata for airflowUri and console link ──────────
    env         = get_composer_environment(args.project, args.location, args.environment)
    airflow_url = env["config"]["airflowUri"].rstrip("/")
    print(f"Environment: {args.environment}  ({args.location})")
    print(f"  Airflow UI : {airflow_url}\n")

    # ── 2. List all DAGs (≈30s) ────────────────────────────────────────────────
    print("Fetching DAG list (≈30s)…")
    dags_raw = run_airflow_cmd(
        args.project, args.location, args.environment, ["dags", "list"]
    )
    if not dags_raw:
        print("ERROR: could not retrieve DAG list. Check roles/composer.user on the project.")
        sys.exit(1)
    # Airflow 2 JSON uses "paused" (bool); guard against string "True"/"False"
    dag_pause_map: dict[str, bool] = {
        d["dag_id"]: str(d.get("paused", False)).lower() == "true"
        for d in dags_raw
    }
    print(f"  {len(dag_pause_map)} DAG(s) found\n")
    if args.dag_limit > 0:
        dag_pause_map = dict(list(dag_pause_map.items())[:args.dag_limit])
        print(f"  [--dag-limit] capped to {len(dag_pause_map)} DAG(s) for testing\n")

    # ── 3. Fetch the latest run for each DAG (parallel per-DAG calls) ────────────
    # airflow dags list-runs without --dag-id returns [] in Airflow 2.10;
    # per-DAG calls with --dag-id are required. We parallelise to stay fast.
    total_dags = len(dag_pause_map)
    print(
        f"Fetching latest run for {total_dags} DAG(s) using {args.workers} parallel workers…"
        f"\n  Estimated time: {total_dags // args.workers * 10 // 60}–"
        f"{total_dags // args.workers * 30 // 60} min depending on cluster latency."
    )
    latest_run: dict[str, dict] = {}
    done = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                get_latest_run_for_dag,
                args.project, args.location, args.environment, dag_id
            ): dag_id
            for dag_id in dag_pause_map
        }
        for future in as_completed(futures):
            dag_id, run = future.result()
            if run:
                latest_run[dag_id] = run
            done += 1
            if done % 100 == 0 or done == total_dags:
                print(f"  {done}/{total_dags} queried…")

    print(f"  {len(latest_run)} DAG(s) have at least one run\n")

    # ── 4. Build rows ──────────────────────────────────────────────────────────
    rows: list[dict] = []
    for dag_id, is_paused in sorted(dag_pause_map.items()):
        r = latest_run.get(dag_id)
        if r:
            state          = r.get("state", "unknown")
            execution_date = str(r.get("execution_date", ""))[:19].replace("T", " ")
            run_id         = r.get("run_id", "")
            run_link       = f"{airflow_url}/dags/{dag_id}/grid?dag_run_id={run_id}"
        else:
            state, execution_date, run_id = "no_runs", "", ""
            run_link = f"{airflow_url}/dags/{dag_id}/grid"

        icon        = STATUS_EMOJI.get(state, "❓")
        paused_note = " [paused]" if is_paused else ""
        print(f"  {icon}  {dag_id}{paused_note}  →  {state}  {execution_date}")

        rows.append({
            "environment":      args.environment,
            "location":         args.location,
            "dag_id":           dag_id,
            "is_paused":        is_paused,
            "latest_run_state": state,
            "execution_date":   execution_date,
            "run_id":           run_id,
            "airflow_ui_link":  run_link,
        })

    if not rows:
        print("No DAG data collected.")
        sys.exit(1)

    # ── 5. Write CSV ───────────────────────────────────────────────────────────
    fieldnames = [
        "environment", "location", "dag_id", "is_paused",
        "latest_run_state", "execution_date", "run_id",
        "airflow_ui_link",
    ]
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # ── 6. Terminal summary ────────────────────────────────────────────────────
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
