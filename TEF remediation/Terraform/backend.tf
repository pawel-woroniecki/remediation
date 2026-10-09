terraform {
  backend "gcs" {
    bucket = "tefde-gcp-fastoss-terraform-states"
    prefix = "TEF_remediation/PROD"
  }
}
