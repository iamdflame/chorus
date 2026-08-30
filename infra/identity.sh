#!/usr/bin/env bash
# One service account per agent role, each granted only what its job needs.
#
# Per app rather than per role is the common shortcut, and it means the component that
# assigns seats holds the credential that can call the model, write to the database, and
# talk to every other service. Splitting them costs nothing and turns the tool allowlist
# from a prompt instruction into an IAM decision — the difference between an agent that
# is asked not to do something and one that cannot.
#
# Roles are deliberately narrow:
#   extractor  reads unbounded free text, needs the model, must never write state
#   elicitor   reasons over a bounded projection, needs the model, must never write state
#   allocator  assigns seats deterministically; needs NO model access at all
#
# Run once. Idempotent — re-running reports the existing bindings.
#
#   ./infra/identity.sh

set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project)}"
ROLES=("extractor:roles/aiplatform.user"
       "elicitor:roles/aiplatform.user"
       "allocator:roles/datastore.viewer")

echo "  Project: ${PROJECT}"

for entry in "${ROLES[@]}"; do
  name="${entry%%:*}"
  role="${entry##*:}"
  email="chorus-${name}@${PROJECT}.iam.gserviceaccount.com"

  if ! gcloud iam service-accounts describe "$email" --project="$PROJECT" >/dev/null 2>&1; then
    gcloud iam service-accounts create "chorus-${name}" \
      --display-name="Chorus ${name}" --project="$PROJECT"
  fi

  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:${email}" \
    --role="$role" --condition=None --quiet >/dev/null
  echo "  ${name}: ${role}"
done

# Needed for scripts/verify_controls.sh to attempt actions as each identity.
CALLER="$(gcloud config get-value account)"
for entry in "${ROLES[@]}"; do
  name="${entry%%:*}"
  email="chorus-${name}@${PROJECT}.iam.gserviceaccount.com"
  gcloud iam service-accounts add-iam-policy-binding "$email" \
    --member="user:${CALLER}" \
    --role="roles/iam.serviceAccountTokenCreator" --quiet >/dev/null
done

echo
echo "  Identities ready. Prove they are enforced:"
echo "    ./scripts/verify_controls.sh"
