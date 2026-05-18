from __future__ import annotations

import copy
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google.cloud import bigquery, run_v2
from google.cloud.run_v2.types import EnvVar, RunJobRequest
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

GCP_PROJECT = os.environ.get("GCP_PROJECT", "tefde-gcp-fastoss-dev-gke")
REPORTING_PROJECT = os.environ.get("REPORTING_PROJECT", "tefde-gcp-fastoss-dev")
REGION = os.environ.get("REGION", "europe-west3")
GCS_BUCKET = os.environ.get("GCS_BUCKET", "")
BQ_SCAN_PROJECT = os.environ.get("BQ_SCAN_PROJECT", "")

with open(BASE_DIR / "reports.yaml") as f:
    REPORTS: dict = yaml.safe_load(f)


def _resolve_reports() -> dict:
    """Apply env-var overrides to YAML defaults once at startup."""
    reports = copy.deepcopy(REPORTS)
    for report in reports.values():
        for param_name, param_def in report.get("parameters", {}).items():
            if param_name in ("gcs_bucket", "reports_gcs_bucket") and GCS_BUCKET:
                param_def["default"] = GCS_BUCKET
            elif param_name == "bq_scan_project" and BQ_SCAN_PROJECT:
                param_def["default"] = BQ_SCAN_PROJECT
            elif param_name == "gcp_project" and GCP_PROJECT:
                param_def["default"] = GCP_PROJECT
            elif param_name == "reporting_project" and REPORTING_PROJECT:
                param_def["default"] = REPORTING_PROJECT
    return reports


REPORTS_RESOLVED: dict = _resolve_reports()

# ---------------------------------------------------------------------------
# GCP clients — instantiated once at startup and shared across all requests.
# ---------------------------------------------------------------------------
_bq: bigquery.Client = bigquery.Client(project=REPORTING_PROJECT)
_jobs: run_v2.JobsClient = run_v2.JobsClient()
_execs: run_v2.ExecutionsClient = run_v2.ExecutionsClient()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="DevOps Reports UI")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


# ---------------------------------------------------------------------------
# Report metadata
# ---------------------------------------------------------------------------
@app.get("/api/reports")
def get_reports():
    return REPORTS_RESOLVED


# ---------------------------------------------------------------------------
# Trigger execution
# ---------------------------------------------------------------------------
class ExecutionRequest(BaseModel):
    report_type: str
    parameters: dict[str, str]


@app.post("/api/executions")
def trigger_execution(req: ExecutionRequest, request: Request):
    if req.report_type not in REPORTS_RESOLVED:
        raise HTTPException(status_code=400, detail=f"Unknown report type: {req.report_type}")

    report = REPORTS_RESOLVED[req.report_type]

    # Validate required parameters
    for param_name, param_def in report["parameters"].items():
        if param_def.get("required") and not req.parameters.get(param_name, "").strip():
            raise HTTPException(status_code=400, detail=f"Missing required parameter: {param_name}")

    # Build CLI args and env var overrides from the parameter metadata
    args = [req.report_type]
    env_overrides: list[EnvVar] = []

    for param_name, param_def in report["parameters"].items():
        value = req.parameters.get(param_name, "").strip()
        if not value:
            raw_default = str(param_def.get("default", ""))
            value = date.today().isoformat() if raw_default == "<today>" else raw_default
        if not value:
            continue

        if param_def.get("type") == "enum" and value not in param_def.get("options", []):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid value '{value}' for '{param_name}'. Allowed: {param_def.get('options')}",
            )

        if "cli_flag" in param_def:
            args += [param_def["cli_flag"], value]
        elif "env_var" in param_def:
            env_overrides.append(EnvVar(name=param_def["env_var"], value=value))

    triggered_by = (
        request.headers.get("X-Goog-Authenticated-User-Email", "").removeprefix("accounts.google.com:")
        or "ui"
    )
    env_overrides.append(EnvVar(name="TRIGGERED_BY", value=triggered_by))

    job_resource = (
        f"projects/{GCP_PROJECT}/locations/{REGION}/jobs/{report['cloud_run_job']}"
    )

    try:
        operation = _jobs.run_job(
            RunJobRequest(
                name=job_resource,
                overrides=RunJobRequest.Overrides(
                    container_overrides=[
                        RunJobRequest.Overrides.ContainerOverride(
                            args=args,
                            env=env_overrides,
                        )
                    ]
                ),
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to trigger Cloud Run Job: {exc}")

    # Prefer execution name from the LRO metadata (set immediately by the API)
    execution_name: Optional[str] = None
    try:
        meta = operation.metadata
        if meta and meta.name:
            execution_name = meta.name
    except Exception:
        pass

    # Fallback: list executions and take the most recent one
    if not execution_name:
        time.sleep(2)
        try:
            executions = list(
                _execs.list_executions(
                    request=run_v2.ListExecutionsRequest(parent=job_resource)
                )
            )
            if executions:
                executions.sort(key=lambda e: e.create_time, reverse=True)
                execution_name = executions[0].name
        except Exception:
            pass

    if not execution_name:
        raise HTTPException(
            status_code=500,
            detail="Job was triggered but the execution name could not be retrieved. "
                   "Check Cloud Run console for job status.",
        )

    return {"execution_name": execution_name, "status": "triggered"}


# ---------------------------------------------------------------------------
# Execution status
# ---------------------------------------------------------------------------
@app.get("/api/executions/status")
def get_execution_status(
    name: str = Query(..., description="Cloud Run execution resource name"),
):
    try:
        execution = _execs.get_execution(name=name)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Execution not found: {exc}")

    status = _derive_status(execution)

    if status != "succeeded":
        return {"status": status}

    # Succeeded — look up the EXECUTION_ID and GCS path from BigQuery
    report_type = _report_type_from_execution_name(name)
    execution_id: Optional[str] = None
    gcs_url: Optional[str] = None

    if report_type:
        create_time: datetime = execution.create_time
        # create_time is a UTC datetime via proto-plus; subtract buffer for clock skew
        after_ts = create_time - timedelta(seconds=60)
        row = _query_bq_execution(report_type, after_ts)
        if row:
            execution_id = row.get("execution_id")
            raw_gcs = row.get("gcs_path")
            if raw_gcs:
                gcs_url = (
                    "https://console.cloud.google.com/storage/browser/"
                    + raw_gcs.removeprefix("gs://")
                )
            else:
                gcs_url = _build_gcs_url(report_type, execution_id)

    return {
        "status": "succeeded",
        "execution_id": execution_id,
        "gcs_url": gcs_url,
    }


# ---------------------------------------------------------------------------
# List recent executions
# ---------------------------------------------------------------------------
@app.get("/api/executions")
def list_executions():
    query = f"""
        SELECT execution_id, report_type, execution_ts, status, gcs_path
        FROM `{REPORTING_PROJECT}.devops_reports.executions`
        ORDER BY execution_ts DESC
        LIMIT 20
    """
    try:
        rows = list(_bq.query(query).result())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"BigQuery query failed: {exc}")

    return [
        {
            "execution_id": r.execution_id,
            "report_type": r.report_type,
            "execution_ts": r.execution_ts.isoformat() if r.execution_ts else None,
            "status": r.status,
            "gcs_path": r.gcs_path,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _derive_status(execution: run_v2.Execution) -> str:
    if execution.reconciling:
        return "running"
    if execution.failed_count > 0:
        return "failed"
    if execution.succeeded_count > 0:
        return "succeeded"
    return "running"


def _report_type_from_execution_name(execution_name: str) -> Optional[str]:
    for report_type, report_def in REPORTS_RESOLVED.items():
        if report_def["cloud_run_job"] in execution_name:
            return report_type
    return None


def _query_bq_execution(report_type: str, after: datetime) -> Optional[dict]:
    query = f"""
        SELECT execution_id, gcs_path
        FROM `{REPORTING_PROJECT}.devops_reports.executions`
        WHERE report_type = @report_type
          AND execution_ts >= @after
        ORDER BY execution_ts DESC
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("report_type", "STRING", report_type),
            bigquery.ScalarQueryParameter("after", "TIMESTAMP", after.isoformat()),
        ]
    )
    try:
        rows = list(_bq.query(query, job_config=job_config).result())
        return dict(rows[0]) if rows else None
    except Exception:
        return None


def _build_gcs_url(report_type: str, execution_id: Optional[str]) -> Optional[str]:
    if not execution_id:
        return None
    report = REPORTS_RESOLVED.get(report_type, {})
    prefix = report.get("gcs_prefix", "")
    bucket_param = report.get("gcs_bucket_param", "gcs_bucket")
    bucket = report.get("parameters", {}).get(bucket_param, {}).get("default", "")
    if not bucket:
        return None
    path = f"{prefix}/{execution_id}" if prefix else execution_id
    return f"https://console.cloud.google.com/storage/browser/{bucket}/{path}"
