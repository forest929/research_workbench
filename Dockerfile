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

# The DB lives on a mounted volume, not in the image.
ENV DATABASE_PATH=/data/portfolio_architect.db

EXPOSE 8000

# No --reload in production. One worker: the SQLite path is single-writer; if you
# move to managed Postgres you can raise --workers.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
