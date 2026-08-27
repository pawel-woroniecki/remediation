#!/usr/bin/env python3
"""
One-off report: latest DAG run status for every DAG in a Cloud Composer environment.

Outputs a CSV file and a terminal summary.
Each row includes a direct Airflow UI link so the reader can click through to the run.

Authentication is automatic:
  1. Tries the Airflow stable REST API using an OAuth 2.0 access token
     (same credentials used for the Composer management API — no IAP discovery needed).
     If the environment accepts it: ~20–60 s for 1000+ DAGs.
  2. If the REST API returns 401/403, falls back to gcloud-subprocess calls
     (~15 min for 1000+ DAGs with --workers 20, still much faster than the old default).

Usage (from Cloud Shell, authenticated as a project member with roles/composer.user):
  python composer_dag_status_report.py

Override defaults:
  python composer_dag_status_report.py \
      --project     tefde-gcp-fastoss-prod-gke \
      --location    europe-west3 \
      --environment fastoss-prod-composer-3 \
      --output      dag_report.csv \
      --workers     20
"""
import argparse
import csv
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import google.auth
import google.auth.transport.requests
import requests

DEFAULT_PROJECT = "tefde-gcp-fastoss-prod-gke"
DEFAULT_OUTPUT  = "dag_status_report.csv"

STATUS_EMOJI = {
    "success":  "✅",
    "failed":   "❌",
    "running":  "🔄",
    "queued":   "⏳",
    "no_runs":  "—",
}


# ── REST API helpers ─────────────────────────────────────────────────────────

def _make_authorized_session():
    """Build an HTTP session for Airflow REST API calls.

    Prefers `gcloud auth print-access-token` (the interactive user's token) over
    google.auth.default() to avoid GOOGLE_APPLICATION_CREDENTIALS overrides in
    Cloud Shell that may resolve to a service account with restricted Airflow RBAC.
    Falls back to google.auth.default() when gcloud is not available.
    """
    try:
        result = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True, text=True, timeout=30,
        )
        token = result.stdout.strip()
        if token and result.returncode == 0:
            session = requests.Session()
            session.headers.update({"Authorization": f"Bearer {token}"})
            return session
    except Exception:
        pass
    # Fallback: google.auth ADC (works outside Cloud Shell / in Cloud Run jobs)
    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    return google.auth.transport.requests.AuthorizedSession(credentials)


def list_dags_http(session, airflow_url: str) -> dict[str, bool]:
    """Fetch all DAGs via Airflow REST API.  Returns {dag_id: is_paused}."""
    dag_pause_map: dict[str, bool] = {}
    offset = 0
    limit = 200
    while True:
        resp = session.get(
            f"{airflow_url}/api/v1/dags",
            params={"limit": limit, "offset": offset, "only_active": "false"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        for dag in data.get("dags", []):
            dag_pause_map[dag["dag_id"]] = bool(dag.get("is_paused", False))
        total = data.get("total_entries", 0)
        offset += limit
        if offset >= total:
            break
    return dag_pause_map


def get_latest_run_http(
    session,
    airflow_url: str,
    dag_id: str,
    start_date: str,
) -> tuple[str, dict | None]:
    """Fetch the most recent DAG run for one DAG via the Airflow REST API."""
    try:
        resp = session.get(
            f"{airflow_url}/api/v1/dags/{dag_id}/dagRuns",
            params={
                "limit": 1,
                "order_by": "-execution_date",
                "start_date_gte": f"{start_date}T00:00:00Z",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            return dag_id, None
        runs = resp.json().get("dag_runs", [])
        if not runs:
            return dag_id, None
        run = runs[0]
        # Normalise REST API field names to match the gcloud CLI schema used downstream
        run["run_id"] = run.pop("dag_run_id", run.get("run_id", ""))
        return dag_id, run
    except Exception:
        return dag_id, None


# ── gcloud fallback helpers ───────────────────────────────────────────────────

def get_composer_environment(project: str, location: str, environment: str) -> dict:
    """Fetch a single Composer environment via REST API (no IAP needed)."""
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
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return []
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
    start_date: str,
) -> tuple[str, dict | None]:
    """Fetch the most recent DAG run for a single DAG via gcloud (fallback)."""
    runs = run_airflow_cmd(
        project, location, env_name,
        ["dags", "list-runs"], ["--dag-id", dag_id, "--start-date", start_date]
    )
    return dag_id, (runs[0] if runs else None)


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project",     default=DEFAULT_PROJECT)
    parser.add_argument("--location",    default="europe-west3",
                        help="GCP region the Composer environment lives in")
    parser.add_argument("--environment", default="fastoss-prod-composer-3",
                        help="Composer environment name")
    parser.add_argument("--output",      default=DEFAULT_OUTPUT)
    parser.add_argument("--workers",          type=int, default=20,
                        help="Parallel workers for per-DAG run queries (default: 20)")
    parser.add_argument("--run-window-days",  type=int, default=90,
                        help="Only look at runs in the last N days (default: 90)")
    parser.add_argument("--dag-limit",        type=int, default=0,
                        help="Cap number of DAGs queried (0 = all); use for testing")
    args = parser.parse_args()

    # ── 1. Fetch environment metadata for airflowUri ──────────────────────────
    print("Fetching Composer environment metadata…")
    env         = get_composer_environment(args.project, args.location, args.environment)
    airflow_url = env["config"]["airflowUri"].rstrip("/")
    print(f"Environment: {args.environment}  ({args.location})")
    print(f"  Airflow UI : {airflow_url}\n")

    start_date = (
        datetime.now(timezone.utc) - timedelta(days=args.run_window_days)
    ).strftime("%Y-%m-%d")

    # ── 2. List DAGs — try REST API first, fall back to gcloud ────────────────
    print("Connecting to Airflow REST API…")
    rest_session = _make_authorized_session()

    # Cheap probe to check whether the access token is accepted
    try:
        probe = rest_session.get(
            f"{airflow_url}/api/v1/dags", params={"limit": 1}, timeout=10
        )
        use_rest_api = probe.status_code == 200
    except Exception:
        use_rest_api = False
        probe = None

    probe_status = probe.status_code if probe is not None else "error"

    if use_rest_api:
        print("  REST API accepted (OAuth 2.0 access token) — fast path active.")
        print("Fetching DAG list via Airflow REST API…")
        dag_pause_map = list_dags_http(rest_session, airflow_url)
        if not dag_pause_map:
            print("ERROR: REST API returned empty DAG list.")
            sys.exit(1)
    else:
        print(f"  REST API returned HTTP {probe_status} — falling back to gcloud.")
        print("Fetching DAG list via gcloud (≈30s)…")
        dags_raw = run_airflow_cmd(
            args.project, args.location, args.environment, ["dags", "list"]
        )
        if not dags_raw:
            print("ERROR: could not retrieve DAG list. Check roles/composer.user on the project.")
            sys.exit(1)
        dag_pause_map: dict[str, bool] = {
            d["dag_id"]: str(d.get("paused", False)).lower() == "true"
            for d in dags_raw
        }

    print(f"  {len(dag_pause_map)} DAG(s) found\n")
    if args.dag_limit > 0:
        dag_pause_map = dict(list(dag_pause_map.items())[:args.dag_limit])
        print(f"  [--dag-limit] capped to {len(dag_pause_map)} DAG(s) for testing\n")

    # ── 3. Fetch the latest run for each DAG (parallel) ───────────────────────
    total_dags = len(dag_pause_map)
    approach = "REST API" if use_rest_api else "gcloud"
    print(
        f"Fetching latest run for {total_dags} DAG(s) using {args.workers} parallel workers ({approach})…"
        f"\n  Run window  : {start_date} → now ({args.run_window_days} days)"
    )
    if not use_rest_api:
        estimated_lo = total_dags // args.workers * 10 // 60
        estimated_hi = total_dags // args.workers * 30 // 60
        print(f"  Estimated time: {estimated_lo}–{estimated_hi} min (gcloud mode)")

    latest_run: dict[str, dict] = {}
    done = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        if use_rest_api:
            futures = {
                pool.submit(
                    get_latest_run_http,
                    rest_session, airflow_url, dag_id, start_date
                ): dag_id
                for dag_id in dag_pause_map
            }
        else:
            futures = {
                pool.submit(
                    get_latest_run_for_dag,
                    args.project, args.location, args.environment, dag_id, start_date
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
