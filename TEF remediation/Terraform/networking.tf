# ---------------------------------------------------------------------------
# Networking — Shared VPC connectivity (provisioned by the TEF Networking Team)
#
# The following resources are NOT managed by this Terraform workspace.
# They were provisioned by the TEF Networking Team:
#
#   Shared VPC network  : tefde-gcp-network-shared-ic-1-vpc-devlowapp
#                          (host project: tefde-gcp-network-shared-ic-1)
#   Subnet               : s-shared-ew3-devlow-fastoss-dev-gke-connect-1
#                          (europe-west3, attached for tefde-gcp-fastoss-dev-gke)
#   VPC Access Connector : fastoss-dev-gke-connector
#                          (europe-west3, project tefde-gcp-fastoss-dev-gke)
#
# Firewall rules and routing to the private GitLab network and to Google
# APIs are managed centrally by the Networking Team on the shared VPC.
# Do not attempt to create firewall rules in this workspace for a network
# this project does not own.
# ---------------------------------------------------------------------------

data "google_vpc_access_connector" "devops_reports" {
  name    = var.vpc_connector_name
  project = var.project_id
  region  = var.region
}

# ---------------------------------------------------------------------------
# Legacy resources — superseded by the Networking Team's Shared VPC above.
# Kept commented out for reference only; do not uncomment.
# ---------------------------------------------------------------------------
# resource "google_compute_network" "devops_reports" {
#   name                    = var.vpc_network_name
#   project                 = var.project_id
#   auto_create_subnetworks = false
#
#   depends_on = [google_project_service.compute]
# }
#
# resource "google_compute_subnetwork" "connector" {
#   name                     = "${var.vpc_network_name}-connector"
#   project                  = var.project_id
#   region                   = var.region
#   network                  = google_compute_network.devops_reports.id
#   ip_cidr_range            = var.connector_subnet_cidr
#   private_ip_google_access = true
# }
#
# resource "google_vpc_access_connector" "devops_reports" {
#   name    = "devops-reports-connector"
#   project = var.project_id
#   region  = var.region
#
#   subnet {
#     name       = google_compute_subnetwork.connector.name
#     project_id = var.project_id
#   }
#
#   machine_type  = "e2-micro"
#   min_instances = 2
#   max_instances = 3
#
#   depends_on = [google_project_service.vpcaccess]
# }
#
# resource "google_compute_firewall" "allow_egress_gitlab" {
#   name      = "${var.vpc_network_name}-allow-egress-gitlab"
#   project   = var.project_id
#   network   = google_compute_network.devops_reports.id
#   direction = "EGRESS"
#   priority  = 1000
#
#   destination_ranges = [var.gitlab_network_cidr]
#
#   allow {
#     protocol = "tcp"
#     ports    = ["443"]
#   }
# }
#
# resource "google_compute_firewall" "allow_egress_google_apis" {
#   name      = "${var.vpc_network_name}-allow-egress-google-apis"
#   project   = var.project_id
#   network   = google_compute_network.devops_reports.id
#   direction = "EGRESS"
#   priority  = 1000
#
#   destination_ranges = ["199.36.153.8/30", "199.36.153.4/30"]
#
#   allow {
#     protocol = "tcp"
#     ports    = ["443"]
#   }
# }
#
# resource "google_compute_firewall" "deny_egress_all" {
#   name      = "${var.vpc_network_name}-deny-egress-all"
#   project   = var.project_id
#   network   = google_compute_network.devops_reports.id
#   direction = "EGRESS"
#   priority  = 65534
#
#   destination_ranges = ["0.0.0.0/0"]
#
#   deny {
#     protocol = "all"
#   }
# }

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
output "vpc_connector_id" {
  description = "Resource ID of the VPC Access Connector (provisioned by the Networking Team) used by all Cloud Run Jobs."
  value       = data.google_vpc_access_connector.devops_reports.id
}
