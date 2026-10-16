# Rotating the GitLab PAT

The GitLab Personal Access Token (PAT) stored as `gitlab-token` in Secret Manager is
fetched at runtime by every Cloud Run Job to clone repos from the `ndl_core` subgroup.
When it expires, **all 7 jobs fail simultaneously** with a 401 / authentication error.

> **Prefer a Group Access Token over a Personal Access Token.** A Personal Access Token
> is tied to an individual GitLab account — if that person leaves, the token is revoked
> automatically and all jobs stop. A Group Access Token belongs to the `ndl_core` group
> and survives staff changes. Ask the GitLab group owner to create a Group Access Token
> if one is not already in use.

---

## Step 1 — Create a new token in GitLab

1. Open GitLab and navigate to the **ndl_core** group.
2. Go to **Settings → Access Tokens**.
3. Click **Add new token** (or **Create group access token**).
4. Set a descriptive name, e.g. `devops-reports-runner`.
5. Set an expiry date at least 12 months out. Note it in your team calendar so rotation
   is planned, not reactive.
6. Select **exactly these two scopes**: `read_api` and `read_repository`. No other scopes
   are needed.
7. Click **Create** and **copy the token value immediately** — GitLab shows it only once.

---

## Step 2 — Load the new token into Secret Manager

Run this command from any terminal with `gcloud` access and the
`secretmanager.versions.add` permission:

```bash
gcloud secrets versions add gitlab-token \
  --project=tefde-gcp-fastoss-dev-gke \
  --data-file=- <<< "PASTE_NEW_TOKEN_HERE"
```

Verify the new version is now the `ENABLED` latest version:

```bash
gcloud secrets versions list gitlab-token \
  --project=tefde-gcp-fastoss-dev-gke
```

The newest version should show `STATE: ENABLED`. The Cloud Run Jobs always fetch the
*latest* version automatically — no Terraform or Cloud Run configuration change is needed.

---

## Step 3 — Verify with a test run

Trigger the lightest job to confirm the new token works before the next scheduled run:

```bash
gcloud run jobs execute devops-reports-orphan-datasets \
  --project=tefde-gcp-fastoss-dev-gke \
  --region=europe-west3
```

Wait ~5 minutes, then check **Cloud Run → Jobs → `devops-reports-orphan-datasets` →
Executions**. Status should be `Succeeded`. If it still fails with an authentication error,
double-check the token was copied correctly (no trailing newline or whitespace).

---

## Step 4 — Disable the old token version (optional but recommended)

Once the test run succeeds, disable the previous secret version to prevent accidental use:

```bash
# Replace N with the old version number shown in step 2
gcloud secrets versions disable N \
  --secret=gitlab-token \
  --project=tefde-gcp-fastoss-dev-gke
```

---

## Step 5 — Notify the team

- Inform the DevOps platform team that the token was rotated and jobs are healthy again.
- If the old token still exists in GitLab, revoke it there too:
  **GitLab group → Settings → Access Tokens → Revoke**.
- Add a reminder in your team calendar for the new expiry date, at least 2 weeks before —
  plan the next rotation before it becomes an incident.

---

## Checklist

- [ ] New token created in GitLab with `read_api` + `read_repository` scopes
- [ ] New version added to `gitlab-token` in Secret Manager
- [ ] Test run succeeded (`devops-reports-orphan-datasets` status = Succeeded)
- [ ] Old secret version disabled in Secret Manager
- [ ] Old GitLab token revoked in GitLab
- [ ] Team notified
- [ ] Next-expiry reminder added to team calendar

---

## Background

| Detail | Value |
|---|---|
| Secret name | `gitlab-token` |
| GCP project | `tefde-gcp-fastoss-dev-gke` |
| Required GitLab scopes | `read_api`, `read_repository` |
| Who fetches the token | `entrypoint.sh` — on every Cloud Run Job start, via `clone_fastoss_b.py` |
| Why Secret Manager | Token is fetched at runtime; never stored in code, Terraform state, or container image |
| Who holds the `secretmanager.versions.add` permission | DevOps platform team (via `devops-reports-runner` SA grants — see `IAM_admin_instructions.md`) |

For the full operator context (symptoms, test run commands, escalation), see
[DevOps Drift Reports - Operator Runbook.html](DevOps%20Drift%20Reports%20-%20Operator%20Runbook.html#pat-rotation).
