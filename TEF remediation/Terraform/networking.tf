# ---------------------------------------------------------------------------
# Networking — dedicated VPC for Cloud Run Jobs to reach private GitLab
#
# PREREQUISITE (outside Terraform scope):
#   A VPN tunnel, Cloud Interconnect, or VPC peering must be configured on
#   this network to route HTTPS traffic to dot-portal.de.pri.o2.com.
#   Once that routing exists the Cloud Run Jobs will clone via HTTPS (:443)
#   through the VPC Access Connector into the private GitLab network.
#
#   Outputs 'vpc_network_name' and 'vpc_connector_id' can be used as inputs
#   to a VPN/Interconnect module if you manage that in a separate Terraform
#   workspace.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# VPC Network
# ---------------------------------------------------------------------------
resource "google_compute_network" "devops_reports" {
  name                    = var.vpc_network_name
  project                 = var.project_id
  auto_create_subnetworks = false

  depends_on = [google_project_service.compute]
}

# ---------------------------------------------------------------------------
# Subnet — dedicated to the VPC Access Connector (/28 is the minimum size)
#
# private_ip_google_access = true lets connector VMs reach Google APIs
# (BigQuery, GCS, Secret Manager) without traversing the public internet.
# ---------------------------------------------------------------------------
resource "google_compute_subnetwork" "connector" {
  name                     = "${var.vpc_network_name}-connector"
  project                  = var.project_id
  region                   = var.region
  network                  = google_compute_network.devops_reports.id
  ip_cidr_range            = var.connector_subnet_cidr
  private_ip_google_access = true
}

# ---------------------------------------------------------------------------
# VPC Access Connector — bridges Cloud Run Jobs into this VPC
#
# min_instances = 2 is the platform minimum; instances are always running.
# machine_type  = e2-micro is sufficient for low-frequency batch jobs.
# ---------------------------------------------------------------------------
resource "google_vpc_access_connector" "devops_reports" {
  name    = "devops-reports-connector"
  project = var.project_id
  region  = var.region

  subnet {
    name       = google_compute_subnetwork.connector.name
    project_id = var.project_id
  }

  machine_type  = "e2-micro"
  min_instances = 2
  max_instances = 3

  depends_on = [google_project_service.vpcaccess]
}

# ---------------------------------------------------------------------------
# Firewall — allow egress to the private GitLab network on HTTPS only
# ---------------------------------------------------------------------------
resource "google_compute_firewall" "allow_egress_gitlab" {
  name      = "${var.vpc_network_name}-allow-egress-gitlab"
  project   = var.project_id
  network   = google_compute_network.devops_reports.id
  direction = "EGRESS"
  priority  = 1000

  destination_ranges = [var.gitlab_network_cidr]

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }
}

# ---------------------------------------------------------------------------
# Firewall — allow egress to Google APIs via Private Google Access
#   199.36.153.8/30  = restricted.googleapis.com
#   199.36.153.4/30  = private.googleapis.com
# Covers BigQuery, GCS, Secret Manager, and Cloud Run API calls.
# ---------------------------------------------------------------------------
resource "google_compute_firewall" "allow_egress_google_apis" {
  name      = "${var.vpc_network_name}-allow-egress-google-apis"
  project   = var.project_id
  network   = google_compute_network.devops_reports.id
  direction = "EGRESS"
  priority  = 1000

  destination_ranges = ["199.36.153.8/30", "199.36.153.4/30"]

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }
}

# ---------------------------------------------------------------------------
# Firewall — deny all other egress (explicit default deny at priority 65534)
# Overrides GCP's implied allow-all egress rule at priority 65535.
# ---------------------------------------------------------------------------
resource "google_compute_firewall" "deny_egress_all" {
  name      = "${var.vpc_network_name}-deny-egress-all"
  project   = var.project_id
  network   = google_compute_network.devops_reports.id
  direction = "EGRESS"
  priority  = 65534

  destination_ranges = ["0.0.0.0/0"]

  deny {
    protocol = "all"
  }
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
output "vpc_network_name" {
  description = "Name of the dedicated VPC network. Attach your VPN gateway / Interconnect VLAN attachment to this network."
  value       = google_compute_network.devops_reports.name
}

output "vpc_connector_id" {
  description = "Resource ID of the VPC Access Connector used by all Cloud Run Jobs."
  value       = google_vpc_access_connector.devops_reports.id
}
