# infra

`Dockerfile` lives at the repository root, not here.

`gcloud run deploy --source .` only honours a Dockerfile at the root of the build
context; anywhere else it silently falls back to Buildpacks, which auto-detects a single
language and would build the Python service without ever building the console — leaving
the API serving an empty front end.

- `../Dockerfile` — two stages: Node builds the console, Python serves it and the API
- `deploy.sh` — enables services, grants the runtime service account Vertex and Firestore
  access, then builds and deploys
