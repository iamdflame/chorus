output "service_url" {
  description = "The deployed console and API."
  value       = google_cloud_run_v2_service.chorus.uri
}

output "agent_identities" {
  description = "One per agent role. scripts/verify_controls.sh attacks these."
  value       = { for k, sa in google_service_account.agent : k => sa.email }
}

output "runtime_identity" {
  description = "What the Cloud Run service runs as. Not an agent identity."
  value       = google_service_account.runtime.email
}

output "trace_console" {
  description = "Where the 39,996 spans from a 20,000-agent run land."
  value       = "https://console.cloud.google.com/traces/list?project=${var.project_id}"
}
