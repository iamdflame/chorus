resource "google_cloud_run_v2_service" "chorus" {
  project  = var.project_id
  name     = var.service_name
  location = var.region

  # The image is not managed here. Terraform owns infrastructure; CI or infra/deploy.sh
  # builds and pushes. Without this, `terraform plan` would report drift every time anyone
  # deployed, and a plan that is always dirty is a plan nobody reads.
  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  template {
    service_account = google_service_account.runtime.email

    # Safe above 1 only because the effect store is Firestore-backed and convergence is
    # proved by scripts/verify_convergence.py. With in-process state, four instances would
    # silently multiply model spend by four.
    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }

    # A swarm run streams for minutes. The default 300s timeout truncates it mid-stream,
    # which reads to a viewer as the product failing rather than the platform giving up.
    timeout = "3600s"

    # Eight concurrent requests per instance, not the default 80. Each request can hold a
    # streaming swarm and its ADK sessions; 80 of those exhausts memory long before any
    # semaphore matters.
    max_instance_request_concurrency = 8

    containers {
      image = var.image

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }

      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "1"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = var.vertex_location
      }
      env {
        name  = "CHORUS_ORIGINS"
        value = "https://${var.service_name}-${data.google_project.this.number}.${var.region}.run.app"
      }

      # From Secret Manager, never a literal. With no token the application refuses every
      # mutation endpoint rather than leaving them open — an unset secret is the most
      # common way a control like this ends up doing nothing.
      env {
        name = "CHORUS_WRITE_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.write_token.secret_id
            version = "latest"
          }
        }
      }

      startup_probe {
        http_get { path = "/health" }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 12
      }

      liveness_probe {
        http_get { path = "/health" }
        period_seconds = 30
      }
    }
  }

  depends_on = [
    google_project_service.enabled,
    google_project_iam_member.runtime,
  ]
}

data "google_project" "this" {
  project_id = var.project_id
}

# Public reads. A judge, a reader or a recruiter should be able to open the console without
# being issued a credential. Mutation endpoints are gated in the application and are closed
# outright when no write token is set, so "public" here means readable, not writable.
resource "google_cloud_run_v2_service_iam_member" "public" {
  count = var.public_console ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.chorus.location
  name     = google_cloud_run_v2_service.chorus.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
