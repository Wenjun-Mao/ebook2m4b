#!/usr/bin/env bash
set -Eeuo pipefail

MODEL_ID="${MODEL_ID:-hexgrad/Kokoro-82M}"
REVISION="${REVISION:-f3ff3571791e39611d31c381e3a41a3af07b4987}"
SERVICE="${SERVICE:-web}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
DATA_DIR="${DATA_DIR:-${REPO_ROOT}/data}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is not installed." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Error: docker compose is not available." >&2
  exit 1
fi

mkdir -p "${DATA_DIR}/cache/huggingface"

# Compose reads this variable in compose.yaml for the /data bind mount.
export EBOOK2M4B_DATA_HOST_PATH="${DATA_DIR}"

cd "${REPO_ROOT}"

echo "Preseeding ${MODEL_ID}@${REVISION} into ${DATA_DIR}/cache/huggingface ..."

# Use the web service by default so preseeding works even on hosts without NVIDIA runtime.
docker compose run --rm --no-deps \
  -e HF_HOME=/data/cache/huggingface \
  -e TRANSFORMERS_CACHE=/data/cache/huggingface \
  -e MODEL_ID="${MODEL_ID}" \
  -e REVISION="${REVISION}" \
  -e HF_TOKEN \
  "${SERVICE}" \
  python - <<'PY'
import os
from huggingface_hub import snapshot_download

model_id = os.environ["MODEL_ID"]
revision = os.environ.get("REVISION") or None

snapshot_path = snapshot_download(
    repo_id=model_id,
    revision=revision,
    cache_dir="/data/cache/huggingface",
    local_files_only=False,
)
print(f"Cached at: {snapshot_path}")
PY

echo "Done. Your host cache is now preseeded."
