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

# Cloud Tasks and Cloud Run Jobs, for the execution path that outlives a request.
#
# Declared here rather than added by hand because the point of this directory is that the
# infrastructure is reviewable. A queue created by a one-off gcloud command is a queue
# nobody can diff.
resource "google_project_service" "async" {
  for_each = toset([
    "cloudtasks.googleapis.com",
    "cloudscheduler.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_cloud_tasks_queue" "sweeps" {
  project  = var.project_id
  name     = "chorus-sweeps"
  location = var.region

  rate_limits {
    # One sweep at a time. Two concurrent twenty-thousand-agent runs on one instance
    # contend for the same Vertex quota and make both slower; the interesting concurrency
    # is already inside a run.
    max_concurrent_dispatches = 1
    max_dispatches_per_second = 1
  }

  retry_config {
    max_attempts = 3
    # The task is cheap to retry because the run is not: a resumed sweep replays completed
    # effects at zero model cost rather than re-paying for them.
    min_backoff = "10s"
    max_backoff = "300s"
  }

  depends_on = [google_project_service.async]
}
