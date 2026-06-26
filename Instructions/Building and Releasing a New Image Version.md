# Building and Releasing a New Report/UI Image — Step-by-Step Guide

This document explains how to ship a code change: build a new Docker image, push it to
Artifact Registry, and — the step people most often forget — **explicitly redeploy** Cloud Run
so it actually starts using the new image.

There are two separate images in this project:

| Image | Built from | Used by |
|---|---|---|
| `devops-reports` | `Dockerfile.python` (report scripts, `entrypoint.sh`) | All 4 Cloud Run Jobs |
| `devops-reports-ui` | `ui/Dockerfile` (FastAPI backend, frontend) | The `devops-reports-ui` Cloud Run Service |

Change a report script (`git_branches_gap/`, `git_gcp_code_vs_environment_drift/`,
`bigquery_orphan_datasets/`, `clone_all_groups_repo/`, `entrypoint.sh`, `Dockerfile.python`) →
rebuild `devops-reports`. Change anything under `ui/` → rebuild `devops-reports-ui`.

---

## The one thing to understand before you start

**Pushing a new image does not redeploy it.** Cloud Run resolves an image tag (like `:latest`)
to a specific digest *at the moment you create or update the Cloud Run resource* — not on every
execution. If you push a new `:latest` image but never update the Cloud Run Job/Service itself,
every future execution keeps using the **old** digest indefinitely, even though Artifact
Registry now has a newer image under the same tag.

So releasing a new version is always **two steps**: build+push, then redeploy. Skipping the
second step is the most common way a "fix" silently never takes effect.

---

## Step 1 — Make your code change and commit it

Edit the relevant script(s), commit, and push to the default branch:

```bash
git add <changed files>
git commit -m "describe the fix"
git push origin main
```

## Step 2 — Build and push the image

### Option A — let CI do it (recommended)

`.gitlab-ci.yml`'s `build-reports` / `build-ui` jobs trigger automatically on pushes to the
default branch that touch the relevant files, and push both a `:<short-sha>` tag and `:latest`.
Check the pipeline succeeded (including the Trivy scan, which blocks the push on HIGH/CRITICAL
CVEs) before moving on.

> **Note:** the CI pipeline only runs `terraform plan`, never `terraform apply` (see the
> `terraform-plan` job's comment in `.gitlab-ci.yml`). It never redeploys anything — Step 3
> below is always a manual action regardless of how the image was built.

### Option B — build manually

```bash
SHA=$(git rev-parse --short HEAD)

# Reports image
IMAGE=europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports
docker build -f Dockerfile.python --build-arg BUILD_SHA=$SHA -t $IMAGE:$SHA -t $IMAGE:latest .
docker push $IMAGE:$SHA && docker push $IMAGE:latest

# UI image
IMAGE=europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports-ui
docker build -f ui/Dockerfile --build-arg BUILD_SHA=$SHA -t $IMAGE:$SHA -t $IMAGE:latest ui/
docker push $IMAGE:$SHA && docker push $IMAGE:latest
```

Note the short SHA you used (`$SHA`) — you need it in Step 3.

---

## Step 3 — Redeploy (required every time)

Pick **one** of these. Method A is recommended because it keeps `terraform.tfvars` (and
therefore your infrastructure history) in sync with what's actually deployed; Method B is
faster for a one-off test but causes drift that Method A will silently overwrite on the next
`terraform apply`.

### Method A — update Terraform and apply (recommended)

1. Edit `TEF remediation/Terraform/terraform.tfvars`, replacing the `:latest` tag with the
   specific SHA you just built — this guarantees Terraform sees a changed string and actually
   issues an update (a repeated `:latest` string never triggers a Terraform diff, since
   Terraform only compares the literal text of the `image` attribute, not the underlying
   digest):
   ```hcl
   container_image    = "europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports:abc1234"
   ui_container_image  = "europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports-ui:abc1234"
   ```
   (Only change the one(s) you actually rebuilt.)
2. Apply:
   ```bash
   cd "TEF remediation/Terraform"
   terraform plan    # confirm only the relevant Cloud Run Job(s)/Service show as "to change"
   terraform apply
   ```

### Method B — quick manual redeploy with gcloud (no Terraform state change)

For the 4 report jobs, repeat for each job you need to update:
```bash
gcloud run jobs update devops-reports-commit-drift \
  --image=europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports:abc1234 \
  --project=tefde-gcp-fastoss-dev-gke \
  --region=europe-west3
```
Job names: `devops-reports-orphan-datasets`, `devops-reports-env-drift`,
`devops-reports-commit-drift`, `devops-reports-file-drift`.

For the UI:
```bash
gcloud run services update devops-reports-ui \
  --image=europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports-ui:abc1234 \
  --project=tefde-gcp-fastoss-dev-gke \
  --region=europe-west3
```

If you use Method B, remember to also do Method A's Step 1 edit afterward (without re-applying
immediately) so `terraform.tfvars` reflects reality — otherwise the *next* unrelated
`terraform apply` will see no change in the `:latest` string and won't object, but anyone
reading `terraform.tfvars` will be looking at a stale version number.

---

## Step 4 — Verify

1. Confirm the Cloud Run resource now points at the new image:
   ```bash
   gcloud run jobs describe devops-reports-commit-drift \
     --project=tefde-gcp-fastoss-dev-gke --region=europe-west3 \
     --format="value(template.template.containers[0].image)"
   ```
   (Use `gcloud run services describe devops-reports-ui ...` for the UI.) The output should
   show your new SHA tag or its resolved digest, not the old one.
2. Trigger a run and watch the logs:
   ```bash
   gcloud run jobs execute devops-reports-commit-drift \
     --project=tefde-gcp-fastoss-dev-gke --region=europe-west3
   ```
   Check Cloud Logging for the execution and confirm the behavior you changed is actually
   different (e.g. the bug you fixed no longer reproduces).
3. Each image embeds its build SHA as an OCI label (`org.opencontainers.image.revision`,
   set via `BUILD_SHA` in the Dockerfiles) if you ever need to confirm exactly which commit a
   running container was built from:
   ```bash
   gcloud artifacts docker images describe \
     europe-west3-docker.pkg.dev/tefde-gcp-fastoss-dev-gke/devops-reports/devops-reports:abc1234 \
     --format="value(image_summary.digest)"
   ```

---

## Rolling back

Both job names and the SHA tag scheme make rollback straightforward: repeat Step 3 with the
previous known-good SHA tag instead of the new one (Artifact Registry keeps every SHA-tagged
image; only `:latest` ever moves). You don't need to rebuild anything to roll back.

---

## Releasing a full version (optional)

If this change is significant enough to warrant a version tag (see `Readme.md`'s CI/CD section
for the convention used so far, e.g. `v2.0.0`):
```bash
git tag -a v2.1.0 -m "Release v2.1.0: <summary>"
git push origin v2.1.0
```
