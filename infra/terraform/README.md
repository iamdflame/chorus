# Infrastructure as code

`deploy.sh` builds and ships a container. It is not infrastructure-as-code: it issues
imperative `gcloud` commands, it cannot tell you what exists, and it cannot tell you what
has drifted. This directory declares the infrastructure instead.

The split is deliberate and holds in both directions:

| | owns | why |
| --- | --- | --- |
| **Terraform** | project services, IAM, Firestore, Artifact Registry, Secret Manager, the Cloud Run service | declarative, reviewable, drift-detectable |
| **`deploy.sh` / CI** | building and pushing the image | a `terraform apply` that rebuilds a container cannot be run safely just to check for drift |

`run.tf` therefore ignores changes to the container image. Without that, `terraform plan`
would report drift after every deployment, and a plan that is always dirty is a plan
nobody reads.

## What it declares

```
services.tf   the seven APIs this project actually calls, and nothing else
iam.tf        one service account per agent role, plus a separate runtime identity
data.tf       Firestore (delete-protected), Artifact Registry, the write-token secret
run.tf        the Cloud Run service, its probes, limits and secret wiring
```

## Running it

```bash
terraform init
terraform plan  -var="project_id=$(gcloud config get-value project)"
terraform apply -var="project_id=$(gcloud config get-value project)"
```

Validated with `terraform validate` and planned against a live project: **23 to add,
0 to change, 0 to destroy.**

## Importing what already exists

This project was built before the Terraform was written, so several resources exist and
were created by `gcloud`. A first `apply` would try to create them again and fail. Import
them first — this is the honest operational sequence, not a footnote:

```bash
P=$(gcloud config get-value project)

for a in extractor elicitor allocator; do
  terraform import -var="project_id=$P" \
    "google_service_account.agent[\"$a\"]" \
    "projects/$P/serviceAccounts/chorus-$a@$P.iam.gserviceaccount.com"
done

terraform import -var="project_id=$P" google_firestore_database.effects \
  "projects/$P/databases/(default)"

terraform import -var="project_id=$P" \
  google_artifact_registry_repository.containers \
  "projects/$P/locations/us-central1/repositories/cloud-run-source-deploy"

terraform import -var="project_id=$P" google_cloud_run_v2_service.chorus \
  "projects/$P/locations/us-central1/services/chorus"
```

## Two things this does not do

**State is local.** The GCS backend is written and commented out in `versions.tf`. Local
state is fine for one operator and wrong for two: the second person to run `apply` does not
see the first person's resources and proposes to create them all again.

**Model Armor is application-level, not the Google Cloud service.** `armor/` implements
screening and structural containment in this repository, and `scripts/verify_armor.py`
proves the containment properties. The managed Model Armor product is not provisioned here,
and is not claimed to be.
