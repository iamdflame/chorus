# Firestore holds the effect store: every model call, tool call and delegation the fleet
# has made, addressed by content. Losing it does not lose a cache — it loses the ability
# to explain any decision the system has ever taken.

resource "google_firestore_database" "effects" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.firestore_location
  type        = "FIRESTORE_NATIVE"

  # Effects are immutable and content-addressed, so point-in-time recovery is unusually
  # cheap here: there is no write-amplification from updates, only appends.
  point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_ENABLED"

  # An accidental `terraform destroy` should not be able to take the audit log with it.
  delete_protection_state = "DELETE_PROTECTION_ENABLED"

  depends_on = [google_project_service.enabled]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_artifact_registry_repository" "containers" {
  project       = var.project_id
  location      = var.region
  repository_id = "cloud-run-source-deploy"
  format        = "DOCKER"
  description   = "Container images for the Chorus service, built from source by Cloud Build."

  depends_on = [google_project_service.enabled]
}

# The write token that gates fork, merge, replay, adopt and search. Held here, never as an
# environment literal in a deploy script: an env var set on the command line is in shell
# history, in CI logs, and in `gcloud run services describe` output.
resource "google_secret_manager_secret" "write_token" {
  project   = var.project_id
  secret_id = "chorus-write-token"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled]
}
