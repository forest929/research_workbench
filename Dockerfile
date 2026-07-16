# Backend image — FastAPI + uvicorn. No database inside: the SQLite file (or a
# managed Postgres connection) is provided at runtime via a mounted volume /
# DATABASE_PATH, so the image stays small and the 3.7 GB corpus never gets baked
# into a layer.
FROM python:3.12-slim

WORKDIR /app

# Install the package + its deps first (better layer caching).
COPY pyproject.toml ./
COPY portfolio_architect ./portfolio_architect
COPY api ./api
RUN pip install --no-cache-dir .

# AWS CLI: the entrypoint uses it to pull the SQLite corpus from Nebius Object
# Storage (S3-compatible) at startup — the ~930 MB DB is never baked in.
RUN pip install --no-cache-dir awscli

# Startup DB download → then uvicorn. See docker-entrypoint.sh.
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# The DB is fetched to this path on boot (or mount a volume here to persist it).
ENV DATABASE_PATH=/data/portfolio_architect.db

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
# No --reload in production. One worker: the SQLite path is single-writer; if you
# move to managed Postgres you can raise --workers.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
