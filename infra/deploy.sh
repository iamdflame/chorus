#!/usr/bin/env bash
# Deploy Lightcone to Cloud Run.
#
#   ./infra/deploy.sh YOUR_PROJECT_ID [REGION]
#
# Requires billing on the project: Cloud Run, Cloud Build and Artifact Registry are all
# billing-gated. Firestore, Pub/Sub and Vertex AI are not.

set -euo pipefail

PROJECT="${1:?usage: deploy.sh PROJECT_ID [REGION]}"
REGION="${2:-us-central1}"
SERVICE="lightcone"

echo "==> project ${PROJECT} · region ${REGION}"
gcloud config set project "${PROJECT}" >/dev/null

echo "==> enabling services"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  aiplatform.googleapis.com \
  --project="${PROJECT}"

echo "==> ensuring Firestore database"
gcloud firestore databases create --location=nam5 --project="${PROJECT}" 2>/dev/null \
  || echo "    (already exists)"

if [[ -z "${GOOGLE_API_KEY:-}" ]]; then
  echo "!! GOOGLE_API_KEY is not set; the fleet cannot reach Gemini." >&2
  echo "   export it, or switch to Vertex AI by setting GOOGLE_GENAI_USE_VERTEXAI=1" >&2
  exit 1
fi

echo "==> building and deploying"
gcloud run deploy "${SERVICE}" \
  --source . \
  --region "${REGION}" \
  --project "${PROJECT}" \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 3600 \
  --concurrency 8 \
  --max-instances 4 \
  --set-env-vars "GOOGLE_API_KEY=${GOOGLE_API_KEY},GOOGLE_CLOUD_PROJECT=${PROJECT},LIGHTCONE_REGION=${REGION},LIGHTCONE_SNAPSHOT=data/history.json"

URL=$(gcloud run services describe "${SERVICE}" --region "${REGION}" \
        --project "${PROJECT}" --format='value(status.url)')

echo
echo "==> live at ${URL}"
echo "==> health:"
curl -fsS "${URL}/health" && echo
