#!/bin/sh
# Runs in the minio-init sidecar after minio is healthy. Creates the bucket
# idempotently, then exits (restart: "no").
set -eu

mc alias set local "$MINIO_ENDPOINT" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" >/dev/null

# -p create parent, ignore "already exists" (owned-by). mb exits non-zero if it
# already exists, so tolerate that.
mc mb -p "local/$MINIO_BUCKET" 2>/dev/null || true

# Bucket is private by default; make it explicit.
mc anonymous set none "local/$MINIO_BUCKET" 2>/dev/null || true

echo "[minio-init] bucket '$MINIO_BUCKET' is ready at $MINIO_ENDPOINT"
