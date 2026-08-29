# Two stages: build the console with Node, then serve everything from one Python image.
# One container rather than two services because the console is a static bundle FastAPI
# already mounts — a second Cloud Run service would add a cross-origin hop and a second
# cold start for no benefit.

FROM node:20-slim AS console
WORKDIR /build
COPY console/package.json console/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY console/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so a code change does not invalidate the layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY kernel/ ./kernel/
COPY world/ ./world/
COPY fleet/ ./fleet/
COPY swarm/ ./swarm/
COPY optimizer/ ./optimizer/
COPY api/ ./api/
COPY scripts/ ./scripts/
COPY data/ ./data/
COPY --from=console /build/dist ./console/dist

# Cloud Run supplies PORT and expects the container to listen on it.
ENV PORT=8080
EXPOSE 8080

# Single worker on purpose: the Engine holds the branch tree in memory and serialises
# mutations behind a lock. Multiple workers would each hold a divergent copy.
CMD exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 75
