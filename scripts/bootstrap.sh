#!/usr/bin/env bash
# One command to a runnable checkout. No cloud account required for the offline proofs.
#
#   ./scripts/bootstrap.sh

set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> python venv"
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

echo "==> console"
if command -v npm >/dev/null 2>&1; then
  npm install --prefix console --no-audit --no-fund --silent
else
  echo "    npm not found — skipping the console (the proofs do not need it)"
fi

if [[ ! -f .env ]]; then
  cat > .env <<'ENV'
# Vertex AI (preferred: bills through Cloud billing, no key in the image)
# GOOGLE_GENAI_USE_VERTEXAI=1
# GOOGLE_CLOUD_PROJECT=your-project
# GOOGLE_CLOUD_LOCATION=global

# or an AI Studio key: https://aistudio.google.com/apikey
# GOOGLE_API_KEY=
ENV
  echo "==> wrote .env template (the offline proofs run without it)"
fi

cat <<'DONE'

==> ready. The offline proofs need no credentials:

    .venv/bin/python scripts/verify_determinism.py
    .venv/bin/python scripts/verify_collapse.py
    .venv/bin/python scripts/ablation.py
    .venv/bin/python -m pytest tests/ -q

    Live model runs need .env filled in:
    .venv/bin/python scripts/prove_swarm.py --agents 2000
DONE
