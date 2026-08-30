# Every API this project actually calls, and nothing it does not.
#
# The temptation is to enable a generous set and move on. Each enabled API is surface area
# on a project that also holds the effect log, so the list is exactly what the code uses:
# grep for the client and it is here, or it is not enabled.

locals {
  services = [
    "run.googleapis.com",              # serves the API and console
    "cloudbuild.googleapis.com",       # builds the container from source
    "artifactregistry.googleapis.com", # stores it
    "firestore.googleapis.com",        # the durable effect store
    "aiplatform.googleapis.com",       # Vertex AI: gemini-3.5-flash, embeddings
    "cloudtrace.googleapis.com",       # 39,996 spans from one run
    "secretmanager.googleapis.com",    # the write token, never an env literal
  ]
}

resource "google_project_service" "enabled" {
  for_each = toset(local.services)

  project = var.project_id
  service = each.value

  # Disabling an API on destroy would take Firestore's data with it in some cases, and a
  # `terraform destroy` on a scratch environment should not be able to delete the record
  # of what the fleet did in production.
  disable_on_destroy = false
}
