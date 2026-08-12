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
    A naive text.find("[") picks up that bracket, not the JSON array.
    We instead look for "[" only at the START of a line (re.MULTILINE),
    which matches the actual JSON array output but not the command echo.
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
    # Nothing parseable — print raw output to help diagnose
    print(f"  [warn] no JSON found in output of: {' '.join(airflow_cmd)}")
    print(f"  [warn] stdout: {result.stdout[:400]!r}")
    print(f"  [warn] stderr: {result.stderr[:400]!r}")
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project",     default=DEFAULT_PROJECT)
    parser.add_argument("--location",    default="europe-west3",
                        help="GCP region the Composer environment lives in")
    parser.add_argument("--environment", default="fastoss-prod-composer-3",
                        help="Composer environment name")
    parser.add_argument("--output",      default=DEFAULT_OUTPUT)
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

    # ── 3. List recent runs for all DAGs (≈30s) ────────────────────────────────
    print("Fetching recent DAG runs (≈30s)…")
    runs_raw = run_airflow_cmd(
        args.project, args.location, args.environment,
        ["dags", "list-runs"],
    )
    # Runs come ordered by execution_date desc; first hit per dag_id is the latest
    latest_run: dict[str, dict] = {}
    for r in runs_raw:
        did = r.get("dag_id", "")
        if did and did not in latest_run:
            latest_run[did] = r
    print(f"  {len(runs_raw)} run(s) retrieved, {len(latest_run)} unique DAG(s) with runs\n")

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
