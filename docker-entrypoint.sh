#!/bin/sh
# Backend container entrypoint.
#
# On startup, pull the SQLite corpus from Nebius Object Storage to DATABASE_PATH
# (unless it's already there — e.g. on a mounted volume), then hand off to the
# CMD (uvicorn). The DB is ~930 MB, far too big to bake into the image, so it
# lives in the bucket and is fetched at boot.
#
# Required env (inject from the MysteryBox secret at deploy time):
#   AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY  — S3 access key for the bucket
#   DB_S3_URI            — s3://research-workbench-bucket/updated_15July/portfolio_architect.db
#   S3_ENDPOINT_URL      — https://storage.eu-north1.nebius.cloud   (default below)
#   AWS_DEFAULT_REGION   — eu-north1                                (default below)
#   DATABASE_PATH        — /data/portfolio_architect.db            (default below)
set -e

DB_PATH="${DATABASE_PATH:-/data/portfolio_architect.db}"
S3_ENDPOINT="${S3_ENDPOINT_URL:-https://storage.eu-north1.nebius.cloud}"
REGION="${AWS_DEFAULT_REGION:-eu-north1}"

if [ -f "$DB_PATH" ]; then
    echo "[entrypoint] DB already present at $DB_PATH ($(du -h "$DB_PATH" | cut -f1)) — skipping download"
elif [ -n "$DB_S3_URI" ]; then
    if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
        echo "[entrypoint] ERROR: DB_S3_URI set but AWS credentials missing in env." >&2
        exit 1
    fi
    echo "[entrypoint] downloading $DB_S3_URI -> $DB_PATH"
    mkdir -p "$(dirname "$DB_PATH")"
    aws s3 cp "$DB_S3_URI" "$DB_PATH" \
        --endpoint-url "$S3_ENDPOINT" --region "$REGION" --only-show-errors
    echo "[entrypoint] download complete ($(du -h "$DB_PATH" | cut -f1))"
else
    echo "[entrypoint] WARNING: no DB at $DB_PATH and DB_S3_URI unset — the app will create an empty SQLite DB." >&2
fi

exec "$@"
