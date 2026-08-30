# One service account per agent role, not one per application.
#
# Per-app is the shortcut, and it means the component that assigns seats holds the
# credential that can call the model and write the database. Splitting them turns the tool
# allowlist from a prompt instruction into an IAM decision — the difference between an
# agent asked not to do something and one that cannot.
#
# scripts/verify_controls.sh attempts the forbidden action from each identity and reports
# the denial, including two probes that must be ALLOWED: an identity that can do nothing
# proves only that it is broken.

locals {
  agents = {
    extractor = {
      description = "Reads unbounded free text. Needs the model, must never write state."
      roles       = ["roles/aiplatform.user"]
    }
    elicitor = {
      description = "Reasons over a bounded projection. Needs the model, must never write state."
      roles       = ["roles/aiplatform.user"]
    }
    allocator = {
      # No aiplatform role, deliberately. Allocation under hard constraints is what
      # deterministic optimisation is for; a model here would be dearer and worse, so it
      # is unreachable rather than merely unused.
      description = "Assigns seats deterministically. No model access at all."
      roles       = ["roles/datastore.viewer"]
    }
  }

  agent_role_pairs = merge([
    for name, cfg in local.agents : {
      for role in cfg.roles : "${name}:${role}" => { agent = name, role = role }
    }
  ]...)
}

resource "google_service_account" "agent" {
  for_each = local.agents

  project      = var.project_id
  account_id   = "chorus-${each.key}"
  display_name = "Chorus ${each.key}"
  description  = each.value.description
}

resource "google_project_iam_member" "agent" {
  for_each = local.agent_role_pairs

  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.agent[each.value.agent].email}"
}

# The identity the Cloud Run service itself runs as. Separate from the agent identities:
# the process that serves HTTP is not the process that reasons, and giving the web tier
# the model credential would make every agent-level restriction above decorative.
resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "chorus-runtime"
  display_name = "Chorus Cloud Run runtime"
  description  = "Serves the API and console. Reads Firestore, calls Vertex, writes traces."
}

resource "google_project_iam_member" "runtime" {
  for_each = toset([
    "roles/datastore.user",
    "roles/aiplatform.user",
    "roles/cloudtrace.agent",
    "roles/secretmanager.secretAccessor",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime.email}"
}
