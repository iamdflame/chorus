variable "project_id" {
  description = "GCP project that owns every resource here."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run and Artifact Registry."
  type        = string
  default     = "us-central1"
}

variable "firestore_location" {
  description = <<-EOT
    Firestore location. Multi-region by default because the effect store is the durable
    record of every decision the fleet made, and losing it loses the ability to explain
    any of them. Cannot be changed after the database is created.
  EOT
  type        = string
  default     = "nam5"
}

variable "vertex_location" {
  description = <<-EOT
    Vertex AI endpoint. `global` deliberately: gemini-3.5-flash returns 404 on regional
    endpoints for this project, which cost an afternoon to discover and is recorded here
    so it does not cost anyone another one.
  EOT
  type        = string
  default     = "global"
}

variable "service_name" {
  type    = string
  default = "chorus"
}

variable "image" {
  description = <<-EOT
    Container image to run. Terraform owns the infrastructure; the image is built and
    pushed by infra/deploy.sh or CI. Splitting them is deliberate — a `terraform apply`
    that rebuilds a container is one that cannot be run safely to check for drift.
  EOT
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "max_instances" {
  description = <<-EOT
    Safe above 1 only because the effect store is Firestore-backed and convergence across
    instances is proved by scripts/verify_convergence.py. With in-process state this would
    silently multiply model spend by the instance count.
  EOT
  type        = number
  default     = 4
}

variable "public_console" {
  description = <<-EOT
    Whether the console is readable without credentials. True for the hackathon: a judge
    should be able to watch twenty thousand agents collapse without being issued a token.
    Mutation endpoints are gated in the application regardless, and are closed outright
    when no write token is configured.
  EOT
  type        = bool
  default     = true
}
