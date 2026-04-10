#!/usr/bin/env bash
set -Eeuo pipefail

MODEL_ID="${MODEL_ID:-hexgrad/Kokoro-82M}"
REVISION="${REVISION:-f3ff3571791e39611d31c381e3a41a3af07b4987}"
REF_NAME="${REF_NAME:-main}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
DATA_DIR="${DATA_DIR:-${REPO_ROOT}/data}"

MISSING_TOOLS=()
command -v curl >/dev/null 2>&1 || MISSING_TOOLS+=("curl")
command -v jq >/dev/null 2>&1 || MISSING_TOOLS+=("jq")

if [[ "${#MISSING_TOOLS[@]}" -gt 0 ]]; then
  echo "Error: missing required tools: ${MISSING_TOOLS[*]}" >&2
  echo "Reminder: install prerequisites on Ubuntu with:" >&2
  echo "  sudo apt-get update && sudo apt-get install -y curl jq" >&2
  exit 1
fi

MODEL_KEY="${MODEL_ID//\//--}"
CACHE_ROOT="${DATA_DIR}/cache/huggingface"
REPO_CACHE_DIR="${CACHE_ROOT}/hub/models--${MODEL_KEY}"
SNAPSHOT_DIR="${REPO_CACHE_DIR}/snapshots/${REVISION}"
REFS_DIR="${REPO_CACHE_DIR}/refs"

mkdir -p "${SNAPSHOT_DIR}" "${REFS_DIR}"

echo "Fetching model manifest for ${MODEL_ID}@${REVISION} ..."
META_JSON="$(mktemp)"
cleanup() {
  rm -f "${META_JSON}"
}
trap cleanup EXIT

curl -fLsS \
  "https://huggingface.co/api/models/${MODEL_ID}/revision/${REVISION}" \
  -o "${META_JSON}"

mapfile -t FILES < <(jq -r '.siblings[].rfilename' "${META_JSON}")

if [[ "${#FILES[@]}" -eq 0 ]]; then
  echo "Error: no files returned for ${MODEL_ID}@${REVISION}." >&2
  exit 1
fi

echo "Downloading ${#FILES[@]} files to ${SNAPSHOT_DIR} ..."
for rel_path in "${FILES[@]}"; do
  target_path="${SNAPSHOT_DIR}/${rel_path}"
  target_dir="$(dirname "${target_path}")"
  mkdir -p "${target_dir}"

  if [[ -s "${target_path}" ]]; then
    echo "[skip] ${rel_path}"
    continue
  fi

  tmp_path="${target_path}.part"
  echo "[get ] ${rel_path}"
  curl -fL \
    "https://huggingface.co/${MODEL_ID}/resolve/${REVISION}/${rel_path}" \
    -o "${tmp_path}"
  mv "${tmp_path}" "${target_path}"
done

printf '%s' "${REVISION}" > "${REFS_DIR}/${REF_NAME}"

echo "Done. Hugging Face cache preseeded at: ${REPO_CACHE_DIR}"
echo "Ref written: ${REFS_DIR}/${REF_NAME} -> ${REVISION}"
echo "Use these env vars at runtime:"
echo "  HF_HOME=${CACHE_ROOT}"
echo "  TRANSFORMERS_CACHE=${CACHE_ROOT}"
