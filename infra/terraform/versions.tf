# Pinned rather than floating. An unpinned provider means the infrastructure you get
# depends on the day you ran the command, which is the opposite of what declaring it is for.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.20"
    }
  }

  # Uncomment once the bucket exists. Local state is fine for one operator and wrong for
  # two: the second person to run `apply` against local state does not see the first
  # person's resources and proposes to create them again.
  #
  # backend "gcs" {
  #   bucket = "chorus-tfstate"
  #   prefix = "chorus"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
