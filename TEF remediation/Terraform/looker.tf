# ---------------------------------------------------------------------------
# Looker Studio — no service account required
# ---------------------------------------------------------------------------
# Dashboards are built in Looker Studio (free, formerly Data Studio) connecting
# directly to the devops_reports BigQuery dataset.
#
# Looker Studio authenticates via the viewer's own Google OAuth identity —
# no service account key is needed. Share dashboards at the Looker Studio level
# to control who can view them (e.g. restrict to domain:yourcompany.com).
#
# To connect Looker Studio to BigQuery:
#   Looker Studio → Create → Data Source → BigQuery
#   → select project tefde-gcp-fastoss-dev → dataset devops_reports
#   → select the desired table or use the views (e.g. execution_daily_summary)
# ---------------------------------------------------------------------------
